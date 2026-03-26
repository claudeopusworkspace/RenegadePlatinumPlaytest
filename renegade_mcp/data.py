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
_map_table: dict[int, dict] | None = None


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
