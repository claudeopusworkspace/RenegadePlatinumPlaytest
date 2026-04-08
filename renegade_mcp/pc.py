"""Pokemon PC storage system tools.

Suite of tools for interacting with the Pokemon Storage System PC:
- open_pc: Navigate to PC tile, boot up, reach the storage menu
- deposit_pokemon: Deposit party Pokemon into boxes
- withdraw_pokemon: Withdraw box Pokemon to party
- read_box: Read Pokemon data from any PC box (memory read, no UI)
- close_pc: Exit the PC and return to overworld
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import item_names, move_names, species_names
from renegade_mcp.dialogue import read_dialogue
from renegade_mcp.map_state import get_map_state
from renegade_mcp.navigation import interact_with
from renegade_mcp.party import _decode_encrypted_pokemon, read_party

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

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

# ── PC Box Memory Layout ──
# Discovered via PID search: 5 Pokemon deposited in Box 1, PIDs found at
# 136-byte intervals. All checksums validated.
# BOX_DATA_BASE resolved at runtime via addr("BOX_DATA_BASE")
BOX_SLOT_SIZE = 136           # Gen 4 stored Pokemon (no battle extension)
SLOTS_PER_BOX = 30
NUM_BOXES = 18
BOX_GRID_COLS = 6             # Withdraw UI grid: 6 columns × 5 rows


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

    After interact_with returns, the game may be in different states:
    - On melonDS: advance_dialogue dismisses the "Which PC?" menu (B = cancel),
      returning to overworld. Player is still facing the PC.
    - On DeSmuME: advance_dialogue stops at "Which PC?" menu.

    This function detects the current state and navigates to the storage menu.

    Returns None on success, error dict on failure.
    """
    from renegade_mcp.dialogue import _find_script_manager, _read_script_state

    # Check if a dialogue box or menu is still active
    mgr = _find_script_manager(emu)
    in_dialogue = False
    if mgr:
        ss = _read_script_state(emu, mgr)
        in_dialogue = ss["is_msg_box_open"] or ss["sub_ctx_active"]

    if not in_dialogue:
        # Overworld — re-interact with PC (player is still facing it)
        _press(emu, ["a"], wait=TEXT_WAIT)
        # "CLAUDE booted up the PC." has two text pages — advance both
        _press(emu, ["b"], wait=TEXT_WAIT)
        _press(emu, ["b"], wait=MENU_WAIT)
    else:
        # Still in dialogue — clear any remaining boot text
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
    # Enter DEPOSIT (first option, already highlighted).
    # Short hold (2f) to prevent A from bleeding into the party grid —
    # on melonDS, 8f spans the fast menu transition and auto-selects slot 0.
    emu.press_buttons(["a"], frames=2)
    emu.advance_frames(MENU_WAIT)

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


def _nav_to_box_slot(emu: EmulatorClient, slot: int) -> None:
    """Navigate the withdraw screen's box grid from slot 0 to the target slot.

    Box grid layout (6 columns × 5 rows):
        [0]  [1]  [2]  [3]  [4]  [5]
        [6]  [7]  [8]  [9]  [10] [11]
        [12] [13] [14] [15] [16] [17]
        [18] [19] [20] [21] [22] [23]
        [24] [25] [26] [27] [28] [29]
    """
    col = slot % BOX_GRID_COLS
    row = slot // BOX_GRID_COLS
    for _ in range(row):
        _press(emu, ["down"], wait=NAV_WAIT)
    for _ in range(col):
        _press(emu, ["right"], wait=NAV_WAIT)


def _withdraw_one(emu: EmulatorClient, slot: int) -> None:
    """Withdraw a single box Pokemon from the withdraw screen.

    Flow: navigate grid → select → WITHDRAW → animation →
    "Continue?" → No → back to storage menu.

    Cursor always starts at slot 0 when entering WITHDRAW fresh.
    """
    # Navigate to target slot from slot 0
    _nav_to_box_slot(emu, slot)

    # A = select Pokemon → action menu (WITHDRAW highlighted)
    _press(emu, ["a"], wait=NAV_WAIT)
    # A = WITHDRAW
    _press(emu, ["a"], wait=DEPOSIT_ANIM_WAIT)

    # Dismiss "Withdrew [name]." text
    _press(emu, ["b"], wait=NAV_WAIT)
    emu.advance_frames(60)

    # "Continue Box operations?" prompt → No (down from Yes)
    _press(emu, ["down"], wait=NAV_WAIT)
    _press(emu, ["a"], wait=MENU_WAIT)


# ── Public API ──


def read_box(emu: EmulatorClient, box: int = 1) -> dict[str, Any]:
    """Read all Pokemon in a PC box directly from memory.

    No UI interaction needed — reads the encrypted box data from RAM
    and decrypts it using the same Gen 4 algorithm as party data.

    Args:
        box: Box number (1-18). Defaults to Box 1.
    """
    if box < 1 or box > NUM_BOXES:
        return _error(f"Invalid box number {box} (must be 1-{NUM_BOXES}).")

    sp_names = species_names()
    mv_names = move_names()
    it_names = item_names()

    # Calculate base address for this box
    from renegade_mcp.addresses import addr
    box_base = addr("BOX_DATA_BASE") + (box - 1) * SLOTS_PER_BOX * BOX_SLOT_SIZE

    # Read all 30 slots at once
    raw = emu.read_memory_range(box_base, size="byte", count=SLOTS_PER_BOX * BOX_SLOT_SIZE)
    data = bytes(raw)

    pokemon = []
    for i in range(SLOTS_PER_BOX):
        slot_data = data[i * BOX_SLOT_SIZE : (i + 1) * BOX_SLOT_SIZE]
        decoded = _decode_encrypted_pokemon(slot_data)
        if decoded is None:
            continue  # Empty slot

        species = decoded["species_id"]
        if species == 0:
            continue

        name = sp_names.get(species, f"Pokemon#{species}")
        held = it_names.get(decoded["item_id"], "") if decoded["item_id"] > 0 else ""

        entry: dict[str, Any] = {
            "slot": i,
            "species_id": species,
            "name": name,
            "shiny": decoded.get("shiny", False),
            "nature": decoded["nature"],
            "exp": decoded["exp"],
            "moves": decoded["moves"],
            "move_names": [
                mv_names.get(m, f"#{m}") if m > 0 else "-" for m in decoded["moves"]
            ],
            "pp": decoded["pp"],
            "ivs": decoded["ivs"],
            "evs": decoded["evs"],
            "friendship": decoded["friendship"],
        }
        if held:
            entry["held_item"] = held
        if decoded.get("partial"):
            entry["partial"] = True

        pokemon.append(entry)

    # Format output
    lines = [f"=== Box {box} ({len(pokemon)} Pokemon) ==="]
    for p in pokemon:
        shiny_tag = " *SHINY*" if p.get("shiny") else ""
        nature_str = f" ({p['nature']})" if p.get("nature") else ""
        held_str = f"  [{p['held_item']}]" if p.get("held_item") else ""
        partial_tag = " [stale]" if p.get("partial") else ""
        lines.append(f"  {p['slot']:2d}. {p['name']}{shiny_tag}{nature_str}{held_str}{partial_tag}")
        if not p.get("partial") and p.get("move_names"):
            moves = [m for m in p["move_names"] if m != "-"]
            lines.append(f"      Moves: {', '.join(moves)}")
        ivs = p.get("ivs", {})
        if ivs and not p.get("partial"):
            iv_str = "/".join(str(ivs[s]) for s in ["hp", "atk", "def", "spa", "spd", "spe"])
            lines.append(f"      IVs: {iv_str}")

    return {
        "success": True,
        "box": box,
        "count": len(pokemon),
        "pokemon": pokemon,
        "formatted": "\n".join(lines),
    }


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


def withdraw_pokemon(emu: EmulatorClient, box_slots: list[int]) -> dict[str, Any]:
    """Withdraw one or more Pokemon from Box 1 to the party.

    Must be called after open_pc (at the storage system menu).
    For each slot, enters WITHDRAW, navigates the box grid, withdraws,
    exits back to the storage menu, then repeats for the next slot.

    Box slots are withdrawn lowest-first so indices don't shift unexpectedly.

    Args:
        box_slots: List of 0-indexed box slots to withdraw from Box 1.
    """
    if not box_slots:
        return _error("No box slots specified.")

    # Validate slots
    box_data = read_box(emu, box=1)
    if not box_data.get("success"):
        return _error("Could not read box data.")

    occupied_slots = {p["slot"] for p in box_data["pokemon"]}
    for s in box_slots:
        if s < 0 or s >= SLOTS_PER_BOX:
            return _error(f"Invalid box slot {s} (must be 0-{SLOTS_PER_BOX - 1}).")
        if s not in occupied_slots:
            return _error(f"Box slot {s} is empty.")

    if len(set(box_slots)) != len(box_slots):
        return _error("Duplicate slots in box_slots.")

    # Check party has room
    party = read_party(emu)
    party_size = len(party)
    if party_size + len(box_slots) > 6:
        return _error(
            f"Party has {party_size} Pokemon — cannot withdraw {len(box_slots)} more "
            f"(max 6)."
        )

    # Build slot→name lookup
    slot_to_name: dict[int, str] = {}
    sp_names = species_names()
    for p in box_data["pokemon"]:
        slot_to_name[p["slot"]] = p.get("name", sp_names.get(p["species_id"], "???"))

    # Order doesn't matter for box grid (slots are fixed, no compaction),
    # but withdraw in the order requested.
    for raw_slot in box_slots:
        # Navigate to WITHDRAW option on storage menu
        # First go to top
        for _ in range(5):
            _press(emu, ["up"], wait=NAV_WAIT)
        # Down to WITHDRAW (index 1)
        _press(emu, ["down"], wait=NAV_WAIT)
        # Enter WITHDRAW mode — short hold to prevent A bleed-through
        emu.press_buttons(["a"], frames=2)
        emu.advance_frames(MENU_WAIT)

        # Withdraw — box grid positions are fixed (no shifting)
        _withdraw_one(emu, raw_slot)

    # Format results
    names = [slot_to_name.get(s, f"slot {s}") for s in box_slots]
    new_party_size = party_size + len(box_slots)

    return {
        "success": True,
        "withdrawn": box_slots,
        "withdrawn_names": names,
        "new_party_size": new_party_size,
        "formatted": (
            f"Withdrew {len(box_slots)} Pokemon from Box 1: "
            f"{', '.join(names)}. Party now has {new_party_size} Pokemon."
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
