"""PokéMart inventory lookup and purchasing.

Mart data is sourced from the ROM (mart_items.h in the decompilation).
Item prices come from pl_item_data.narc (extracted to data/item_prices.json).

Two inventory systems:
  1. Common items — shared across all standard PokéMarts, badge-gated.
  2. Specialty items — unique per city, always available.

Badge-gating uses the same switch logic as the game (scrcmd_shop.c):
  0 badges → threshold 1, 1-2 → 2, 3-4 → 3, 5-6 → 4, 7 → 5, 8 → 6

PokéMart rooms use city code prefix "FS" (Friendly Shop).
All standard marts share identical layouts:
  - Cashier F at (3, 5) — common items
  - Cashier M at (2, 5) — specialty items
  - Exit warp at (3, 11)

If called from a city/town overworld, auto-navigates to the mart.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import item_names, item_prices, map_table

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Common mart items: (item_id, badge_threshold) ──
# Every standard PokéMart sells these, filtered by the player's badge count.
# Data from: ref/pokeplatinum/include/data/mart_items.h PokeMartCommonItems[]
COMMON_MART_ITEMS: list[tuple[int, int]] = [
    (4, 1),    # Poké Ball
    (3, 3),    # Great Ball
    (2, 4),    # Ultra Ball
    (17, 1),   # Potion
    (26, 2),   # Super Potion
    (25, 4),   # Hyper Potion
    (24, 5),   # Max Potion
    (23, 6),   # Full Restore
    (28, 3),   # Revive
    (18, 1),   # Antidote
    (22, 1),   # Parlyz Heal
    (21, 2),   # Awakening
    (19, 2),   # Burn Heal
    (20, 2),   # Ice Heal
    (27, 4),   # Full Heal
    (78, 2),   # Escape Rope
    (79, 2),   # Repel
    (76, 3),   # Super Repel
    (77, 4),   # Max Repel
]

# Badge count → threshold value (from scrcmd_shop.c switch statement)
_BADGE_THRESHOLDS: dict[int, int] = {
    0: 1, 1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 5, 8: 6,
}

# ── Specialty marts: city_code → list of item IDs ──
# Each city's PokéMart has additional unique items alongside the common stock.
# Data from: ref/pokeplatinum/include/data/mart_items.h PokeMartSpecialties[]
SPECIALTY_MARTS: dict[str, list[int]] = {
    "C01": [146, 14],              # Jubilife: Air Mail, Heal Ball
    "C02": [146, 15, 10, 9],      # Canalave: Air Mail, Quick Ball, Timer Ball, Repeat Ball
    "C03": [141, 14, 6],          # Oreburgh: Tunnel Mail, Heal Ball, Net Ball
    "C04": [146, 14, 6, 8],      # Eterna: Air Mail, Heal Ball, Net Ball, Nest Ball
    "C05": [143, 14, 6, 8],      # Hearthome: Heart Mail, Heal Ball, Net Ball, Nest Ball
    "C06": [146, 8, 13, 15],     # Pastoria: Air Mail, Nest Ball, Dusk Ball, Quick Ball
    # C07 (Veilstone) = Dept Store — not a standard mart, skipped
    "C08": [142, 11],            # Sunyshore: Steel Mail, Luxury Ball
    "C09": [144, 13, 15, 10],    # Snowpoint: Snow Mail, Dusk Ball, Quick Ball, Timer Ball
    "C10": [14, 6, 8, 13, 15, 10, 9, 11],  # Pokémon League (all specialty balls)
    "T03": [140, 14, 6],         # Floaroma: Bloom Mail, Heal Ball, Net Ball
    "T04": [146, 6, 8, 13],     # Solaceon: Air Mail, Net Ball, Nest Ball, Dusk Ball
    "T05": [146, 13, 15, 10],   # Celestic: Air Mail, Dusk Ball, Quick Ball, Timer Ball
}


def _badge_threshold(badge_count: int) -> int:
    """Convert badge count to mart item availability threshold."""
    return _BADGE_THRESHOLDS.get(badge_count, 1)


def _city_code_from_map(map_id: int) -> str | None:
    """Extract the city/town code (e.g. 'C01', 'T03') from a map ID."""
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")
    m = re.match(r"^([CT]\d{2})", code)
    return m.group(1) if m else None


def _city_name(city_code: str) -> str:
    """Resolve a city code to its display name by finding the overworld map entry."""
    for entry in map_table().values():
        if entry.get("code") == city_code:
            name = entry.get("name", "")
            if name and not name.startswith("["):
                return name
    return city_code


def _find_mart_warp(
    emu: "EmulatorClient", map_id: int, city_code: str,
) -> dict | None:
    """Find a warp on the current map that leads to this city's PokéMart."""
    from renegade_mcp.map_state import read_warps_from_rom

    warps = read_warps_from_rom(emu, map_id)
    table = map_table()
    for w in warps:
        dest_entry = table.get(w["dest_map"], {})
        dest_code = dest_entry.get("code", "")
        if dest_code.startswith(f"{city_code}FS"):
            return w
    return None


def _format_item(name: str, price: int, tag: str = "") -> str:
    """Format one item line: name, price, optional tag."""
    s = f"  {name:<16s} ¥{price:,}"
    if tag:
        s += f"  ({tag})"
    return s


def read_shop(emu: EmulatorClient, badge_count: int | None = None) -> dict[str, Any]:
    """Read the PokéMart inventory for the player's current location.

    Args:
        emu: Emulator client (used to read current map).
        badge_count: Player's badge count. If None, defaults to 0.

    Returns dict with common_items, specialty_items, formatted text, etc.
    """
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.trainer import read_trainer_status

    map_id, x, y, _facing = read_player_state(emu)
    city_code = _city_code_from_map(map_id)

    if city_code is None:
        entry = map_table().get(map_id, {})
        loc_name = entry.get("name", f"Map {map_id}")
        return {
            "error": f"Not in a city or town with a standard PokéMart.",
            "location": loc_name,
            "map_id": map_id,
        }

    loc_name = _city_name(city_code)

    if badge_count is not None:
        badges = badge_count
    else:
        status = read_trainer_status(emu)
        badges = status.get("badges", 0) if isinstance(status.get("badges"), int) else 0
    threshold = _badge_threshold(badges)

    names = item_names()
    prices = item_prices()

    # ── Common items ──
    common = []
    next_unlock_at: int | None = None
    for item_id, req in COMMON_MART_ITEMS:
        available = threshold >= req
        item = {
            "name": names.get(item_id, f"???#{item_id}"),
            "price": prices.get(item_id, 0),
            "item_id": item_id,
            "available": available,
        }
        if not available:
            item["badges_needed"] = req
            if next_unlock_at is None or req < next_unlock_at:
                next_unlock_at = req
        common.append(item)

    # ── Specialty items ──
    specialty = []
    if city_code in SPECIALTY_MARTS:
        for item_id in SPECIALTY_MARTS[city_code]:
            specialty.append({
                "name": names.get(item_id, f"???#{item_id}"),
                "price": prices.get(item_id, 0),
                "item_id": item_id,
            })

    # ── Formatted output ──
    lines = [f"PokéMart — {loc_name}"]
    if badge_count is not None:
        lines.append(f"Badges: {badges}/8 (threshold {threshold})")
    else:
        lines.append(f"Badges: unknown (showing 0-badge stock, threshold {threshold})")
    lines.append("")

    avail = [i for i in common if i["available"]]
    locked = [i for i in common if not i["available"]]

    if avail:
        lines.append("Common stock:")
        for item in avail:
            lines.append(_format_item(item["name"], item["price"]))

    if specialty:
        lines.append("")
        lines.append(f"Specialty ({loc_name}):")
        for item in specialty:
            lines.append(_format_item(item["name"], item["price"]))

    if locked:
        lines.append("")
        lines.append(f"Locked (next unlock at threshold {next_unlock_at}):")
        for item in locked:
            lines.append(_format_item(
                item["name"], item["price"],
                tag=f"threshold {item['badges_needed']}",
            ))

    has_specialty = city_code in SPECIALTY_MARTS
    if not has_specialty:
        lines.append("")
        lines.append(f"(No specialty items for {loc_name})")

    if city_code == "C07":
        lines.append("")
        lines.append("Note: Veilstone has a Dept Store, not a standard mart.")

    return {
        "location": loc_name,
        "city_code": city_code,
        "map_id": map_id,
        "badges": badges,
        "badges_confirmed": badge_count is not None,
        "threshold": threshold,
        "common_items": common,
        "specialty_items": specialty,
        "formatted": "\n".join(lines),
    }


# ── Buy Item ──

# Timing constants (frames)
_TEXT_WAIT = 120      # dialogue line render
_MENU_WAIT = 300      # shop menu transition (camera pan + list load)
_SETTLE_WAIT = 120    # post-dialogue settle


def _press(emu: EmulatorClient, buttons: list[str], wait: int = _TEXT_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _available_common_items(threshold: int) -> list[int]:
    """Return item IDs for common mart items available at the given badge threshold."""
    return [item_id for item_id, req in COMMON_MART_ITEMS if threshold >= req]


def _find_item_position(
    item_name: str,
    threshold: int,
    city_code: str,
) -> tuple[str, int, int] | None:
    """Find which cashier sells an item and its menu position.

    Returns (cashier_type, menu_index, item_id) or None if not found.
    cashier_type is "common" or "specialty".
    menu_index is the 0-based position in that cashier's item list.
    """
    names = item_names()
    target = item_name.lower()

    # Check common items (badge-filtered, in array order)
    available = _available_common_items(threshold)
    for idx, item_id in enumerate(available):
        if names.get(item_id, "").lower() == target:
            return ("common", idx, item_id)

    # Check specialty items
    specialty_ids = SPECIALTY_MARTS.get(city_code, [])
    for idx, item_id in enumerate(specialty_ids):
        if names.get(item_id, "").lower() == target:
            return ("specialty", idx, item_id)

    return None


def buy_item(
    emu: EmulatorClient,
    item_name: str,
    quantity: int = 1,
    badge_count: int | None = None,
) -> dict[str, Any]:
    """Buy an item from the PokéMart.

    Works from inside a mart or from a city/town overworld (auto-navigates).
    Finds the correct cashier (common vs specialty), navigates to them,
    opens the shop, scrolls to the item, selects quantity, confirms, and exits.

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Potion", "Heal Ball"). Case-insensitive.
        quantity: How many to buy (default 1).
        badge_count: Player's badge count for filtering. If None, defaults to 0.
    """
    from renegade_mcp.map_state import get_map_state, read_player_state
    from renegade_mcp.navigation import interact_with, navigate_to
    from renegade_mcp.phase_timer import phase
    from renegade_mcp.trainer import read_trainer_status

    map_id, _x, _y, _facing = read_player_state(emu)
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")

    navigated_to_mart = False

    if "FS" in code:
        # ── Case 1: Already inside a PokéMart ──
        city_code = _city_code_from_map(map_id)
        if city_code is None:
            return _error(f"Cannot determine city from map code: {code}")

    else:
        # ── Case 2: On a city/town overworld — navigate to mart ──
        city_code = _city_code_from_map(map_id)
        if city_code is not None and code == city_code:
            mart_warp = _find_mart_warp(emu, map_id, city_code)
            if mart_warp is None:
                loc = _city_name(city_code)
                return _error(f"No PokéMart warp found in {loc}.")

            with phase("shop_navigate_to_mart"):
                nav_result = navigate_to(emu, mart_warp["x"], mart_warp["y"], flee_encounters=True)

            if nav_result.get("encounter"):
                return {
                    "success": False,
                    "error": "Navigation to PokéMart interrupted by encounter.",
                    "encounter": nav_result["encounter"],
                    "formatted": (
                        "Error: Navigation to PokéMart interrupted by encounter. "
                        "Deal with the encounter and try again."
                    ),
                }

            if nav_result.get("stopped_early") and not nav_result.get("door_entered"):
                return _error(
                    "Could not reach the PokéMart — path was blocked. "
                    f"Path: {nav_result.get('path', 'unknown')}"
                )

            navigated_to_mart = True
            # Re-read position now that we're inside
            map_id, _x, _y, _facing = read_player_state(emu)
            entry = map_table().get(map_id, {})
            code = entry.get("code", "")

            if "FS" not in code:
                return _error(
                    f"Navigated to mart warp but didn't enter "
                    f"(current code: {code})."
                )
        else:
            # ── Case 3: Not in a mart or city overworld ──
            loc = _city_name(city_code) if city_code else entry.get("name", f"Map {map_id}")
            return _error(
                f"Not inside a PokéMart or city overworld ({loc}, code: {code}). "
                "Navigate to a town with a PokéMart first."
            )

    # ── Resolve badge threshold ──
    if badge_count is not None:
        badges = badge_count
    else:
        status = read_trainer_status(emu)
        badges = status.get("badges", 0) if isinstance(status.get("badges"), int) else 0
    threshold = _badge_threshold(badges)

    # ── Find item in shop inventory ──
    result = _find_item_position(item_name, threshold, city_code)
    if result is None:
        # Build helpful error with available items
        names = item_names()
        avail_common = [names.get(i, "?") for i in _available_common_items(threshold)]
        avail_spec = [names.get(i, "?") for i in SPECIALTY_MARTS.get(city_code, [])]
        return _error(
            f"Item \"{item_name}\" not found in shop. "
            f"Common: {', '.join(avail_common)}. "
            f"Specialty: {', '.join(avail_spec) if avail_spec else '(none)'}."
        )

    cashier_type, menu_index, item_id = result
    prices = item_prices()
    price = prices.get(item_id, 0)
    total_cost = price * quantity
    display_name = item_names().get(item_id, item_name)

    # ── Check money ──
    status = read_trainer_status(emu)
    money = status.get("money", 0)
    if total_cost > money:
        return _error(
            f"Not enough money. {display_name} x{quantity} costs ¥{total_cost:,} "
            f"but you only have ¥{money:,}."
        )

    # ── Find the correct cashier NPC ──
    state = get_map_state(emu)
    if state is None:
        return _error("Could not read map state.")

    cashier_name = "Cashier F" if cashier_type == "common" else "Cashier M"
    cashier = next(
        (obj for obj in state["objects"] if obj.get("name") == cashier_name),
        None,
    )
    if cashier is None:
        npc_names = [obj.get("name", "?") for obj in state["objects"] if obj["index"] != 0]
        return _error(f"No {cashier_name} found. NPCs: {', '.join(npc_names)}")

    # ── Walk to cashier and interact ──
    with phase("shop_interact_cashier"):
        nav_result = interact_with(emu, cashier["index"])

    if nav_result.get("interrupted") or nav_result.get("encounter"):
        return _error(f"Navigation to {cashier_name} interrupted: {nav_result}")
    if nav_result.get("stopped_early"):
        return _error(f"Could not reach {cashier_name} — path blocked.")

    # interact_with auto-advances "Welcome! What do you need?" dialogue.
    # We're now at the BUY/SELL/SEE YA menu with cursor on BUY.
    with phase("shop_purchase_flow"):
        _press(emu, ["a"], _MENU_WAIT)   # select BUY → item list loads

        # ── Navigate item list to target item ──
        for _ in range(menu_index):
            _press(emu, ["down"], wait=30)

        # ── Select item ──
        _press(emu, ["a"])               # "Certainly. How many would you like?"
        _press(emu, ["a"])               # text finishes → quantity selector (x01)

        # ── Set quantity (up arrow to increase from 1) ──
        for _ in range(quantity - 1):
            _press(emu, ["up"], wait=15)

        # ── Confirm quantity → YES/NO → purchase ──
        _press(emu, ["a"])               # confirm qty → "That will be ¥X..." text
        _press(emu, ["a"])               # text finishes → YES/NO prompt
        _press(emu, ["a"])               # select YES → "Here you are! Thank you!"

        # ── Post-purchase dialogue ──
        _press(emu, ["a"])               # advance "Here you are!"
        _press(emu, ["a"])               # "You put away the [item] in the [pocket]."
        _press(emu, ["a"], _MENU_WAIT)   # dismiss → back to item list

        # ── Exit shop: B → See Ya ──
        _press(emu, ["b"], _MENU_WAIT)   # back to Buy/Sell/See Ya
        _press(emu, ["down"], wait=30)   # → SELL
        _press(emu, ["down"], wait=30)   # → SEE YA!
        _press(emu, ["a"])               # "Please come again!"
        _press(emu, ["a"], _SETTLE_WAIT) # dismiss farewell, back to overworld

    # ── Verify purchase ──
    new_status = read_trainer_status(emu)
    new_money = new_status.get("money", 0)
    spent = money - new_money

    result = {
        "success": True,
        "item": display_name,
        "item_id": item_id,
        "quantity": quantity,
        "unit_price": price,
        "total_cost": total_cost,
        "money_before": money,
        "money_after": new_money,
        "money_spent": spent,
        "cashier": cashier_type,
        "formatted": (
            f"Bought {display_name} x{quantity} for ¥{total_cost:,}. "
            f"Money: ¥{money:,} → ¥{new_money:,}"
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


# ── Sell Item ──

# Pockets that cannot be sold (game rejects them)
_UNSELLABLE_POCKETS = {"Key Items", "TMs & HMs", "Mail"}

# Pocket touch-tab coords (bottom screen) — same layout as regular bag.
# Only sellable pockets listed.
_SELL_POCKET_COORDS: dict[str, tuple[int, int]] = {
    "Items":        (27, 51),
    "Medicine":     (35, 102),
    "Poke Balls":   (59, 142),
    "Berries":      (156, 165),
    "Battle Items": (220, 102),
}


def sell_item(
    emu: EmulatorClient,
    item_name: str,
    quantity: int = 1,
) -> dict[str, Any]:
    """Sell an item at the PokéMart.

    Works from inside a mart or from a city/town overworld (auto-navigates).
    Talks to Cashier F, selects SELL, navigates the sell bag to the item,
    sets quantity, confirms the sale, and exits.

    Sell price = buy price / 2 (standard Pokémon formula).

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Potion", "Repel"). Case-insensitive.
        quantity: How many to sell (default 1).
    """
    from renegade_mcp.bag import read_bag
    from renegade_mcp.bag_cursor import get_pocket_cursor
    from renegade_mcp.map_state import get_map_state, read_player_state
    from renegade_mcp.navigation import interact_with, navigate_to
    from renegade_mcp.trainer import read_trainer_status

    item_lower = item_name.lower()

    # ── Find item in bag ──
    bag = read_bag(emu)
    found_pocket = None
    found_index = None
    found_entry = None
    for pocket in bag:
        if pocket["name"] in _UNSELLABLE_POCKETS:
            continue
        for i, item in enumerate(pocket["items"]):
            if item["name"].lower() == item_lower:
                found_pocket = pocket["name"]
                found_index = i
                found_entry = item
                break
        if found_entry is not None:
            break

    if found_entry is None:
        # Check if item is in an unsellable pocket
        for pocket in bag:
            if pocket["name"] in _UNSELLABLE_POCKETS:
                for item in pocket["items"]:
                    if item["name"].lower() == item_lower:
                        return _error(
                            f"'{item['name']}' is in {pocket['name']} pocket "
                            f"and cannot be sold."
                        )
        sellable = []
        for pocket in bag:
            if pocket["name"] not in _UNSELLABLE_POCKETS:
                sellable.extend(it["name"] for it in pocket["items"])
        return _error(
            f"'{item_name}' not found in bag. "
            f"Sellable items: {', '.join(sellable) if sellable else '(none)'}."
        )

    # ── Check quantity ──
    if quantity < 1:
        return _error("Quantity must be at least 1.")
    if quantity > found_entry["qty"]:
        return _error(
            f"Not enough {found_entry['name']}. "
            f"Have {found_entry['qty']}, want to sell {quantity}."
        )

    # ── Calculate sell price ──
    prices = item_prices()
    names = item_names()
    display_name = found_entry["name"]
    # Reverse-lookup item ID from name
    item_id = found_entry.get("id")
    if item_id is None:
        for iid, iname in names.items():
            if iname.lower() == item_lower:
                item_id = iid
                break
    buy_price = prices.get(item_id, 0) if item_id else 0
    sell_price = buy_price // 2
    if sell_price == 0:
        return _error(f"'{display_name}' has no sell value (buy price: ¥0).")
    total_value = sell_price * quantity

    # ── Navigate to mart ──
    map_id, _x, _y, _facing = read_player_state(emu)
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")

    navigated_to_mart = False

    if "FS" in code:
        city_code = _city_code_from_map(map_id)
        if city_code is None:
            return _error(f"Cannot determine city from map code: {code}")
    else:
        city_code = _city_code_from_map(map_id)
        if city_code is not None and code == city_code:
            mart_warp = _find_mart_warp(emu, map_id, city_code)
            if mart_warp is None:
                loc = _city_name(city_code)
                return _error(f"No PokéMart warp found in {loc}.")

            nav_result = navigate_to(emu, mart_warp["x"], mart_warp["y"],
                                     flee_encounters=True)

            if nav_result.get("encounter"):
                return {
                    "success": False,
                    "error": "Navigation to PokéMart interrupted by encounter.",
                    "encounter": nav_result["encounter"],
                    "formatted": (
                        "Error: Navigation to PokéMart interrupted by encounter. "
                        "Deal with the encounter and try again."
                    ),
                }

            if nav_result.get("stopped_early") and not nav_result.get("door_entered"):
                return _error(
                    "Could not reach the PokéMart — path was blocked. "
                    f"Path: {nav_result.get('path', 'unknown')}"
                )

            navigated_to_mart = True
            map_id, _x, _y, _facing = read_player_state(emu)
            entry = map_table().get(map_id, {})
            code = entry.get("code", "")

            if "FS" not in code:
                return _error(
                    f"Navigated to mart warp but didn't enter "
                    f"(current code: {code})."
                )
        else:
            loc = (_city_name(city_code) if city_code
                   else entry.get("name", f"Map {map_id}"))
            return _error(
                f"Not inside a PokéMart or city overworld ({loc}, code: {code}). "
                "Navigate to a town with a PokéMart first."
            )

    # ── Record money before ──
    status = read_trainer_status(emu)
    money_before = status.get("money", 0)

    # ── Find Cashier F and interact ──
    state = get_map_state(emu)
    if state is None:
        return _error("Could not read map state.")

    cashier = next(
        (obj for obj in state["objects"] if obj.get("name") == "Cashier F"),
        None,
    )
    if cashier is None:
        npc_names = [obj.get("name", "?") for obj in state["objects"]
                     if obj["index"] != 0]
        return _error(f"No Cashier F found. NPCs: {', '.join(npc_names)}")

    nav_result = interact_with(emu, cashier["index"])

    if nav_result.get("interrupted") or nav_result.get("encounter"):
        return _error(f"Navigation to Cashier F interrupted: {nav_result}")
    if nav_result.get("stopped_early"):
        return _error("Could not reach Cashier F — path blocked.")

    # interact_with auto-advances "Welcome! What do you need?" dialogue.
    # We're now at the BUY/SELL/SEE YA menu with cursor on BUY.

    # ── Select SELL (one down from BUY) ──
    _press(emu, ["down"], wait=30)    # BUY → SELL
    _press(emu, ["a"], _MENU_WAIT)    # open sell bag

    # ── Navigate to correct pocket via touch tab ──
    pocket_coords = _SELL_POCKET_COORDS.get(found_pocket)
    if pocket_coords is None:
        # Shouldn't happen — we filtered unsellable pockets above
        _press(emu, ["b"], _MENU_WAIT)   # exit sell bag
        _press(emu, ["down"], wait=30)    # → SEE YA
        _press(emu, ["a"])                # select SEE YA
        _press(emu, ["a"], _SETTLE_WAIT)  # dismiss farewell
        return _error(f"Pocket '{found_pocket}' has no sell tab coordinates.")

    px, py = pocket_coords
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(_MENU_WAIT)

    # ── Scroll to item ──
    # Reset cursor to top first (sell bag may have its own cursor state)
    scroll, index = get_pocket_cursor(emu, found_pocket)
    for _ in range(scroll + index):
        _press(emu, ["up"], wait=30)
    for _ in range(found_index):
        _press(emu, ["down"], wait=30)

    # ── Select item ──
    _press(emu, ["a"])                # "How many would you like to sell?"
    _press(emu, ["a"])                # text finishes → quantity selector (x01)

    # ── Set quantity (up to increase from 1) ──
    for _ in range(quantity - 1):
        _press(emu, ["up"], wait=15)

    # ── Confirm sale ──
    # Confirm qty goes straight to YES/NO (no intermediate text screen).
    _press(emu, ["a"])                # confirm qty → "I can pay ¥X. Would that be OK?" + YES/NO
    _press(emu, ["a"])                # select YES → "Turned over [item] and received ¥X."

    # ── Post-sale dialogue ──
    _press(emu, ["a"])                # advance scrolling "Turned over..." text
    _press(emu, ["a"], _MENU_WAIT)    # dismiss finished text → back to sell bag

    # ── Exit sell bag + shop ──
    # After B, cursor returns to BUY (first option), not SELL.
    _press(emu, ["b"], _MENU_WAIT)    # exit sell bag → BUY/SELL/SEE YA (cursor on BUY)
    _press(emu, ["down"], wait=30)    # BUY → SELL
    _press(emu, ["down"], wait=30)    # SELL → SEE YA!
    _press(emu, ["a"])                # "Please come again!"
    _press(emu, ["a"], _SETTLE_WAIT)  # dismiss farewell, back to overworld

    # ── Verify sale ──
    new_status = read_trainer_status(emu)
    new_money = new_status.get("money", 0)
    earned = new_money - money_before

    result = {
        "success": True,
        "item": display_name,
        "item_id": item_id,
        "quantity": quantity,
        "unit_sell_price": sell_price,
        "total_value": total_value,
        "money_before": money_before,
        "money_after": new_money,
        "money_earned": earned,
        "formatted": (
            f"Sold {display_name} x{quantity} for ¥{total_value:,}. "
            f"Money: ¥{money_before:,} → ¥{new_money:,}"
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result
