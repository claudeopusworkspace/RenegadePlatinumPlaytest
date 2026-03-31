"""Give a held item to a party Pokemon in the overworld.

Opens pause menu → Pokemon → select slot → Item → Give → bag opens →
navigate to pocket → select item → dismiss text → close.

Uses the Pokemon menu path (not the Bag path) because GIVE is always
at position 0 in the ITEM submenu, regardless of item type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.bag import read_bag
from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import (
    MENU_SIZE,
    PAUSE_CURSOR_ADDR,
    open_pause_menu,
)

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Timing ──
MENU_WAIT = 300       # frames after major menu transitions
NAV_WAIT = 60         # frames after D-pad navigation
DISMISS_WAIT = 120    # frames after B press to dismiss text

# ── Pause menu ──
POKEMON_INDEX = 1     # 0=Pokedex, 1=Pokemon, 2=Bag, ...

# ── Party screen (top screen, D-pad, 2-column grid) ──
# Layout:  0  1
#          2  3
#          4  5
PARTY_NAV = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}

# ── Submenu positions ──
# SUMMARY(0) → SWITCH(1) → ITEM(2) → CANCEL(3)
ITEM_OPTION_OFFSET = 2

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


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _tap(emu: EmulatorClient, x: int, y: int, wait: int = NAV_WAIT) -> None:
    """Tap touch screen and wait."""
    emu.tap_touch_screen(x, y, frames=8)
    emu.advance_frames(wait)


def give_item(emu: EmulatorClient, item_name: str, party_slot: int = 0) -> dict[str, Any]:
    """Give a held item to a party Pokemon.

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Scope Lens"). Case-insensitive.
        party_slot: Party index 0-5 (0 = first Pokemon).

    Returns dict with success status, details, and formatted message.
    """
    item_lower = item_name.lower()

    # ── Pre-checks ──

    # Find item in bag (search all pockets except Key Items)
    bag = read_bag(emu)
    target_pocket = None
    item_index = None
    item_entry = None

    for pocket in bag:
        if pocket["name"] == "Key Items":
            continue
        for i, item in enumerate(pocket["items"]):
            if item["name"].lower() == item_lower:
                target_pocket = pocket
                item_index = i
                item_entry = item
                break
        if item_entry is not None:
            break

    if item_entry is None:
        # Check if it's a Key Item
        for pocket in bag:
            if pocket["name"] == "Key Items":
                for item in pocket["items"]:
                    if item["name"].lower() == item_lower:
                        return _error(
                            f"'{item['name']}' is a Key Item and cannot be given as a held item."
                        )
        all_items = [it["name"] for p in bag for it in p["items"]]
        return _error(f"'{item_name}' not found in bag. Available items: {all_items}")

    pocket_name = target_pocket["name"]

    # Validate party slot
    party = read_party(emu)
    if party_slot < 0 or party_slot >= len(party):
        return _error(f"Party slot {party_slot} invalid. Party has {len(party)} member(s).")

    target_mon = party[party_slot]
    target_name = target_mon.get("name", f"Slot {party_slot}")
    existing_item = target_mon.get("item_id", 0)

    if existing_item != 0:
        from renegade_mcp.data import item_names
        existing_name = item_names().get(existing_item, f"item #{existing_item}")
        return _error(
            f"{target_name} is already holding {existing_name}. "
            "Use take_item first to remove it."
        )

    # Check scrolling limitation
    if item_index > 4:
        return _error(
            f"'{item_entry['name']}' is at position {item_index} in {pocket_name} — "
            "scrolling not yet implemented. Only the first 5 items are selectable."
        )

    # ── Step 1: Open pause menu ──
    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to POKEMON ──
    cursor = emu.read_memory(PAUSE_CURSOR_ADDR, size="byte")
    diff = (POKEMON_INDEX - cursor) % MENU_SIZE
    for _ in range(diff):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Select target Pokemon ──
    nav = PARTY_NAV.get(party_slot)
    if nav is None:
        _bail(emu)
        return _error(f"Party slot {party_slot} navigation not mapped.")
    for direction in nav:
        _press(emu, [direction])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 4: Select ITEM from submenu ──
    # Submenu: SUMMARY(0), SWITCH(1), ITEM(2), CANCEL(3)
    for _ in range(ITEM_OPTION_OFFSET):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 5: Select GIVE from item submenu ──
    # Item submenu (no held item): GIVE(0), CANCEL(1)
    # GIVE is always position 0 — just press A.
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 6: Bag opens — navigate to correct pocket ──
    coords = POCKET_COORDS.get(pocket_name)
    if coords:
        _tap(emu, coords[0], coords[1], wait=MENU_WAIT)

    # ── Step 7: Navigate to item and select it ──
    for _ in range(item_index):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 8: Dismiss "was given the X to hold" text ──
    _press(emu, ["b"], wait=DISMISS_WAIT)

    # ── Step 9: Close menus ──
    # After giving, game returns to party screen.
    _press(emu, ["b"], wait=MENU_WAIT)   # close party screen
    _press(emu, ["b"], wait=MENU_WAIT)   # close pause menu
    _press(emu, ["b"], wait=MENU_WAIT)   # safety — extra B in overworld is harmless

    # ── Step 10: Verify ──
    party_after = read_party(emu)
    if party_slot < len(party_after):
        new_item_id = party_after[party_slot].get("item_id", 0)
    else:
        new_item_id = -1

    if new_item_id == item_entry["id"]:
        msg = f"Gave {item_entry['name']} to {target_name}."
        return {
            "success": True,
            "item_id": item_entry["id"],
            "item": item_entry["name"],
            "target": target_name,
            "party_slot": party_slot,
            "formatted": msg,
        }
    else:
        from renegade_mcp.data import item_names as _item_names
        actual_name = (
            _item_names().get(new_item_id, f"item #{new_item_id}")
            if new_item_id > 0
            else "nothing"
        )
        msg = (
            f"Give may have failed. {target_name} is now holding {actual_name} "
            f"(expected {item_entry['name']}). Menu flow may have gone wrong."
        )
        return {"success": False, "formatted": msg}


def _bail(emu: EmulatorClient) -> None:
    """Press B repeatedly to close any open menus."""
    for _ in range(5):
        _press(emu, ["b"], wait=MENU_WAIT)


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
