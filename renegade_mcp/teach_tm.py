"""Teach a TM or HM move to a party Pokemon from the overworld.

Automates the full menu flow: pause menu → Bag → TMs & HMs pocket →
select TM/HM → USE → "Booted up" dialogue → "Teach?" YES → select party
member → move-forget flow (if 4 moves) → close menus.

Handles both cases: 4 moves (forget prompt) and <4 moves (auto-learn).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.bag import read_bag
from renegade_mcp.bag_cursor import get_pocket_cursor
from renegade_mcp.data import (
    ITEM_TM01,
    can_learn_tm,
    item_id_to_tm_index,
    move_names,
    tm_move_name,
)
from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import (
    MENU_SIZE,
    open_pause_menu,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
MENU_WAIT = 300       # frames after major menu transitions
NAV_WAIT = 60         # frames after D-pad navigation
DISMISS_WAIT = 120    # frames after B press to dismiss text

# ── Pause menu ──
BAG_INDEX = 2

# ── Bag pocket touch coords (bottom screen) ──
TM_POCKET_COORDS = (100, 165)  # TMs & HMs tab

# ── Party screen layout (D-pad, 2-column grid) ──
PARTY_NAV = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _tap(emu: EmulatorClient, x: int, y: int, wait: int = NAV_WAIT) -> None:
    emu.tap_touch_screen(x, y, frames=8)
    emu.advance_frames(wait)


def _error(message: str) -> dict[str, Any]:
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


def teach_tm(
    emu: EmulatorClient,
    tm_name: str,
    party_slot: int = 0,
    forget_move: int | None = None,
) -> dict[str, Any]:
    """Teach a TM/HM to a party Pokemon.

    Args:
        emu: Emulator client.
        tm_name: TM/HM name (e.g. "HM06", "TM76") or move name
                 (e.g. "Rock Smash", "Stealth Rock"). Case-insensitive.
        party_slot: Party index 0-5.
        forget_move: Move slot (0-3) to forget if Pokemon knows 4 moves.
                     Required when Pokemon has 4 moves. Pass -1 to abort
                     (won't teach the move).

    Returns dict with success status and details.
    """
    tm_lower = tm_name.strip().lower()

    # ── Pre-checks ──

    # Find the TM/HM in the bag
    bag = read_bag(emu)
    tm_pocket = None
    for pocket in bag:
        if pocket["name"] == "TMs & HMs":
            tm_pocket = pocket
            break
    if tm_pocket is None:
        return _error("TMs & HMs pocket not found in bag data.")

    # Match by TM label (e.g. "HM06", "TM76") or by move name (e.g. "Rock Smash")
    item_index = None
    item_entry = None
    for i, item in enumerate(tm_pocket["items"]):
        bag_name = item["name"].lower()  # e.g. "hm06", "tm76"
        item_id = item["id"]
        tm_idx = item_id_to_tm_index(item_id)
        if tm_idx is None:
            continue
        move_name = tm_move_name(tm_idx)

        if bag_name == tm_lower or move_name.lower() == tm_lower:
            item_index = i
            item_entry = item
            break

    if item_entry is None:
        available = []
        for item in tm_pocket["items"]:
            tm_idx = item_id_to_tm_index(item["id"])
            if tm_idx is not None:
                available.append(f"{item['name']} ({tm_move_name(tm_idx)})")
        return _error(
            f"'{tm_name}' not found in TMs & HMs pocket. "
            f"Available: {available}"
        )

    tm_idx = item_id_to_tm_index(item_entry["id"])
    move_name = tm_move_name(tm_idx)
    tm_label = item_entry["name"]

    # Validate party slot
    party = read_party(emu)
    if party_slot < 0 or party_slot >= len(party):
        return _error(f"Party slot {party_slot} invalid. Party has {len(party)} member(s).")

    target_mon = party[party_slot]
    target_name = target_mon.get("name", f"Slot {party_slot}")
    species_id = target_mon.get("species_id", 0)

    # Check compatibility from ROM data
    if not can_learn_tm(species_id, tm_idx):
        return _error(
            f"{target_name} cannot learn {tm_label} ({move_name}). "
            "Not compatible according to ROM data."
        )

    # Check if already knows this move
    current_move_names = target_mon.get("move_names", [])
    for mn in current_move_names:
        if mn.lower() == move_name.lower():
            return _error(f"{target_name} already knows {move_name}.")

    # Check forget_move parameter for 4-move case
    num_moves = len([mn for mn in current_move_names if mn != "-"])
    if num_moves >= 4 and forget_move is None:
        move_list = [
            f"  {i}: {mn}" for i, mn in enumerate(current_move_names)
        ]
        return _error(
            f"{target_name} knows 4 moves. Pass forget_move (0-3) to choose "
            f"which to replace, or -1 to cancel.\n"
            + "\n".join(move_list)
        )

    # ── Step 1: Open pause menu ──
    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to Bag ──
    from renegade_mcp.addresses import addr
    cursor = emu.read_memory(addr("PAUSE_CURSOR_ADDR"), size="byte")
    steps = (BAG_INDEX - cursor) % MENU_SIZE
    for _ in range(steps):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Tap TMs & HMs pocket tab ──
    _tap(emu, *TM_POCKET_COORDS, wait=MENU_WAIT)

    # ── Step 4: Select TM/HM ──
    scroll, index = get_pocket_cursor(emu, "TMs & HMs")
    for _ in range(scroll + index):
        _press(emu, ["up"])
    for _ in range(item_index):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)  # Opens USE/CANCEL submenu

    # ── Step 5: Press A for "USE" (default selection) ──
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 6: "Booted up a TM/HM!" dialogue ──
    # Two text boxes: "Booted up a TM!" / "It contained [move]."
    _press(emu, ["a"], wait=MENU_WAIT)  # "Booted up a TM/HM."
    _press(emu, ["a"], wait=MENU_WAIT)  # "It contained [move]."

    # ── Step 7: "Teach [move] to a Pokemon?" YES/NO ──
    _press(emu, ["a"], wait=MENU_WAIT)  # YES (default)

    # ── Step 8: Select party member ──
    nav = PARTY_NAV.get(party_slot)
    if nav is None:
        for _ in range(5):
            _press(emu, ["b"], wait=DISMISS_WAIT)
        return _error(f"Party slot {party_slot} navigation not mapped.")

    for direction in nav:
        _press(emu, [direction])
    _press(emu, ["a"], wait=MENU_WAIT)  # Select Pokemon

    # ── Step 9: Handle move-learn flow ──
    if num_moves >= 4:
        if forget_move == -1:
            # User wants to cancel — "Wants to learn" → A → "already knows 4" → A →
            # "Should a move be deleted?" → NO
            _press(emu, ["a"], wait=MENU_WAIT)  # "[Mon] wants to learn..."
            _press(emu, ["a"], wait=MENU_WAIT)  # "However, already knows four moves."
            # "Should a move be deleted?" YES/NO → select NO
            _press(emu, ["down"])               # Move cursor to NO
            _press(emu, ["a"], wait=MENU_WAIT)  # Confirm NO
            # "Stop learning [move]?" — need to confirm
            _press(emu, ["a"], wait=MENU_WAIT)  # Advance text
            _press(emu, ["a"], wait=MENU_WAIT)  # YES to stop learning
            # "[Mon] did not learn [move]."
            _press(emu, ["a"], wait=MENU_WAIT)  # Dismiss

            # Back in bag — close menus
            _press(emu, ["b"], wait=MENU_WAIT)  # Close bag
            _press(emu, ["b"], wait=MENU_WAIT)  # Close pause menu

            return {
                "success": True,
                "action": "skipped",
                "tm": tm_label,
                "move": move_name,
                "target": target_name,
                "formatted": f"Cancelled teaching {move_name} to {target_name}.",
            }

        # Proceed with forgetting a move
        # "[Mon] wants to learn [move]." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "However, [Mon] already knows four moves." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "Should a move be deleted and replaced?" YES/NO → A (YES is default)
        _press(emu, ["a"], wait=MENU_WAIT)
        # "Which move should be forgotten?" → A
        _press(emu, ["a"], wait=MENU_WAIT)

        # Move selection screen: navigate to the move to forget (0-3)
        # Cursor starts at slot 0, moves are in a vertical list
        for _ in range(forget_move):
            _press(emu, ["down"])
        _press(emu, ["a"], wait=MENU_WAIT)  # Select move to forget

        # "1, 2, and... Poof!" → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "[Mon] forgot [old move]." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "And..." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "[Mon] learned [new move]!" → A
        _press(emu, ["a"], wait=MENU_WAIT)

    else:
        # <4 moves: game teaches automatically, no forget prompt.
        # Flow: "[Mon] learned [move]!" → A → back to bag
        _press(emu, ["a"], wait=MENU_WAIT)  # "[Mon] learned [move]!"

    # ── Step 10: Close menus (back in bag after teaching) ──
    _press(emu, ["b"], wait=MENU_WAIT)  # Close bag
    _press(emu, ["b"], wait=MENU_WAIT)  # Close pause menu

    # ── Step 11: Verify ──
    party_after = read_party(emu)
    if party_slot < len(party_after):
        new_move_names = party_after[party_slot].get("move_names", [])
        learned = any(mn.lower() == move_name.lower() for mn in new_move_names)
    else:
        learned = False
        new_move_names = []

    if learned:
        old_move_name = ""
        if forget_move is not None and 0 <= forget_move < len(current_move_names):
            old_move_name = current_move_names[forget_move]

        msg = f"{target_name} learned {move_name}!"
        if old_move_name:
            msg = f"{target_name} forgot {old_move_name} and learned {move_name}!"

        return {
            "success": True,
            "action": "learned",
            "tm": tm_label,
            "move": move_name,
            "target": target_name,
            "forgot": old_move_name or None,
            "new_moves": list(new_move_names),
            "formatted": msg,
        }
    else:
        return {
            "success": False,
            "tm": tm_label,
            "move": move_name,
            "target": target_name,
            "formatted": (
                f"Teaching may have failed. Could not verify {move_name} "
                f"in {target_name}'s moveset. Menu flow may have gone wrong."
            ),
        }
