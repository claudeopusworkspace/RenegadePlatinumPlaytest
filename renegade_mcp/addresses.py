"""Runtime address resolution for multi-emulator support.

All heap-allocated RAM addresses shift by a uniform delta between emulators:
  - DeSmuME: delta = 0 (reference addresses)
  - melonDS: delta = -0x20

ARM9 addresses (0x02000000-0x02110000) are fixed across both emulators.

Detection strategy: read the party count at the DeSmuME reference address.
If it's a valid value (1-6), delta=0. Otherwise try -0x20. Cross-validate
with badge count (0-8) to avoid false positives.
"""

from __future__ import annotations

from typing import Any

# ── Detection state ──

_delta: int | None = None

# Known shift candidates (DeSmuME=0, melonDS=-0x20)
_KNOWN_DELTAS = [0, -0x20]

# ── DeSmuME reference addresses (delta=0 baseline) ──

_DESMUME: dict[str, int] = {
    # Save Block group
    "SAVE_BLOCK_BASE":       0x0227E1D0,
    "ENCRYPTED_PARTY_COUNT": 0x0227E26C,
    "ENCRYPTED_PARTY_BASE":  0x0227E270,
    "SPECIES_ARRAY_BASE":    0x0227F3E8,
    "PLAYER_POS_BASE":       0x0227F450,
    "BAG_BASE":              0x0227E800,
    "FLAGS_ARRAY":           0x0227F1BC,
    "BOX_DATA_BASE":         0x0228B100,
    # FieldSystem group
    "PAUSE_CURSOR_ADDR":     0x0229FA28,
    "BAG_CURSOR_PTR_ADDR":   0x0229FA30,
    "PLAYER_FACING_ADDR":    0x022A1A60,
    "OBJ_ARRAY_FPX_BASE":   0x022A1AA8,
    # PlayerData group (within FieldOverworldState, offset +0x90 from PLAYER_POS_BASE)
    "CYCLING_GEAR_ADDR":     0x0227F4E0,  # u16: 0=walking, 1=cycling
    # BattleContext group
    "BATTLE_BASE":           0x022C5774,
    "BATTLE_END_FLAG_ADDR":  0x022C5B53,
    "LEVEL_UP_MONS_ADDR":    0x022C5B3D,
    "PARTY_ORDER_ADDR":      0x022C5B60,
    "TASK_DATA_PTR_ADDR":    0x022C2BAC,
    # TextPrinter + scan regions
    "TP_BASE":               0x02271534,
    "OVERWORLD_SCAN_START":  0x022A7000,
    "BATTLE_SCAN_START":     0x0228A000,
    "SM_SCAN_START":         0x0229F000,
    # Terrain (RAM fallback, unreliable but included for completeness)
    "TERRAIN_ADDR":          0x0231D1E4,
}

# ── ARM9 fixed addresses (no shift) ──

ZONE_HEADER_BASE = 0x020E601E
ZONE_HEADER_STRIDE = 24

# ── Struct-internal constants (no shift) ──

ENCRYPTED_SLOT_SIZE = 236
PARTY_MAX_SLOTS = 6
SPECIES_ARRAY_STRIDE = 8

BATTLE_SLOT_SIZE = 0xC0  # 192 bytes per BattleMon
BATTLE_MAX_SLOTS = 4

OBJ_STRIDE = 0x128  # 296 bytes per MapObject
OBJ_MAX_ENTRIES = 64

BOX_SLOT_SIZE = 136
SLOTS_PER_BOX = 30
NUM_BOXES = 18

# Scan region sizes (constant, not shifted)
OVERWORLD_SCAN_SIZE = 0x2800
BATTLE_SCAN_SIZE = 0x180000
SM_SCAN_SIZE = 0x11000


# ── Public API ──

def detect_shift(emu: Any) -> int:
    """Detect the heap address shift by reading canary values.

    Tries each known delta: reads party count and badge count at the
    shifted address. If both are valid, caches and returns the delta.

    Args:
        emu: Connected EmulatorClient instance.

    Returns:
        The detected delta (0 for DeSmuME, -0x20 for melonDS).

    Raises:
        RuntimeError: If no valid delta is found.
    """
    global _delta

    party_count_ref = _DESMUME["ENCRYPTED_PARTY_COUNT"]
    # Badge byte is at SAVE_BLOCK_BASE + 0x82
    badge_ref = _DESMUME["SAVE_BLOCK_BASE"] + 0x82

    for candidate in _KNOWN_DELTAS:
        pc_addr = party_count_ref + candidate
        badge_addr = badge_ref + candidate

        try:
            pc = emu.read_memory(pc_addr, size="long")
            badge = emu.read_memory(badge_addr, size="byte")
        except Exception:
            continue

        if isinstance(pc, dict):
            pc = pc.get("values", [0])[0]
        if isinstance(badge, dict):
            badge = badge.get("values", [0])[0]

        if 0 <= pc <= 6 and 0 <= badge <= 8:
            _delta = candidate
            return candidate

    raise RuntimeError(
        "Could not detect emulator heap layout. Tried deltas "
        f"{_KNOWN_DELTAS} but no valid party count (0-6) + badge count (0-8) found. "
        "Verify the game is loaded and a save file is active."
    )


def addr(name: str) -> int:
    """Get a resolved heap address by name.

    Raises RuntimeError if detect_shift() hasn't been called yet.
    """
    if _delta is None:
        raise RuntimeError(
            "Address resolution not initialized. "
            "The emulator connection should call detect_shift() automatically."
        )
    if name not in _DESMUME:
        raise KeyError(f"Unknown address name: {name!r}")
    return _DESMUME[name] + _delta


def get_delta() -> int | None:
    """Return the current delta, or None if not yet detected."""
    return _delta


def reset() -> None:
    """Clear cached delta. Next addr() call will fail until detect_shift() runs."""
    global _delta
    _delta = None
