"""Read bag/inventory data from emulator memory.

Reads 7 bag pockets from the save block at 0x0227E800.
Each pocket is an array of (item_id u16, quantity u16) pairs.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import item_names

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Memory layout ──

# Pocket definitions: (name, max_slots)
POCKETS = [
    ("Items", 165),
    ("Key Items", 50),
    ("TMs & HMs", 100),
    ("Mail", 12),
    ("Medicine", 40),
    ("Berries", 64),
    ("Battle Items", 30),
]

BAG_SIZE = sum(slots for _, slots in POCKETS) * 4  # 1844 bytes


def read_bag(emu: EmulatorClient) -> list[dict[str, Any]]:
    """Read all bag pockets from memory. Returns list of pocket dicts."""
    it_names = item_names()
    from renegade_mcp.addresses import addr
    raw = emu.read_memory_range(addr("BAG_BASE"), size="byte", count=BAG_SIZE)
    raw_bytes = bytes(raw)

    result = []
    offset = 0
    for pocket_name, max_slots in POCKETS:
        items = []
        for slot in range(max_slots):
            slot_offset = offset + slot * 4
            item_id = struct.unpack_from("<H", raw_bytes, slot_offset)[0]
            qty = struct.unpack_from("<H", raw_bytes, slot_offset + 2)[0]

            if item_id > 0 and qty > 0:
                name = it_names.get(item_id, f"???#{item_id}")
                items.append({"id": item_id, "name": name, "qty": qty})

        result.append({"name": pocket_name, "items": items})
        offset += max_slots * 4

    return result


def format_bag(bag: list[dict[str, Any]], pocket_filter: str = "") -> str:
    """Format bag data as a readable string."""
    total_items = sum(len(p["items"]) for p in bag)
    lines = [f"=== Bag ({total_items} item{'s' if total_items != 1 else ''}) ==="]

    for pocket in bag:
        if pocket_filter and pocket["name"].lower() != pocket_filter.lower():
            continue

        items = pocket["items"]
        if items:
            lines.append(f"\n  {pocket['name']}:")
            for item in items:
                qty_str = f" x{item['qty']}" if item["qty"] > 1 else ""
                lines.append(f"    {item['name']}{qty_str}")

    return "\n".join(lines)
