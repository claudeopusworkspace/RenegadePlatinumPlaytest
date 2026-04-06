"""Take a held item from a party Pokemon in the overworld.

Opens pause menu → Pokemon → select slot → Item → Take → dismiss text → close.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import (
    open_pause_menu,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
MENU_WAIT = 300       # frames after major menu transitions
NAV_WAIT = 60         # frames after D-pad navigation

# ── Pause menu ──
POKEMON_INDEX = 1     # 0=Pokedex, 1=Pokemon, 2=Bag, ...
MENU_SIZE = 7

# ── Party screen (top screen, D-pad, 2-column grid) ──
# Layout:  0  1
#          2  3
#          4  5
PARTY_NAV_ABS = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}

# ── Submenu positions (from SUMMARY) ──
# SUMMARY(0) → SWITCH(1) → ITEM(2) → CANCEL(3)
ITEM_OPTION_OFFSET = 2

# ── Item submenu positions (from GIVE) ──
# GIVE(0) → TAKE(1) → CANCEL(2)
TAKE_OPTION_OFFSET = 1


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def take_item(emu: EmulatorClient, party_slot: int = 0) -> dict[str, Any]:
    """Take the held item from a party Pokemon.

    Args:
        emu: Emulator client.
        party_slot: Party index 0-5 (0 = first Pokemon).

    Returns dict with success status and item taken.
    """
    if not (0 <= party_slot <= 5):
        return _error(f"Party slot must be 0-5, got {party_slot}.")

    # Pre-check: read party to verify slot exists and has an item
    party = read_party(emu)
    if party_slot >= len(party):
        return _error(f"Party slot {party_slot} invalid. Party has {len(party)} member(s).")

    target = party[party_slot]
    target_name = target.get("name", f"Slot {party_slot}")
    item_id = target.get("item_id", 0)

    if item_id == 0:
        return _error(f"{target_name} is not holding an item.")

    # ── Step 1: Open pause menu (with readiness check) ──
    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to POKEMON ──
    from renegade_mcp.addresses import addr
    cursor = emu.read_memory(addr("PAUSE_CURSOR_ADDR"), size="byte")
    diff = (POKEMON_INDEX - cursor) % MENU_SIZE
    for _ in range(diff):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Select the target Pokemon ──
    nav = PARTY_NAV_ABS.get(party_slot)
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

    # ── Step 5: Select TAKE from item submenu ──
    # Item submenu: GIVE(0), TAKE(1), CANCEL(2)
    for _ in range(TAKE_OPTION_OFFSET):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 6: Dismiss "Received the X from Y" text ──
    _press(emu, ["b"], wait=MENU_WAIT)

    # ── Step 7: Close party screen → close pause menu ──
    _press(emu, ["b"], wait=MENU_WAIT)
    _press(emu, ["b"], wait=MENU_WAIT)

    # ── Step 8: Verify ──
    party_after = read_party(emu)
    if party_slot < len(party_after):
        new_item_id = party_after[party_slot].get("item_id", 0)
    else:
        new_item_id = -1  # Can't verify

    if new_item_id == 0:
        # Get item name from data module
        from renegade_mcp.data import item_names
        item_name = item_names().get(item_id, f"item #{item_id}")
        msg = f"Took {item_name} from {target_name}."
        return {
            "success": True,
            "item_id": item_id,
            "item": item_name,
            "target": target_name,
            "party_slot": party_slot,
            "formatted": msg,
        }
    else:
        msg = (
            f"Take may have failed. {target_name} item_id: "
            f"{item_id} → {new_item_id}. Menu flow may have gone wrong."
        )
        return {"success": False, "formatted": msg}


def _bail(emu: EmulatorClient) -> None:
    """Press B repeatedly to close any open menus."""
    for _ in range(5):
        _press(emu, ["b"], wait=MENU_WAIT)


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
