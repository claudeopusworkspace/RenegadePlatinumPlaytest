"""Move Relearner and Move Deleter NPC interaction tools.

Move Relearner: Pastoria City, map 129 (C06R0401), warp (611, 835).
  NPC: "Collector". Free in Renegade Platinum (no Heart Scale).
  Flow: interact → party select → scrollable move list → forget prompt → done.

Move Deleter: Oreburgh City, map 58 (C03R0301), warp (293, 752).
  NPC: "Old Man". Free.
  Flow: interact → Yes/No → party select → current move list → confirm → done.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import map_table, move_names as all_move_names
from renegade_mcp.map_state import (
    get_map_state,
    read_player_state,
    read_warps_from_rom,
)
from renegade_mcp.navigation import interact_with, navigate_to
from renegade_mcp.party import read_party

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
TEXT_WAIT = 120       # frames for dialogue line to render
MENU_WAIT = 300       # frames for major menu/screen transitions
NAV_WAIT = 60         # frames after D-pad navigation
SETTLE_WAIT = 120     # frames after final dialogue dismissal

# ── Move Relearner ──
RELEARNER_MAP_ID = 129          # C06R0401 — Pastoria City house
RELEARNER_CITY_CODE = "C06"     # Pastoria City
RELEARNER_NPC_NAME = "Collector"
RELEARNER_WARP_X = 611
RELEARNER_WARP_Y = 835

# ── Move Deleter ──
DELETER_MAP_ID = 58             # C03R0301 — Oreburgh City house
DELETER_CITY_CODE = "C03"       # Oreburgh City
DELETER_NPC_NAME = "Old Man"
DELETER_WARP_X = 293
DELETER_WARP_Y = 752

# ── Party select (D-pad, 2-column grid) ──
PARTY_NAV = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}


def _press(emu: EmulatorClient, buttons: list[str], wait: int = TEXT_WAIT) -> None:
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _error(message: str) -> dict[str, Any]:
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


# ── Location helpers ──


def _city_code_from_map(map_id: int) -> str | None:
    """Extract city/town code (e.g. 'C01', 'T03') from a map ID."""
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")
    m = re.match(r"^([CT]\d{2})", code)
    return m.group(1) if m else None


def _find_building_warp(
    emu: EmulatorClient,
    map_id: int,
    target_map_id: int,
) -> dict | None:
    """Find a warp on the current map that leads to the target map ID."""
    warps = read_warps_from_rom(emu, map_id)
    for w in warps:
        if w["dest_map"] == target_map_id:
            return w
    return None


def _navigate_to_npc_building(
    emu: EmulatorClient,
    target_map_id: int,
    city_code: str,
    city_name: str,
    npc_label: str,
    warp_x: int,
    warp_y: int,
) -> dict[str, Any] | None:
    """Ensure player is inside the target NPC's building.

    Returns None on success, or an error dict if navigation fails.
    """
    map_id, _, _, _ = read_player_state(emu)
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")

    if map_id == target_map_id:
        # Already in the right room
        return None

    # Check if we're in the right city (outdoor map or another building)
    current_city = _city_code_from_map(map_id)

    if current_city == city_code and code == city_code:
        # On the city overworld — navigate to the building warp
        warp = _find_building_warp(emu, map_id, target_map_id)
        if warp is None:
            # Fall back to known coordinates
            warp = {"x": warp_x, "y": warp_y}

        nav = navigate_to(emu, warp["x"], warp["y"], flee_encounters=True)
        if nav.get("encounter"):
            return {
                "success": False,
                "error": f"Trainer battle interrupted navigation to {npc_label}.",
                "encounter": nav["encounter"],
            }
        if not nav.get("door_entered"):
            return _error(
                f"Navigated to warp at ({warp['x']}, {warp['y']}) but "
                f"did not enter the building. Try moving closer manually."
            )

        # Verify we're in the right map now
        new_map, _, _, _ = read_player_state(emu)
        if new_map != target_map_id:
            return _error(
                f"Entered map {new_map} but expected {target_map_id} "
                f"({npc_label}'s building). Are you in the right city?"
            )
        return None

    # Not in the right city at all
    return _error(
        f"Not in {city_name}. The {npc_label} is in {city_name} "
        f"(map {target_map_id}, city code {city_code}). "
        f"Fly to {city_name} first, or enter the {npc_label}'s building directly."
    )


def _find_npc(
    emu: EmulatorClient, npc_name: str, label: str,
) -> tuple[dict | None, dict[str, Any] | None]:
    """Find an NPC by name on the current map.

    Returns (npc_dict, None) on success, or (None, error_dict) on failure.
    """
    state = get_map_state(emu)
    if state is None:
        return None, _error("Could not read map state.")

    npc = next(
        (obj for obj in state["objects"] if obj.get("name") == npc_name),
        None,
    )
    if npc is None:
        names = [
            obj.get("name", "?")
            for obj in state["objects"]
            if obj["index"] != 0
        ]
        return None, _error(
            f"No {label} ('{npc_name}') found. NPCs: {', '.join(names)}"
        )
    return npc, None


def _select_party_member(emu: EmulatorClient, party_slot: int) -> None:
    """Navigate the party selection screen to a slot and press A."""
    nav = PARTY_NAV.get(party_slot, [])
    for direction in nav:
        _press(emu, [direction], wait=NAV_WAIT)
    _press(emu, ["a"], wait=MENU_WAIT)


# ── Move Relearner ──


def relearn_move(
    emu: EmulatorClient,
    move_name: str,
    party_slot: int = 0,
    forget_move: int | None = None,
) -> dict[str, Any]:
    """Teach a party Pokemon a previously-known move via the Move Relearner.

    Args:
        emu: Emulator client.
        move_name: Name of the move to relearn (case-insensitive).
        party_slot: Party index 0-5. Default 0 (lead).
        forget_move: Move slot (0-3) to forget if the Pokemon knows 4 moves.
                     Pass -1 to cancel without learning. None = not provided
                     (tool will return an error listing current moves if 4 full).
    """
    move_lower = move_name.strip().lower()

    # ── Pre-checks ──
    party = read_party(emu)
    if party_slot < 0 or party_slot >= len(party):
        return _error(
            f"Party slot {party_slot} invalid. Party has {len(party)} member(s)."
        )
    target = party[party_slot]
    target_name = target.get("name", f"Slot {party_slot}")
    current_moves = target.get("move_names", [])

    # Check if already knows this move
    for mn in current_moves:
        if mn.lower() == move_lower:
            return _error(f"{target_name} already knows {move_name}.")

    # Check 4-move case
    num_moves = len([mn for mn in current_moves if mn != "-"])
    if num_moves >= 4 and forget_move is None:
        move_list = [f"  {i}: {mn}" for i, mn in enumerate(current_moves)]
        return _error(
            f"{target_name} knows 4 moves. Pass forget_move (0-3) to choose "
            f"which to replace, or -1 to cancel.\n" + "\n".join(move_list)
        )

    # ── Navigate to building ──
    nav_err = _navigate_to_npc_building(
        emu, RELEARNER_MAP_ID, RELEARNER_CITY_CODE, "Pastoria City",
        "Move Relearner", RELEARNER_WARP_X, RELEARNER_WARP_Y,
    )
    if nav_err is not None:
        return nav_err

    # ── Find NPC ──
    npc, err = _find_npc(emu, RELEARNER_NPC_NAME, "Move Relearner")
    if err is not None:
        return err

    # ── Interact ──
    result = interact_with(emu, npc["index"])
    if result.get("encounter"):
        return _error(f"Encounter during navigation: {result['encounter']}")

    # The relearner auto-advances into "Which Pokemon needs tutoring?"
    # which opens the party select screen (no Yes/No gate).
    # read_dialogue has already auto-advanced through the opening dialogue.
    # We should now be at the party select screen.

    # ── Select party member ──
    _select_party_member(emu, party_slot)

    # Wait for move list to load (fade out + OpenMoveReminderMenu + fade in)
    # Press A to advance past "Which move should I teach?" if needed
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Navigate the scrollable move list ──
    # Pre-compute position from ROM learnset data (same approach as buy_item).
    found, nav_err = _navigate_relearner_list(emu, move_lower, target)
    if nav_err is not None:
        # Cancel out of the relearner
        _press(emu, ["b"], wait=MENU_WAIT)
        _press(emu, ["b"], wait=MENU_WAIT)
        _press(emu, ["b"], wait=SETTLE_WAIT)
        return nav_err

    # ── A pressed on the target move. Now handle the learning flow. ──

    # "Dusknoir wants to remember the move X." → A
    _press(emu, ["a"], wait=MENU_WAIT)

    if num_moves >= 4:
        if forget_move == -1:
            # "But X can't learn more than four moves." → A
            _press(emu, ["a"], wait=MENU_WAIT)
            # "Delete an existing move to make room?" YES/NO → select NO
            _press(emu, ["down"], wait=NAV_WAIT)  # Move to NO
            _press(emu, ["a"], wait=MENU_WAIT)     # Confirm NO
            # "Give up trying to make X remember a move?" → back to list
            # Dismiss remaining dialogue
            for _ in range(5):
                _press(emu, ["b"], wait=TEXT_WAIT)
            _press(emu, ["b"], wait=SETTLE_WAIT)

            return {
                "success": True,
                "action": "skipped",
                "move": move_name,
                "target": target_name,
                "formatted": f"Cancelled relearning {move_name} for {target_name}.",
            }

        # "But X can't learn more than four moves." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "Delete an existing move to make room for Y?" YES/NO → A (YES)
        _press(emu, ["a"], wait=MENU_WAIT)

        # Move selection screen: navigate to the move to forget (0-3)
        # Cursor starts at slot 0
        for _ in range(forget_move):
            _press(emu, ["down"], wait=NAV_WAIT)
        _press(emu, ["a"], wait=MENU_WAIT)  # Select move to forget

        # "Is it OK to make this Pokemon forget X?" YES/NO → A (YES)
        _press(emu, ["a"], wait=MENU_WAIT)

        # "1, 2, and... Poof!" → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "X forgot Y." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "And..." → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "X remembered the move Y." → A
        _press(emu, ["a"], wait=MENU_WAIT)

    else:
        # <4 moves: no forget prompt needed
        # "1, 2, and... Poof!" → A
        _press(emu, ["a"], wait=MENU_WAIT)
        # "X remembered the move Y." → A
        _press(emu, ["a"], wait=MENU_WAIT)

    # "That'll do it. Come back again..." → dismiss
    _press(emu, ["a"], wait=SETTLE_WAIT)
    # May need extra dismissal
    _press(emu, ["b"], wait=SETTLE_WAIT)

    # ── Verify ──
    party_after = read_party(emu)
    if party_slot < len(party_after):
        new_moves = party_after[party_slot].get("move_names", [])
        learned = any(mn.lower() == move_lower for mn in new_moves)
    else:
        learned = False
        new_moves = []

    old_move_name = ""
    if forget_move is not None and 0 <= forget_move < len(current_moves):
        old_move_name = current_moves[forget_move]

    if learned:
        msg = f"{target_name} relearned {move_name}!"
        if old_move_name:
            msg = f"{target_name} forgot {old_move_name} and relearned {move_name}!"
        return {
            "success": True,
            "action": "learned",
            "move": move_name,
            "target": target_name,
            "forgot": old_move_name or None,
            "new_moves": list(new_moves),
            "formatted": msg,
        }

    return {
        "success": False,
        "move": move_name,
        "target": target_name,
        "new_moves": list(new_moves),
        "formatted": (
            f"Could not verify {move_name} in {target_name}'s moveset. "
            f"Current moves: {new_moves}. Menu flow may have gone wrong."
        ),
    }


def _get_relearnable_moves(species_id: int, level: int) -> list[str]:
    """Get the ordered list of relearnable moves for a species at a given level.

    Mirrors the game's MoveReminderData_GetMoves algorithm: level-up moves
    at or below the Pokemon's current level, deduplicated, in learnset order.
    Does NOT filter out currently-known moves (caller handles that).
    """
    from renegade_mcp.data import level_up_moves
    learnset = level_up_moves(species_id)
    names = all_move_names()
    seen: set[str] = set()
    result: list[str] = []
    for lv, move_id in learnset:
        if lv > level:
            continue
        name = names.get(move_id, "")
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _navigate_relearner_list(
    emu: EmulatorClient,
    target_move_lower: str,
    target_mon: dict,
) -> tuple[bool, dict[str, Any] | None]:
    """Navigate the relearner's scrollable move list to the target move.

    Returns (True, None) if move found and A pressed on it,
    or (False, error_dict) if the move isn't in the list.
    """
    species_id = target_mon.get("species_id", 0)
    level = target_mon.get("level", 100)
    current_move_names = {
        mn.lower() for mn in target_mon.get("move_names", []) if mn != "-"
    }

    # Build expected relearner list: level-up moves at/below level, minus known
    all_levelup = _get_relearnable_moves(species_id, level)
    relearnable = [
        m for m in all_levelup if m.lower() not in current_move_names
    ]

    # Find target position
    target_index = None
    for i, m in enumerate(relearnable):
        if m.lower() == target_move_lower:
            target_index = i
            break

    if target_index is None:
        return False, _error(
            f"'{target_move_lower}' is not in the relearnable move list for "
            f"{target_mon.get('name', '?')}. Available moves: "
            f"{', '.join(relearnable[:20])}"
            + (f"... ({len(relearnable)} total)" if len(relearnable) > 20 else "")
        )

    # Navigate: cursor starts at index 0, press down target_index times
    for _ in range(target_index):
        _press(emu, ["down"], wait=NAV_WAIT)

    # Press A to select
    _press(emu, ["a"], wait=MENU_WAIT)

    return True, None


# ── Move Deleter ──


def delete_move(
    emu: EmulatorClient,
    move_name: str,
    party_slot: int = 0,
) -> dict[str, Any]:
    """Delete a move from a party Pokemon via the Move Deleter.

    Args:
        emu: Emulator client.
        move_name: Name of the move to delete (case-insensitive).
        party_slot: Party index 0-5. Default 0 (lead).
    """
    move_lower = move_name.strip().lower()

    # ── Pre-checks ──
    party = read_party(emu)
    if party_slot < 0 or party_slot >= len(party):
        return _error(
            f"Party slot {party_slot} invalid. Party has {len(party)} member(s)."
        )
    target = party[party_slot]
    target_name = target.get("name", f"Slot {party_slot}")
    current_moves = target.get("move_names", [])

    # Find the move slot
    move_slot = None
    for i, mn in enumerate(current_moves):
        if mn.lower() == move_lower:
            move_slot = i
            break

    if move_slot is None:
        return _error(
            f"{target_name} doesn't know '{move_name}'. "
            f"Current moves: {', '.join(current_moves)}"
        )

    # Check that Pokemon has at least 2 moves (can't delete the last one)
    num_moves = len([mn for mn in current_moves if mn != "-"])
    if num_moves <= 1:
        return _error(
            f"{target_name} only knows 1 move ({current_moves[0]}). "
            f"Cannot delete the last move."
        )

    # ── Navigate to building ──
    nav_err = _navigate_to_npc_building(
        emu, DELETER_MAP_ID, DELETER_CITY_CODE, "Oreburgh City",
        "Move Deleter", DELETER_WARP_X, DELETER_WARP_Y,
    )
    if nav_err is not None:
        return nav_err

    # ── Find NPC ──
    npc, err = _find_npc(emu, DELETER_NPC_NAME, "Move Deleter")
    if err is not None:
        return err

    # ── Interact ──
    result = interact_with(emu, npc["index"])
    if result.get("encounter"):
        return _error(f"Encounter during navigation: {result['encounter']}")

    # Dialogue stops at Yes/No: "You've come to make me force your
    # Pokemon to forget some moves?"
    dialogue = result.get("dialogue", {})
    status = dialogue.get("status", "")

    if status != "yes_no_prompt":
        # Try to recover — maybe dialogue auto-advanced
        return _error(
            f"Expected Yes/No prompt from Move Deleter but got status='{status}'. "
            f"Dialogue: {dialogue.get('text', '')[:200]}"
        )

    # ── Answer YES ──
    _press(emu, ["a"], wait=TEXT_WAIT)

    # "Which Pokemon should forget a move?" → auto-advances to party select
    from renegade_mcp.dialogue import advance_dialogue
    advance_dialogue(emu)

    # ── Select party member ──
    _select_party_member(emu, party_slot)

    # "OK, then. Which move should be forgotten?" → advance to move list
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Navigate to the move in the 4-slot list ──
    # Move list shows current moves (up to 4) + CANCEL.
    # Cursor starts at slot 0.
    for _ in range(move_slot):
        _press(emu, ["down"], wait=NAV_WAIT)
    _press(emu, ["a"], wait=MENU_WAIT)  # Select the move

    # "Hm! The move X? Should that move be forgotten?" YES/NO → A (YES)
    _press(emu, ["a"], wait=MENU_WAIT)

    # "It worked perfectly!" → A
    _press(emu, ["a"], wait=MENU_WAIT)
    # "Your Pokemon has forgotten the move X completely." → A
    _press(emu, ["a"], wait=SETTLE_WAIT)
    # May need extra dismissal
    _press(emu, ["b"], wait=SETTLE_WAIT)

    # ── Verify ──
    party_after = read_party(emu)
    if party_slot < len(party_after):
        new_moves = party_after[party_slot].get("move_names", [])
        deleted = all(mn.lower() != move_lower for mn in new_moves if mn != "-")
    else:
        deleted = False
        new_moves = []

    if deleted:
        return {
            "success": True,
            "action": "deleted",
            "move": move_name,
            "target": target_name,
            "new_moves": [mn for mn in new_moves if mn != "-"],
            "formatted": f"{target_name} forgot {move_name}!",
        }

    return {
        "success": False,
        "move": move_name,
        "target": target_name,
        "new_moves": list(new_moves),
        "formatted": (
            f"Could not verify {move_name} was deleted from {target_name}'s moveset. "
            f"Current moves: {new_moves}. Menu flow may have gone wrong."
        ),
    }
