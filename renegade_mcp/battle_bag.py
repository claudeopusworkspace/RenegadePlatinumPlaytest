"""Battle bag pocket logic — reconstruct in-battle item lists from overworld bag.

The battle bag has 4 pockets (HP/PP Recovery, Status Recovery, Poke Balls, Battle Items)
populated by filtering overworld bag items through their ROM battlePocket bitmask.
Items appear in overworld bag scan order (Items → Key Items → TMs → Mail → Medicine →
Berries → Poke Balls → Battle Items), matching the game's BattleBag_Init.

Touch coordinates derived from ref/pokeplatinum/src/battle_sub_menus/battle_bag.c
TouchScreenRect tables.  Decomp format: {y_top, y_bottom, x_left, x_right}.
"""

from __future__ import annotations

from typing import Any

# ── Battle pocket bitmask → pocket index ──
# From ref/pokeplatinum/src/battle_sub_menus/battle_bag_utils.c sBattlePocketIndexes[]
# Bit 0 (1)  → Poke Balls   (index 2)
# Bit 1 (2)  → Battle Items (index 3)
# Bit 2 (4)  → Recover HP   (index 0)
# Bit 3 (8)  → Recover Stat (index 1)
# Bit 4 (16) → Recover PP   (index 0, same bucket as HP)
_BIT_TO_POCKET = {
    0: 2,  # Poke Balls
    1: 3,  # Battle Items
    2: 0,  # Recover HP/PP
    3: 1,  # Recover Status
    4: 0,  # Recover PP (maps to same bucket as HP)
}

ITEMS_PER_PAGE = 6

POCKET_NAMES = {
    0: "HP/PP Recovery",
    1: "Status Recovery",
    2: "Poke Balls",
    3: "Battle Items",
}


def build_battle_pockets(bag_data: list[dict[str, Any]]) -> dict[int, list[dict]]:
    """Reconstruct battle bag pockets from overworld bag data.

    Args:
        bag_data: Output of read_bag() — list of pocket dicts with 'items' lists.

    Returns:
        {pocket_index: [item_dicts]} where each item has:
            id, name, qty, index (0-based position in pocket),
            page (page number), slot (0-5 position on page).
    """
    from renegade_mcp.data import item_battle_data

    battle_data = item_battle_data()
    pockets: dict[int, list[dict]] = {0: [], 1: [], 2: [], 3: []}

    # Scan all overworld pockets in order (matching game's BattleBag_Init)
    for pocket in bag_data:
        for item in pocket["items"]:
            item_id = item["id"]
            bd = battle_data.get(item_id)
            if bd is None:
                continue

            mask = bd["battlePocket"]
            # An item can appear in multiple battle pockets (e.g. Full Restore)
            for bit, pocket_idx in _BIT_TO_POCKET.items():
                if mask & (1 << bit):
                    idx = len(pockets[pocket_idx])
                    pockets[pocket_idx].append({
                        "id": item_id,
                        "name": item["name"],
                        "qty": item["qty"],
                        "index": idx,
                        "page": idx // ITEMS_PER_PAGE,
                        "slot": idx % ITEMS_PER_PAGE,
                        "battleUseFunc": bd["battleUseFunc"],
                    })

    return pockets


def find_item_in_battle_bag(
    bag_data: list[dict[str, Any]], item_name: str,
) -> dict[str, Any]:
    """Find a specific item's position in the battle bag.

    Args:
        bag_data: Output of read_bag().
        item_name: Item name (case-insensitive).

    Returns dict with:
        pocket_index, pocket_name, page, slot, index, battleUseFunc, qty
    Or dict with 'error' key if not found.
    """
    pockets = build_battle_pockets(bag_data)
    item_lower = item_name.lower()

    for pocket_idx, items in pockets.items():
        for item in items:
            if item["name"].lower() == item_lower:
                return {
                    "pocket_index": pocket_idx,
                    "pocket_name": POCKET_NAMES[pocket_idx],
                    "page": item["page"],
                    "slot": item["slot"],
                    "index": item["index"],
                    "battleUseFunc": item["battleUseFunc"],
                    "qty": item["qty"],
                }

    # Not found — list what IS available
    all_items = []
    for pocket_idx, items in pockets.items():
        for item in items:
            all_items.append(f"{item['name']} ({POCKET_NAMES[pocket_idx]})")

    return {
        "error": f"'{item_name}' not found in battle bag. "
                 f"Available: {', '.join(all_items) if all_items else 'none'}",
    }
