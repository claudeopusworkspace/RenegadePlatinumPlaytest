"""Lookup table loading for species, moves, items, abilities, and map names.

Tables are loaded lazily on first access and cached for the process lifetime.
Paths are relative to CWD (expected to be the project root).
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path("data")


def _load_int_keyed_json(filename: str) -> dict[int, str]:
    """Load a JSON file mapping string keys to values, converting keys to int."""
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return {int(k): v for k, v in json.load(f).items()}


# Lazy-loaded caches
_species_names: dict[int, str] | None = None
_move_names: dict[int, str] | None = None
_item_names: dict[int, str] | None = None
_ability_names: dict[int, str] | None = None
_item_prices: dict[int, int] | None = None
_map_table: dict[int, dict] | None = None
_tmhm_moves: list[int] | None = None
_tm_compat: dict[int, list[int]] | None = None
_item_field_use: dict[str, int] | None = None
_move_data: dict[int, dict] | None = None


def species_names() -> dict[int, str]:
    global _species_names
    if _species_names is None:
        _species_names = _load_int_keyed_json("species_names.json")
    return _species_names


def move_names() -> dict[int, str]:
    global _move_names
    if _move_names is None:
        _move_names = _load_int_keyed_json("move_names.json")
    return _move_names


def item_names() -> dict[int, str]:
    global _item_names
    if _item_names is None:
        _item_names = _load_int_keyed_json("item_names.json")
    return _item_names


def ability_names() -> dict[int, str]:
    global _ability_names
    if _ability_names is None:
        _ability_names = _load_int_keyed_json("ability_names.json")
    return _ability_names


def item_prices() -> dict[int, int]:
    """Load item ID → buy price table (extracted from pl_item_data.narc)."""
    global _item_prices
    if _item_prices is None:
        _item_prices = _load_int_keyed_json("item_prices.json")
    return _item_prices


def move_data() -> dict[int, dict]:
    """Load move ID → {name, type, power, accuracy, pp, class, priority} table.

    Extracted from ROM's pl_waza_tbl.narc by scripts/extract_move_data.py.
    Returns empty dict if data file hasn't been generated yet.
    """
    global _move_data
    if _move_data is None:
        path = DATA_DIR / "move_data.json"
        if not path.exists():
            _move_data = {}
            return _move_data
        with open(path) as f:
            _move_data = {int(k): v for k, v in json.load(f).items()}
    return _move_data


def move_type(move_id: int) -> str | None:
    """Look up a move's type by ID. Returns None if data unavailable."""
    entry = move_data().get(move_id)
    return entry["type"] if entry else None


def item_field_use() -> dict[str, int]:
    """Load item name → fieldUseFunc mapping (from pl_item_data.csv).

    Only includes items with fieldUseFunc > 0. Key field use func values:
        1 = healing (party target), 6 = TM/HM, 8 = berry,
        14 = honey, 19 = bag message (Repel etc.), 20 = evo stone,
        21 = escape rope.
    """
    global _item_field_use
    if _item_field_use is None:
        path = DATA_DIR / "item_field_use.json"
        if not path.exists():
            return {}
        with open(path) as f:
            _item_field_use = json.load(f)
    return _item_field_use


# ── TM/HM constants ──
ITEM_TM01 = 328  # First TM item ID; tm_index = item_id - ITEM_TM01
ITEM_HM08 = 427  # Last HM item ID


def tmhm_moves() -> list[int]:
    """Load TM/HM index (0-99) → move ID mapping.

    Index 0 = TM01, index 91 = TM92, index 92 = HM01, index 99 = HM08.
    """
    global _tmhm_moves
    if _tmhm_moves is None:
        path = DATA_DIR / "tmhm_moves.json"
        with open(path) as f:
            _tmhm_moves = json.load(f)
    return _tmhm_moves


def tm_compat() -> dict[int, list[int]]:
    """Load species ID → list of learnable TM indices (0-99)."""
    global _tm_compat
    if _tm_compat is None:
        path = DATA_DIR / "tm_compat.json"
        with open(path) as f:
            _tm_compat = {int(k): v for k, v in json.load(f).items()}
    return _tm_compat


def can_learn_tm(species_id: int, tm_index: int) -> bool:
    """Check if a species can learn a TM/HM by index (0-99)."""
    return tm_index in tm_compat().get(species_id, [])


def tm_move_name(tm_index: int) -> str:
    """Get the move name taught by a TM/HM index (0-99)."""
    move_id = tmhm_moves()[tm_index]
    return move_names().get(move_id, f"Move#{move_id}")


def item_id_to_tm_index(item_id: int) -> int | None:
    """Convert a bag item ID to a TM/HM index (0-99), or None if not a TM/HM."""
    if ITEM_TM01 <= item_id <= ITEM_HM08:
        return item_id - ITEM_TM01
    return None


def map_table() -> dict[int, dict]:
    """Load map ID → {name, code, room} table."""
    global _map_table
    if _map_table is not None:
        return _map_table

    path = DATA_DIR / "map_id_to_name.json"
    if not path.exists():
        _map_table = {}
        return _map_table

    with open(path) as f:
        raw = json.load(f)

    _map_table = {int(k): v for k, v in raw.items()}
    return _map_table
