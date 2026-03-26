#!/usr/bin/env python3
"""Read bag/inventory data directly from emulator memory.

Reads all 7 bag pockets from the save block in RAM. Each pocket is an array of
(item_id u16, quantity u16) pairs at a fixed offset from the bag base address.

Usage:
    python3 scripts/read_bag.py           # print all pockets
    python3 scripts/read_bag.py --json    # output as JSON
    python3 scripts/read_bag.py --pocket items   # show only Items pocket
"""

import sys
import os
import json
import struct

sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect

# --- Constants ---
BAG_BASE = 0x0227E800

# Pocket layout: (name, max_slots)
# Data order: Items, Key Items, TMs & HMs, Mail, Medicine, Berries, Battle Items
POCKETS = [
    ("Items",        165),
    ("Key Items",     50),
    ("TMs & HMs",    100),
    ("Mail",          12),
    ("Medicine",      40),
    ("Berries",       64),
    ("Battle Items",  30),
]

# Total bag size: sum of all slots * 4 bytes each = 1844 bytes
BAG_SIZE = sum(slots for _, slots in POCKETS) * 4

# Load item names
SCRIPT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'data')

ITEM_NAMES = {}
item_file = os.path.join(DATA_DIR, 'item_names.json')
if os.path.exists(item_file):
    with open(item_file) as f:
        ITEM_NAMES = {int(k): v for k, v in json.load(f).items()}


def read_bag(emu):
    """Read all bag pockets from memory.

    Returns a list of dicts, one per pocket:
        {"name": str, "items": [{"id": int, "name": str, "qty": int}, ...]}
    """
    raw = emu.read_memory_range(BAG_BASE, size="byte", count=BAG_SIZE)
    raw_bytes = bytes(raw)

    result = []
    offset = 0
    for pocket_name, max_slots in POCKETS:
        items = []
        for slot in range(max_slots):
            slot_offset = offset + slot * 4
            item_id = struct.unpack_from('<H', raw_bytes, slot_offset)[0]
            qty = struct.unpack_from('<H', raw_bytes, slot_offset + 2)[0]

            if item_id > 0 and qty > 0:
                name = ITEM_NAMES.get(item_id, f"???#{item_id}")
                items.append({"id": item_id, "name": name, "qty": qty})

        result.append({"name": pocket_name, "items": items})
        offset += max_slots * 4

    return result


def format_bag(bag, pocket_filter=None):
    """Format bag data as a readable string."""
    lines = []
    total_items = sum(len(p["items"]) for p in bag)
    lines.append(f"=== Bag ({total_items} item{'s' if total_items != 1 else ''}) ===")

    for pocket in bag:
        if pocket_filter and pocket["name"].lower() != pocket_filter.lower():
            continue

        items = pocket["items"]
        if items:
            lines.append(f"\n  {pocket['name']}:")
            for item in items:
                qty_str = f" x{item['qty']}" if item["qty"] > 1 else ""
                lines.append(f"    {item['name']}{qty_str}")
        elif not pocket_filter:
            pass  # skip empty pockets in full view

    return '\n'.join(lines)


def main():
    output_json = '--json' in sys.argv
    pocket_filter = None

    if '--pocket' in sys.argv:
        idx = sys.argv.index('--pocket')
        if idx + 1 < len(sys.argv):
            pocket_filter = sys.argv[idx + 1]

    emu = connect()
    try:
        bag = read_bag(emu)

        if output_json:
            if pocket_filter:
                bag = [p for p in bag if p["name"].lower() == pocket_filter.lower()]
            print(json.dumps(bag, indent=2))
        else:
            print(format_bag(bag, pocket_filter))
    finally:
        emu.close()


if __name__ == '__main__':
    main()
