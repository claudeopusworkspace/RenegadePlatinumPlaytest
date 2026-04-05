"""Use items from the overworld bag menu.

Medicine items: open menu → Bag → Medicine → item → USE → party → dismiss.
Field items (Repel, Escape Rope, etc.): open menu → Bag → Items → item → USE → dismiss.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.bag import read_bag
from renegade_mcp.bag_cursor import get_pocket_cursor
from renegade_mcp.data import item_field_use
from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import (
    MENU_SIZE,
    PAUSE_CURSOR_ADDR,
    open_pause_menu,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
MENU_WAIT = 300       # frames to wait after major menu transitions
NAV_WAIT = 60         # frames to wait after D-pad navigation
DISMISS_WAIT = 120    # frames to wait after B press to dismiss text

# ── Pause menu ──
BAG_INDEX = 2

# ── Bag pocket touch coords (bottom screen) ──
POCKET_COORDS = {
    "Items":        (27, 51),
    "Medicine":     (35, 102),
    "Poke Balls":   (59, 142),
    "TMs & HMs":    (100, 165),
    "Berries":      (156, 165),
    "Mail":         (195, 142),
    "Battle Items": (220, 102),
    "Key Items":    (228, 51),
}

# ── Party screen layout (top screen, D-pad) ──
# Platinum party: 2-column grid. Slot 0 = top-left (default cursor).
# Right = +1 (same row), Down = +2 (next row).
# Slot layout:  0  1
#               2  3
#               4  5
PARTY_NAV = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _tap(emu: EmulatorClient, x: int, y: int, wait: int = NAV_WAIT) -> None:
    """Tap touch screen and wait."""
    emu.tap_touch_screen(x, y, frames=8)
    emu.advance_frames(wait)


def use_item(emu: EmulatorClient, item_name: str, party_slot: int = 0) -> dict[str, Any]:
    """Use a Medicine pocket item on a party Pokemon.

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Potion"). Case-insensitive.
        party_slot: Party index 0-5 (0 = first Pokemon).

    Returns dict with success status, details, and formatted message.
    """
    item_lower = item_name.lower()

    # ── Pre-checks ──

    # Find item in Medicine pocket
    bag = read_bag(emu)
    medicine = None
    for pocket in bag:
        if pocket["name"] == "Medicine":
            medicine = pocket
            break
    if medicine is None:
        return _error("Medicine pocket not found in bag data.")

    item_index = None
    item_entry = None
    for i, item in enumerate(medicine["items"]):
        if item["name"].lower() == item_lower:
            item_index = i
            item_entry = item
            break
    if item_entry is None:
        available = [it["name"] for it in medicine["items"]]
        return _error(f"'{item_name}' not found in Medicine pocket. Available: {available}")

    # Validate party slot
    party = read_party(emu)
    if party_slot < 0 or party_slot >= len(party):
        return _error(f"Party slot {party_slot} invalid. Party has {len(party)} member(s).")

    target_mon = party[party_slot]
    target_name = target_mon.get("name", f"Slot {party_slot}")

    # ── Step 1: Open pause menu (with readiness check) ──
    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to Bag ──
    cursor = emu.read_memory(PAUSE_CURSOR_ADDR, size="byte")
    steps = (BAG_INDEX - cursor) % MENU_SIZE
    for _ in range(steps):
        _press(emu, ["down"])

    # Open Bag
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Tap Medicine pocket tab ──
    mx, my = POCKET_COORDS["Medicine"]
    _tap(emu, mx, my, wait=MENU_WAIT)

    # ── Step 4: Select item ──
    # The game remembers cursor position per pocket. Reset to top first.
    scroll, index = get_pocket_cursor(emu, "Medicine")
    for _ in range(scroll + index):
        _press(emu, ["up"])
    for _ in range(item_index):
        _press(emu, ["down"])

    # Press A to select item → opens USE/GIVE/TRASH/CANCEL submenu
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 5: Press A for "USE" (default selection) ──
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 6: Select party member ──
    # Cursor defaults to slot 0. Navigate to target slot.
    nav = PARTY_NAV.get(party_slot)
    if nav is None:
        # Bail out — close menus
        for _ in range(5):
            _press(emu, ["b"], wait=DISMISS_WAIT)
        return _error(f"Party slot {party_slot} navigation not mapped.")

    for direction in nav:
        _press(emu, [direction])

    # Press A to use item
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 7: Dismiss result text + close menus ──
    # B to dismiss "HP was restored" text → back to bag
    _press(emu, ["b"], wait=DISMISS_WAIT)
    # B to close bag → back to pause menu
    _press(emu, ["b"], wait=MENU_WAIT)
    # B to close pause menu → back to overworld
    _press(emu, ["b"], wait=MENU_WAIT)

    # ── Step 8: Verify ──
    bag_after = read_bag(emu)
    new_qty = None
    for pocket in bag_after:
        if pocket["name"] == "Medicine":
            for item in pocket["items"]:
                if item["name"].lower() == item_lower:
                    new_qty = item["qty"]
                    break
            break

    old_qty = item_entry["qty"]
    qty_decreased = new_qty is not None and new_qty == old_qty - 1
    # Item may have been fully consumed (qty was 1, now gone from list)
    if new_qty is None and old_qty == 1:
        qty_decreased = True
        new_qty = 0

    if qty_decreased:
        msg = f"Used {item_entry['name']} on {target_name}. Quantity: {old_qty} → {new_qty}."
        return {
            "success": True,
            "item": item_entry["name"],
            "target": target_name,
            "old_qty": old_qty,
            "new_qty": new_qty,
            "formatted": msg,
        }
    else:
        msg = (
            f"Item use may have failed. {item_entry['name']} quantity: "
            f"{old_qty} → {new_qty if new_qty is not None else '???'}. "
            "The menu flow may have gone wrong."
        )
        return {
            "success": False,
            "item": item_entry["name"],
            "target": target_name,
            "old_qty": old_qty,
            "new_qty": new_qty,
            "formatted": msg,
        }


# ── Field use func types (from pret/pokeplatinum ItemData.fieldUseFunc) ──
FUNC_NONE = 0
FUNC_HEALING = 1        # Medicine (already handled by use_item)
FUNC_TM_HM = 6          # TM/HM (already handled by teach_tm)
FUNC_HONEY = 14          # Honey — attracts Pokemon
FUNC_BAG_MESSAGE = 19    # Repel, Flutes, etc. — shows message, stays in bag
FUNC_EVO_STONE = 20      # Evolution stone — needs party target
FUNC_ESCAPE_ROPE = 21    # Escape Rope — warps out of cave

# No-target field items: USE activates directly, no party selection needed
NO_TARGET_FUNCS = {FUNC_BAG_MESSAGE, FUNC_ESCAPE_ROPE, FUNC_HONEY}


def use_field_item(emu: EmulatorClient, item_name: str) -> dict[str, Any]:
    """Use a field item (Repel, Escape Rope, Honey, etc.) from the Items pocket.

    Handles items that don't target a party Pokemon — they activate directly
    when USE is selected. For Medicine items, use use_item() instead.

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Repel"). Case-insensitive.

    Returns dict with success status, details, and formatted message.
    """
    item_lower = item_name.lower()

    # ── Pre-check: item exists in Items pocket ──
    bag = read_bag(emu)
    items_pocket = None
    for pocket in bag:
        if pocket["name"] == "Items":
            items_pocket = pocket
            break
    if items_pocket is None:
        return _error("Items pocket not found in bag data.")

    item_index = None
    item_entry = None
    for i, item in enumerate(items_pocket["items"]):
        if item["name"].lower() == item_lower:
            item_index = i
            item_entry = item
            break
    if item_entry is None:
        available = [it["name"] for it in items_pocket["items"]]
        return _error(f"'{item_name}' not found in Items pocket. Available: {available}")

    # ── Pre-check: item is field-usable and no-target ──
    field_use = item_field_use()
    func = field_use.get(item_entry["name"], FUNC_NONE)
    if func == FUNC_NONE:
        return _error(f"'{item_entry['name']}' cannot be used from the field (hold-only item).")
    if func not in NO_TARGET_FUNCS:
        return _error(
            f"'{item_entry['name']}' has fieldUseFunc={func} which requires a target. "
            f"Use use_item() for Medicine or teach_tm() for TMs."
        )

    # ── Step 1: Open pause menu ──
    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to Bag ──
    cursor = emu.read_memory(PAUSE_CURSOR_ADDR, size="byte")
    steps = (BAG_INDEX - cursor) % MENU_SIZE
    for _ in range(steps):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Tap Items pocket tab ──
    ix, iy = POCKET_COORDS["Items"]
    _tap(emu, ix, iy, wait=MENU_WAIT)

    # ── Step 4: Select item ──
    scroll, index = get_pocket_cursor(emu, "Items")
    for _ in range(scroll + index):
        _press(emu, ["up"])
    for _ in range(item_index):
        _press(emu, ["down"])

    # Press A to select → opens USE/GIVE/TOSS/CANCEL submenu
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 5: Press A for "USE" (first option) ──
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 6: Handle post-USE based on func type ──
    if func == FUNC_ESCAPE_ROPE:
        # Escape Rope warps to overworld — menus close automatically.
        # Wait for the warp animation to complete.
        emu.advance_frames(600)
    else:
        # BAG_MESSAGE / HONEY: message appears, still in bag.
        # B to dismiss message → back to bag item list
        _press(emu, ["b"], wait=DISMISS_WAIT)
        # B to close bag → back to pause menu
        _press(emu, ["b"], wait=MENU_WAIT)
        # B to close pause menu → back to overworld
        _press(emu, ["b"], wait=MENU_WAIT)

    # ── Step 7: Verify quantity decreased ──
    bag_after = read_bag(emu)
    new_qty = None
    for pocket in bag_after:
        if pocket["name"] == "Items":
            for item in pocket["items"]:
                if item["name"].lower() == item_lower:
                    new_qty = item["qty"]
                    break
            break

    old_qty = item_entry["qty"]
    qty_decreased = new_qty is not None and new_qty == old_qty - 1
    if new_qty is None and old_qty == 1:
        qty_decreased = True
        new_qty = 0

    if qty_decreased:
        msg = f"Used {item_entry['name']}. Quantity: {old_qty} → {new_qty}."
        return {
            "success": True,
            "item": item_entry["name"],
            "old_qty": old_qty,
            "new_qty": new_qty,
            "formatted": msg,
        }
    else:
        msg = (
            f"Item use may have failed. {item_entry['name']} quantity: "
            f"{old_qty} → {new_qty if new_qty is not None else '???'}. "
            "The menu flow may have gone wrong."
        )
        return {
            "success": False,
            "item": item_entry["name"],
            "old_qty": old_qty,
            "new_qty": new_qty,
            "formatted": msg,
        }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
