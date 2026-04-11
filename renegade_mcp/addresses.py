"""Runtime address resolution for multi-emulator support.

All heap-allocated RAM addresses shift by a uniform delta between emulators
and save files. The delta depends on heap allocation order at boot time,
which varies by emulator, save file, and even across boots of the same save.

Known ranges observed:
  - DeSmuME: delta = 0 (reference addresses)
  - melonDS: delta ~ -0x20 to -0x5C (varies per boot)

ARM9 addresses (0x02000000-0x02110000) are fixed across all configurations.

Detection strategy: scan a range of candidate deltas, validating each with
multiple canary values (party count 1-6, badge popcount 0-8, and at least
one species ID in a valid range) to avoid false positives.
"""

from __future__ import annotations

from typing import Any

# ── Detection state ──

_delta: int | None = None

# Scan range for delta detection (covers all observed values with margin)
_SCAN_MIN = -0x200
_SCAN_MAX = 0x200
_SCAN_STEP = 4

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

def _read_canary(emu: Any, addr: int, size: str = "long") -> int | None:
    """Read a single memory value, handling both bridge and MCP response formats."""
    try:
        val = emu.read_memory(addr, size=size)
    except Exception:
        return None
    if isinstance(val, dict):
        # MCP format: {"values": [x]} or bridge format: {"value": x}
        if "value" in val:
            return val["value"]
        return val.get("values", [None])[0]
    return val


def detect_shift(emu: Any) -> int:
    """Detect the heap address shift by scanning candidate deltas.

    Scans a range of deltas and validates each with multiple canary values:
    party count (1-6), badge popcount (0-8), and first species ID (1-649).
    This handles the fact that the delta varies between boots, emulators,
    and save files.

    Args:
        emu: Connected EmulatorClient instance.

    Returns:
        The detected delta.

    Raises:
        RuntimeError: If no valid delta is found.
    """
    global _delta

    party_count_ref = _DESMUME["ENCRYPTED_PARTY_COUNT"]
    badge_ref = _DESMUME["SAVE_BLOCK_BASE"] + 0x82
    species_ref = _DESMUME["SPECIES_ARRAY_BASE"]

    candidates = []

    for candidate in range(_SCAN_MIN, _SCAN_MAX + 1, _SCAN_STEP):
        pc = _read_canary(emu, party_count_ref + candidate)
        if pc is None or not (1 <= pc <= 6):
            continue

        badge = _read_canary(emu, badge_ref + candidate, "byte")
        if badge is None:
            continue
        badge_count = bin(badge).count("1")
        if not (0 <= badge_count <= 8):
            continue

        # Third canary: first species ID must be a valid Pokemon (1-649)
        species = _read_canary(emu, species_ref + candidate, "short")
        if species is None or not (1 <= species <= 649):
            continue

        candidates.append((candidate, pc, badge_count, species))

    if not candidates:
        raise RuntimeError(
            f"Could not detect emulator heap layout. Scanned deltas "
            f"{_SCAN_MIN} to {_SCAN_MAX} (step {_SCAN_STEP}) but no valid "
            "party count (1-6) + badge count (0-8) + species ID (1-649) found. "
            "Verify the game is loaded and a save file is active."
        )

    # Refine: validate ALL party species to eliminate false positives.
    # The real delta will have valid species IDs for every party slot.
    refined = []
    for candidate, pc, badge_count, species in candidates:
        valid_species = 1  # first already validated above
        for i in range(1, pc):
            sp = _read_canary(
                emu, species_ref + candidate + i * SPECIES_ARRAY_STRIDE, "short"
            )
            if sp is not None and 1 <= sp <= 649:
                valid_species += 1
        refined.append((candidate, pc, badge_count, species, valid_species))

    # Prefer: most valid party species (strongest signal), then highest badge
    # count, then smallest absolute delta.
    best = max(refined, key=lambda c: (c[4], c[2], -abs(c[0])))
    _delta = best[0]
    return best[0]


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
