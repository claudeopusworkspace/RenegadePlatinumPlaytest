"""Use a Medicine pocket item on a party Pokemon from the overworld.

Automates the full menu flow: open menu → navigate to Bag → Medicine pocket
→ select item → USE → select party member → dismiss text → close menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.bag import read_bag
from renegade_mcp.bag_cursor import get_pocket_cursor
from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import (
    MENU_SIZE,
    PAUSE_CURSOR_ADDR,
    open_pause_menu,
)

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

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


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
