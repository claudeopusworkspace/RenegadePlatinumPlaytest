#!/usr/bin/env python3
"""Extract battle item data (battleUseFunc, battlePocket) from pl_item_data.csv.

Writes data/item_battle_data.json mapping item_id → {battleUseFunc, battlePocket}.
Only includes items with a non-zero battlePocket (i.e., usable in battle).

Usage:
    python scripts/extract_battle_data.py

Requires:
    - ref/pokeplatinum/res/items/pl_item_data.csv
    - data/item_names.json (for item ID resolution)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

CSV_PATH = Path("ref/pokeplatinum/res/items/pl_item_data.csv")
ITEM_NAMES_PATH = Path("data/item_names.json")
OUTPUT_PATH = Path("data/item_battle_data.json")

# Battle pocket mask name → integer bitmask
# From ref/pokeplatinum/include/constants/items.h
BATTLE_POCKET_MASKS = {
    "BATTLE_POCKET_MASK_NONE": 0,
    "BATTLE_POCKET_MASK_POKE_BALLS": 1,       # bit 0
    "BATTLE_POCKET_MASK_BATTLE_ITEMS": 2,      # bit 1
    "BATTLE_POCKET_MASK_RECOVER_HP": 4,        # bit 2
    "BATTLE_POCKET_MASK_RECOVER_STATUS": 8,    # bit 3
    "BATTLE_POCKET_MASK_RECOVER_PP": 16,       # bit 4
    "BATTLE_POCKET_MASK_RECOVER_HP_STATUS": 12, # bits 2+3
}

# Item constant name → numeric ID
# The CSV rows are ordered by item ID (row 1 = ITEM_NONE = 0, row 2 = ITEM_MASTER_BALL = 1, etc.)


def main():
    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} not found")
        return

    result = {}

    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        for item_id, row in enumerate(reader):
            # item_id starts at 0 (ITEM_NONE), first data row is id=0
            pocket_name = row["battlePocket"]
            battle_use_func = int(row["battleUseFunc"])

            pocket_mask = BATTLE_POCKET_MASKS.get(pocket_name, 0)
            if pocket_mask == 0:
                continue

            result[str(item_id)] = {
                "battleUseFunc": battle_use_func,
                "battlePocket": pocket_mask,
            }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)

    print(f"Wrote {len(result)} items to {OUTPUT_PATH}")

    # Summary
    func_counts = {}
    pocket_counts = {}
    for data in result.values():
        func = data["battleUseFunc"]
        func_counts[func] = func_counts.get(func, 0) + 1
        mask = data["battlePocket"]
        pocket_counts[mask] = pocket_counts.get(mask, 0) + 1

    print(f"  battleUseFunc distribution: {func_counts}")
    print(f"  battlePocket distribution: {pocket_counts}")


if __name__ == "__main__":
    main()
