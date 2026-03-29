"""Pokemon PC storage system tools.

Suite of tools for interacting with the Pokemon Storage System PC:
- open_pc: Navigate to PC tile, boot up, reach the storage menu
- deposit_pokemon: Deposit party Pokemon into boxes
- close_pc: Exit the PC and return to overworld
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.dialogue import read_dialogue
from renegade_mcp.map_state import get_map_state
from renegade_mcp.navigation import interact_with
from renegade_mcp.party import read_party

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Constants ──
PC_BEHAVIOR = 0x83            # Terrain behavior for PC tiles
TEXT_WAIT = 120               # Frames to let dialogue render
MENU_WAIT = 180               # Frames for menu transitions
DEPOSIT_ANIM_WAIT = 120       # Frames for deposit animation
NAV_WAIT = 30                 # Frames between D-pad presses in menus

# Storage menu options (D-pad down from top)
STORAGE_DEPOSIT = 0
STORAGE_WITHDRAW = 1
STORAGE_MOVE = 2
STORAGE_MOVE_ITEMS = 3
STORAGE_SEE_YA = 4


def _press(emu: EmulatorClient, buttons: list[str], wait: int = TEXT_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _error(msg: str) -> dict[str, Any]:
    return {"success": False, "error": msg}


def _find_pc_tile(state: dict[str, Any]) -> tuple[int, int] | None:
    """Find the southernmost PC tile (behavior 0x83) on the current map."""
    terrain = state["terrain"]
    origin_x = state.get("origin_x", 0)
    origin_y = state.get("origin_y", 0)
    best = None
    for row_idx, row in enumerate(terrain):
        for col_idx, val in enumerate(row):
            behavior = val & 0x00FF
            if behavior == PC_BEHAVIOR:
                global_x = col_idx + origin_x
                global_y = row_idx + origin_y
                if best is None or global_y > best[1]:
                    best = (global_x, global_y)
    return best


def _advance_to_storage_menu(emu: EmulatorClient) -> dict[str, Any] | None:
    """Advance through PC boot dialogue to the storage system menu.

    After interact_with returns, the game is showing "CLAUDE booted up the PC."
    text (read_dialogue already captured it, but the text box is still visible).

    Flow:
    1. B × 2 + waits → clears boot text, "Which PC?" menu appears
    2. A → selects SOMEONE'S PC (first option)
    3. B + wait → clears "Storage System was accessed" text
    4. Storage menu visible (DEPOSIT/WITHDRAW/MOVE/MOVE ITEMS/SEE YA!)

    Returns None on success, error dict on failure.
    """
    # Clear "booted up the PC" text — may need 2 B presses depending on
    # where read_dialogue left the text state
    _press(emu, ["b"], wait=TEXT_WAIT)
    _press(emu, ["b"], wait=MENU_WAIT)

    # "Which PC?" menu should now be visible — select SOMEONE'S PC
    _press(emu, ["a"], wait=MENU_WAIT)

    # "The Pokemon Storage System was accessed." text — dismiss it
    _press(emu, ["b"], wait=MENU_WAIT)

    # Now at storage menu
    return None


def _nav_to_party_slot(emu: EmulatorClient, slot: int) -> None:
    """Navigate the deposit screen's party grid from slot 0 to the target slot.

    Party grid layout (2 columns):
        slot 0 | slot 1
        slot 2 | slot 3
        slot 4 | slot 5

    From slot 0: down for each row, then right for column 1.
    """
    col = slot % 2
    row = slot // 2
    for _ in range(row):
        _press(emu, ["down"], wait=NAV_WAIT)
    for _ in range(col):
        _press(emu, ["right"], wait=NAV_WAIT)


def _deposit_one(emu: EmulatorClient, slot: int) -> None:
    """Deposit a single party Pokemon from the storage menu.

    Flow: enter DEPOSIT → navigate grid → select → STORE → confirm box →
    "Continue?" → No → back to storage menu.

    Cursor always starts at slot 0 when entering DEPOSIT fresh.
    """
    # Enter DEPOSIT (first option, already highlighted)
    _press(emu, ["a"], wait=MENU_WAIT)

    # Navigate to target slot from slot 0
    _nav_to_party_slot(emu, slot)

    # A = select Pokemon → action menu (STORE highlighted)
    _press(emu, ["a"], wait=NAV_WAIT)
    # A = STORE
    _press(emu, ["a"], wait=MENU_WAIT)
    # A = confirm Box 1
    _press(emu, ["a"], wait=DEPOSIT_ANIM_WAIT)

    # B → "Continue Box operations?" prompt
    _press(emu, ["b"], wait=NAV_WAIT)
    emu.advance_frames(60)

    # Select No (down from Yes) → back to storage menu
    _press(emu, ["down"], wait=NAV_WAIT)
    _press(emu, ["a"], wait=MENU_WAIT)


# ── Public API ──


def open_pc(emu: EmulatorClient) -> dict[str, Any]:
    """Find the PC, navigate to it, boot up, and reach the storage menu.

    Scans the current map for tiles with behavior 0x83 (PC), picks the
    southernmost one, navigates there, interacts, and advances through
    the dialogue to reach the storage system menu.
    """
    state = get_map_state(emu)
    if state is None:
        return _error("Could not read map state.")

    pc_tile = _find_pc_tile(state)
    if pc_tile is None:
        return _error("No PC tile (behavior 0x83) found on current map.")

    pc_x, pc_y = pc_tile

    # Navigate to and interact with the PC tile
    result = interact_with(emu, x=pc_x, y=pc_y)

    if result.get("error"):
        return _error(f"Could not reach PC: {result['error']}")
    if result.get("interrupted") or result.get("stopped_early"):
        return _error("Navigation to PC was interrupted.")

    dialogue = result.get("dialogue")
    if not dialogue or "booted up the PC" not in dialogue.get("text", ""):
        return _error(
            f"Unexpected dialogue at PC tile: "
            f"{dialogue.get('text', '(none)') if dialogue else '(none)'}"
        )

    # Advance through boot dialogue to storage menu
    err = _advance_to_storage_menu(emu)
    if err:
        return err

    return {
        "success": True,
        "pc_tile": {"x": pc_x, "y": pc_y},
        "formatted": (
            f"PC booted at ({pc_x}, {pc_y}). "
            "At storage menu: DEPOSIT / WITHDRAW / MOVE / MOVE ITEMS / SEE YA!"
        ),
    }


def deposit_pokemon(emu: EmulatorClient, party_slots: list[int]) -> dict[str, Any]:
    """Deposit one or more party Pokemon into the PC from the storage menu.

    Must be called after open_pc (at the storage system menu).
    For each slot, enters DEPOSIT, navigates the party grid, stores to Box 1,
    exits back to the storage menu, then repeats for the next slot.

    Party slots are deposited highest-first so indices don't shift unexpectedly.

    Args:
        party_slots: List of 0-indexed party slots to deposit.
    """
    if not party_slots:
        return _error("No party slots specified.")

    # Validate slots
    party = read_party(emu)
    party_size = len(party)

    for s in party_slots:
        if s < 0 or s >= party_size:
            return _error(f"Invalid slot {s} — party has {party_size} Pokemon (0-{party_size - 1}).")

    if len(set(party_slots)) != len(party_slots):
        return _error("Duplicate slots in party_slots.")

    remaining_after = party_size - len(party_slots)
    if remaining_after < 1:
        return _error(
            f"Cannot deposit {len(party_slots)} of {party_size} Pokemon — "
            "must keep at least 1 in party."
        )

    # Sort descending so highest-index deposits first (lower indices don't shift)
    sorted_slots = sorted(party_slots, reverse=True)

    deposited = []
    current_party_size = party_size

    for raw_slot in sorted_slots:
        # Adjust slot index: for each previously deposited slot with a LOWER
        # index than this one, this slot's effective index shifts down by 1.
        effective_slot = raw_slot
        for prev in deposited:
            if prev < raw_slot:
                effective_slot -= 1

        if effective_slot >= current_party_size:
            effective_slot = current_party_size - 1

        # Deposit this Pokemon (enters DEPOSIT, navigates, stores, exits to storage menu)
        _deposit_one(emu, effective_slot)

        deposited.append(raw_slot)
        current_party_size -= 1

    # Format results
    names = []
    for s in party_slots:
        if s < len(party):
            p = party[s]
            names.append(f"{p.get('name', '???')} Lv{p.get('level', '?')}")
        else:
            names.append(f"slot {s}")

    return {
        "success": True,
        "deposited": party_slots,
        "deposited_names": names,
        "remaining_party_size": current_party_size,
        "formatted": (
            f"Deposited {len(party_slots)} Pokemon into Box 1: "
            f"{', '.join(names)}. Party now has {current_party_size} Pokemon."
        ),
    }


def close_pc(emu: EmulatorClient) -> dict[str, Any]:
    """Close the PC and return to the overworld.

    Must be called from the storage system menu (after open_pc or deposit_pokemon).
    Selects SEE YA! (5th option) and exits.
    """
    # Navigate to SEE YA! (index 4, from top)
    # First go to top of menu
    for _ in range(5):
        _press(emu, ["up"], wait=NAV_WAIT)

    # Now go down to SEE YA! (4 down from DEPOSIT)
    for _ in range(STORAGE_SEE_YA):
        _press(emu, ["down"], wait=NAV_WAIT)

    # Select SEE YA!
    _press(emu, ["a"])

    # Advance through any remaining dialogue/animation
    emu.advance_frames(MENU_WAIT)

    # The "Which PC?" menu may reappear — select SWITCH OFF (last option)
    # Press down to SWITCH OFF and select it
    for _ in range(4):
        _press(emu, ["down"], wait=NAV_WAIT)
    _press(emu, ["a"])
    emu.advance_frames(MENU_WAIT)

    # Verify we're back in the overworld by checking dialogue is gone
    leftover = read_dialogue(emu, region="overworld")
    if leftover.get("region") != "none":
        # Still in some dialogue — press B a few times
        for _ in range(5):
            _press(emu, ["b"], wait=60)
        emu.advance_frames(MENU_WAIT)

    return {
        "success": True,
        "formatted": "PC closed. Back in overworld.",
    }
