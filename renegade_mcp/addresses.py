"""Runtime address resolution for multi-emulator support.

All heap-allocated RAM addresses shift by a uniform delta between emulators
and save files. The delta depends on heap allocation order at boot time,
which varies by emulator, save file, and even across boots of the same save.

Known ranges observed:
  - DeSmuME: delta = 0 (reference addresses)
  - melonDS: delta ~ -0x20 to -0x5C (varies per boot)

ARM9 addresses (0x02000000-0x02110000) are fixed across all configurations.

**Multi-group deltas**: The Platinum save block (PlayerData / Party / Bag)
and FieldOverworldState (live PLAYER_POS_BASE, CYCLING_GEAR_ADDR) are
*separate* heap allocations that usually share a delta but can diverge.
We detect each group's delta independently:

  - "save_block"  → validated by player-name signature at SAVE_BLOCK_BASE + 0x68
  - "field_ow"    → validated by PLAYER_POS_BASE struct contents (map_id, x, y)

The name signature works even pre-starter (party count = 0) where the
legacy party-count canary silently false-positives on memory noise.
"""

from __future__ import annotations

from typing import Any

# ── Detection state ──

# Per-group detected deltas. Populated by detect_shift().
_deltas: dict[str, int | None] = {"save_block": None, "field_ow": None}

# Scan range for delta detection (covers all observed values with margin)
_SCAN_MIN = -0x200
_SCAN_MAX = 0x200
_SCAN_STEP = 4

# Player name sits at this offset inside the save block (Gen4 u16 chars, 0xFFFF-terminated).
PLAYER_NAME_OFFSET = 0x68

# Gen4 charmap ranges for name chars (digits + A-Z + a-z, contiguous).
# See text_encoding.CHAR_MAP: 0x0121..0x012A = digits, 0x012B..0x0144 = A-Z,
# 0x0145..0x015E = a-z, 0x0161..0x016A = alt digits.
_NAME_CHAR_MIN = 0x0121
_NAME_CHAR_MAX = 0x016A
_NAME_TERMINATOR = 0xFFFF
_NAME_MAX_CHARS = 7  # Platinum caps player name at 7 chars


def _is_valid_name_char(v: int) -> bool:
    """True if v is a Gen4 charmap code for a letter or digit."""
    return _NAME_CHAR_MIN <= v <= _NAME_CHAR_MAX


# ── DeSmuME reference addresses (delta=0 baseline) ──

_DESMUME: dict[str, int] = {
    # Save Block group (PlayerData / Party / Bag / Boxes)
    "SAVE_BLOCK_BASE":       0x0227E1D0,
    "ENCRYPTED_PARTY_COUNT": 0x0227E26C,
    "ENCRYPTED_PARTY_BASE":  0x0227E270,
    "SPECIES_ARRAY_BASE":    0x0227F3E8,
    "BAG_BASE":              0x0227E800,
    "FLAGS_ARRAY":           0x0227F1BC,
    "BOX_DATA_BASE":         0x0228B100,
    # FieldOverworldState group (live position, cycling gear)
    # CYCLING_GEAR_ADDR is explicitly +0x90 from PLAYER_POS_BASE in the same struct.
    "PLAYER_POS_BASE":       0x0227F450,
    "CYCLING_GEAR_ADDR":     0x0227F4E0,  # u16: 0=walking, 1=cycling
    # FieldSystem group (cursor, facing, map objects) — uses save_block delta by default.
    "PAUSE_CURSOR_ADDR":     0x0229FA28,
    "BAG_CURSOR_PTR_ADDR":   0x0229FA30,
    "PLAYER_FACING_ADDR":    0x022A1A60,
    "OBJ_ARRAY_FPX_BASE":    0x022A1AA8,
    # BattleContext group — uses save_block delta by default.
    "BATTLE_BASE":           0x022C5774,
    "BATTLE_END_FLAG_ADDR":  0x022C5B53,
    "LEVEL_UP_MONS_ADDR":    0x022C5B3D,
    "PARTY_ORDER_ADDR":      0x022C5B60,
    "TASK_DATA_PTR_ADDR":    0x022C2BAC,
    # TextPrinter + scan regions — uses save_block delta by default.
    "TP_BASE":               0x02271534,
    "OVERWORLD_SCAN_START":  0x022A7000,
    "BATTLE_SCAN_START":     0x022F0000,
    "SM_SCAN_START":         0x0229F000,
    # Terrain (RAM fallback) — uses save_block delta by default.
    "TERRAIN_ADDR":          0x0231D1E4,
}

# Maps each address name to its heap group. Names not listed here default
# to "save_block" (preserves legacy behavior for addresses we haven't
# empirically split).
_GROUPS: dict[str, str] = {
    "PLAYER_POS_BASE":   "field_ow",
    "CYCLING_GEAR_ADDR": "field_ow",
}

# ── ARM9 fixed addresses (no shift) ──

ZONE_HEADER_BASE = 0x020E601E
ZONE_HEADER_STRIDE = 24

# Bike gear state: byte at this address, 0 = fast gear (4th), 1 = slow gear (3rd).
# Toggle by pressing B while on bicycle. Required for climbing bike slopes.
# Located in ARM9 BSS region — no heap delta shift needed.
BIKE_GEAR_STATE_ADDR = 0x021BF6AC

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
BATTLE_SCAN_SIZE = 0x20000
SM_SCAN_SIZE = 0x11000


# ── Canary helpers ──

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


def _name_length_at(emu: Any, addr: int) -> int:
    """Return the length of a valid Gen4 player name at `addr`, or 0 if none.

    A name is a run of letter/digit chars followed by a 0xFFFF terminator
    (or the full 7-char cap). Additionally requires that the u16 immediately
    *before* `addr` is NOT a valid name char — this disambiguates between
    the true name start and later positions inside the same name (e.g.
    "CLAUDE" would otherwise also match starting at "LAUDE", "AUDE", etc.).
    """
    # Reject mid-name positions: char before start must not be a letter/digit.
    prev = _read_canary(emu, addr - 2, "short")
    if prev is not None and _is_valid_name_char(prev):
        return 0

    first = _read_canary(emu, addr, "short")
    if first is None or not _is_valid_name_char(first):
        return 0

    length = 1
    for i in range(1, _NAME_MAX_CHARS + 1):
        c = _read_canary(emu, addr + i * 2, "short")
        if c is None:
            return 0
        if c == _NAME_TERMINATOR:
            return length
        if not _is_valid_name_char(c):
            return 0
        length += 1
    # Hit max length without terminator — accept as 7-char name.
    return length


def _has_valid_name_at(emu: Any, addr: int) -> bool:
    """Convenience wrapper — kept for backward-compat with internal callers."""
    return _name_length_at(emu, addr) > 0


# ── Per-group detection ──

def _detect_save_block_delta(emu: Any) -> int:
    """Find the save-block heap shift.

    Primary canary: player-name signature at SAVE_BLOCK_BASE + 0x68. Works
    regardless of party count, trainer ID, or game progress — the name is
    always set during the unskippable new-game intro.

    Secondary canaries (party count 0-6, badge popcount 0-8, first species 0
    or 1-649) are used only to rank candidates when multiple deltas have
    valid names.
    """
    sb_ref = _DESMUME["SAVE_BLOCK_BASE"]
    party_ref = _DESMUME["ENCRYPTED_PARTY_COUNT"]
    badge_ref = sb_ref + 0x82
    species_ref = _DESMUME["SPECIES_ARRAY_BASE"]

    candidates: list[tuple[int, int]] = []
    for cand in range(_SCAN_MIN, _SCAN_MAX + 1, _SCAN_STEP):
        # Primary gate: name must be valid, with length as a strong signal.
        name_len = _name_length_at(emu, sb_ref + cand + PLAYER_NAME_OFFSET)
        if name_len == 0:
            continue

        # Score: name length dominates (longer = more likely the real start),
        # plus small bonuses for secondary canaries matching.
        score = name_len * 10

        pc = _read_canary(emu, party_ref + cand)
        if pc is not None and 0 <= pc <= 6:
            score += 1

        badge = _read_canary(emu, badge_ref + cand, "byte")
        if badge is not None and 0 <= bin(badge).count("1") <= 8:
            score += 1

        sp = _read_canary(emu, species_ref + cand, "short")
        if sp is not None and (sp == 0 or 1 <= sp <= 649):
            score += 1

        candidates.append((cand, score))

    if not candidates:
        raise RuntimeError(
            f"Could not detect save-block heap shift. Scanned deltas "
            f"{_SCAN_MIN:+#x}..{_SCAN_MAX:+#x} (step {_SCAN_STEP}) for player-name "
            f"signature at SAVE_BLOCK_BASE + 0x{PLAYER_NAME_OFFSET:x} but found "
            "no valid Gen4-encoded name. Has the game finished name entry?"
        )

    # Prefer: highest score (longest name + most secondary canaries), then smallest |delta|.
    best = max(candidates, key=lambda c: (c[1], -abs(c[0])))
    return best[0]


def _read_map_object_0_tile(emu: Any, save_block_delta: int) -> tuple[int, int] | None:
    """Read the player MapObject's live tile position via OBJ_ARRAY_FPX_BASE.

    MapObject[0] is always the player. Its sub-pixel coords (q16.16) update
    every frame regardless of which PLAYER_POS struct is canonical, so we can
    use (tile_x, tile_y) as ground truth when picking the field_ow delta.

    Uses save_block_delta since OBJ_ARRAY_FPX_BASE currently follows the
    save-block group (FieldSystem allocation empirically aligned with save
    block across observed states).

    Returns None if the read fails or yields nonsensical values.
    """
    obj_base = _DESMUME["OBJ_ARRAY_FPX_BASE"] + save_block_delta
    fpx = _read_canary(emu, obj_base, "long")
    fpy = _read_canary(emu, obj_base + 8, "long")
    if fpx is None or fpy is None:
        return None
    tile_x = (fpx >> 16) & 0xFFFF
    tile_y = (fpy >> 16) & 0xFFFF
    if tile_x >= 0x10000 or tile_y >= 0x10000:
        return None
    return (tile_x, tile_y)


def _score_field_ow_delta(emu: Any, delta: int, live_tile: tuple[int, int] | None) -> int:
    """Return a score for a candidate FieldOverworldState delta, or -1 if invalid.

    PlayerData.position struct layout (observed empirically, 20 bytes):
        +0  map_id  (0 for transition, or a valid zone ID 1..600)
        +4  spare   (0, 1, 0xFFFFFFFF, ... — not a reliable canary)
        +8  x       (tile X, world coord — can be thousands on outdoor maps)
        +12 y       (tile Y, world coord)

    `live_tile` is MapObject[0]'s live (tile_x, tile_y). When provided, a
    candidate that matches it gets a massive score boost — this is the strong
    signal that disambiguates between the real struct and 4-byte-off matches.

    x/y bounded at 2^16 — Platinum world coords stay well below 16k tiles
    while random-noise 32-bit values usually have high bits set.
    """
    pos_ref = _DESMUME["PLAYER_POS_BASE"]
    mid = _read_canary(emu, pos_ref + delta)
    if mid is None:
        return -1
    if not (mid == 0 or 1 <= mid <= 600):
        return -1
    x = _read_canary(emu, pos_ref + 8 + delta)
    y = _read_canary(emu, pos_ref + 12 + delta)
    if x is None or y is None:
        return -1
    if not (0 <= x < 0x10000 and 0 <= y < 0x10000):
        return -1

    score = 0
    if mid > 0:
        score += 10
    if x > 0 or y > 0:
        score += 1
    # Big bonus for matching the live MapObject tile position.
    if live_tile is not None and (x, y) == live_tile:
        score += 1000
    return score


def _detect_field_ow_delta(emu: Any, save_block_delta: int) -> int:
    """Find FieldOverworldState (PlayerData) heap shift.

    Uses MapObject[0]'s live tile position (when available) as ground truth
    for matching the PLAYER_POS struct. Fast path: try save_block_delta first
    — usually the two allocations share a delta. Fall back to a full scan
    otherwise, preferring candidates that match the live tile.
    """
    live_tile = _read_map_object_0_tile(emu, save_block_delta)

    sb_score = _score_field_ow_delta(emu, save_block_delta, live_tile)
    # Only take the fast path if the save_block delta matches live_tile
    # (score ≥ 1000) or live_tile is unavailable and map_id is non-zero.
    if sb_score >= 1000 or (live_tile is None and sb_score >= 10):
        return save_block_delta

    candidates: list[tuple[int, int]] = []
    for cand in range(_SCAN_MIN, _SCAN_MAX + 1, _SCAN_STEP):
        s = _score_field_ow_delta(emu, cand, live_tile)
        if s >= 0:
            candidates.append((cand, s))

    if not candidates:
        # No valid PLAYER_POS struct in scan range — fall back to save_block
        # delta. Map tools will report Mystery Zone (as before this fix), but
        # save-block tools (party, bag) will still work.
        return save_block_delta

    # Prefer: highest score (live-tile match dominates), then closest to save_block delta.
    best = max(candidates, key=lambda c: (c[1], -abs(c[0] - save_block_delta)))
    return best[0]


# ── Public API ──

def detect_shift(emu: Any) -> int:
    """Detect heap address shifts for all groups.

    Returns the save-block delta for backward compatibility with callers
    that expect a single int. Field-overworld delta is stored separately
    and retrievable via get_delta("field_ow").
    """
    save_delta = _detect_save_block_delta(emu)
    field_delta = _detect_field_ow_delta(emu, save_delta)

    _deltas["save_block"] = save_delta
    _deltas["field_ow"] = field_delta
    return save_delta


def addr(name: str) -> int:
    """Get a resolved heap address by name.

    Raises RuntimeError if detect_shift() hasn't been called yet.
    """
    if name not in _DESMUME:
        raise KeyError(f"Unknown address name: {name!r}")
    group = _GROUPS.get(name, "save_block")
    delta = _deltas.get(group)
    if delta is None:
        raise RuntimeError(
            "Address resolution not initialized. "
            "The emulator connection should call detect_shift() automatically."
        )
    return _DESMUME[name] + delta


def get_delta(group: str = "save_block") -> int | None:
    """Return the current delta for a heap group.

    Args:
        group: Heap group name. "save_block" (default, back-compat) or "field_ow".
    """
    return _deltas.get(group)


def reset() -> None:
    """Clear all cached deltas. Next addr() call will fail until detect_shift() runs."""
    for k in _deltas:
        _deltas[k] = None
