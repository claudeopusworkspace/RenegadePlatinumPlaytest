"""Post-navigation event handling: encounter detection, flee logic, door transitions.

Functions that detect and handle battles, dialogue, and map transitions
that occur during or after overworld navigation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.nav_constants import (
    _BATTLE_OVER,
    _FAINT_STATES,
    DIRECTIONAL_WARP,
    DOOR_ACTIVATION,
    DOOR_POLL_FRAMES,
    DOOR_TRANSITION_POLLS,
    HOLD_FRAMES,
    POST_BATTLE_SETTLE,
    POST_NAV_MAX_POLLS,
    POST_NAV_POLL_FRAMES,
    SETTLE_FRAMES,
    WAIT_FRAMES,
    _pos_with_map,
    _read_position,
)
from renegade_mcp.battle import format_battle, read_battle
from renegade_mcp.dialogue import (
    CTX_RUNNING, CTX_WAITING,
    _find_script_manager, _read_context_state, _read_script_state,
    advance_dialogue, read_dialogue,
)
from renegade_mcp.turn import _wait_for_action_prompt

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def _flee_wild_battle(emu: EmulatorClient) -> dict[str, Any]:
    """Flee a wild battle, retrying on failure. Returns success/failure info.

    Mirrors auto_grind._run_battle pattern but simplified for navigation use.
    """
    from renegade_mcp.turn import battle_turn as _battle_turn

    max_attempts = 10
    for attempt in range(max_attempts):
        result = _battle_turn(emu, run=True)
        state = result.get("final_state", "")

        if state in _BATTLE_OVER:
            return {"success": True, "attempts": attempt + 1}

        if state == "WAIT_FOR_ACTION":
            # Escape failed, enemy got a free turn — retry
            continue

        if state in _FAINT_STATES:
            return {"success": False, "reason": "fainted", "state": state}

        return {"success": False, "reason": f"unexpected state: {state}"}

    return {"success": False, "reason": "max flee attempts reached"}


def _try_flee_encounter(
    emu: EmulatorClient, encounter: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """If encounter is a wild battle, flee it and return to overworld.

    Returns (encounter_or_none, flee_entry_or_none).
    - Wild battle fled successfully: (None, flee_log_entry) — encounter cleared.
    - Wild battle flee failed: (original encounter, flee_log_entry with failure).
    - Trainer battle or dialogue: (original encounter, None) — unchanged.
    - No encounter: (None, None).
    """
    if encounter is None:
        return None, None

    if encounter.get("encounter") != "battle":
        # Dialogue/cutscene — pass through unchanged
        return encounter, None

    if encounter.get("dialogue"):
        # Trainer battle — can't flee, pass through
        return encounter, None

    # Wild battle — extract species and flee
    species = "unknown"
    for b in (encounter.get("battle_state") or []):
        if b.get("side") == "enemy":
            species = b.get("species", "unknown")
            break

    flee_result = _flee_wild_battle(emu)
    flee_entry: dict[str, Any] = {"type": "wild", "species": species}

    if flee_result["success"]:
        flee_entry["fled"] = True
        flee_entry["attempts"] = flee_result["attempts"]
        emu.advance_frames(POST_BATTLE_SETTLE)
        return None, flee_entry
    else:
        flee_entry["fled"] = False
        flee_entry["reason"] = flee_result["reason"]
        return encounter, flee_entry


def _find_hatching_egg_slot(emu: EmulatorClient) -> int | None:
    """Return the party slot index holding an egg (if any), else None.

    Used to distinguish the game's egg-hatch "Oh?" prompt from a regular
    NPC dialogue that happens to say "Oh?".  Multiple eggs in the party
    is rare; we return the first one encountered.
    """
    from renegade_mcp.party import read_party

    result = read_party(emu)
    members = result if isinstance(result, list) else result.get("party", [])
    for member in members:
        if member.get("is_egg"):
            return member.get("slot")
    return None


def _post_nav_check(emu: EmulatorClient) -> dict[str, Any] | None:
    """Check for battle encounter or overworld dialogue after navigation.

    Polls up to 300 frames (15 at a time). On each iteration, checks
    read_battle and read_dialogue BEFORE advancing, so frame 0 is checked.

    If a battle is detected, advances through the transition to the first
    action prompt (ability announcements, send-out text, etc.) and returns
    the battle state, intro log, and prompt info — ready for battle_turn.

    If overworld dialogue is detected, returns the dialogue text.

    Returns None if neither is detected within 300 frames.
    """
    from renegade_mcp.phase_timer import phase

    for _ in range(POST_NAV_MAX_POLLS):
        # Check for battle encounter
        with phase("npc_read_battle"):
            battlers = read_battle(emu)
        if battlers:
            with phase("npc_wait_action_prompt"):
                prompt_result = _wait_for_action_prompt(emu)
            with phase("npc_read_battle"):
                battle_state = read_battle(emu)
            result: dict[str, Any] = {
                "encounter": "battle",
                "battle_log": prompt_result["log"],
                "battle_state": battle_state,
                "battle_state_formatted": format_battle(battle_state),
                "prompt_ready": prompt_result["ready"],
            }
            if prompt_result.get("prompt_type"):
                result["prompt_type"] = prompt_result["prompt_type"]
            if prompt_result.get("state"):
                result["final_state"] = prompt_result["state"]
            return result

        # Check for overworld dialogue
        with phase("npc_read_dialogue"):
            dialogue = read_dialogue(emu, region="overworld")
        if dialogue["region"] != "none":
            # Validate: text buffer can contain stale data during NPC approach
            # animations. Only trust it when msgBox=1 (dialogue box visible).
            with phase("npc_script_state"):
                mgr = _find_script_manager(emu)
                if mgr is not None:
                    ss = _read_script_state(emu, mgr)
            if mgr is not None:
                if not ss["is_msg_box_open"]:
                    # msgBox=0: text is pre-positioned, not yet displayed.
                    # If a script is running, keep polling — dialogue will
                    # appear once the approach animation finishes.
                    if ss["ctx0_ptr"]:
                        with phase("npc_script_state"):
                            ctx0 = _read_context_state(emu, ss["ctx0_ptr"])
                        if ctx0["state"] in (CTX_RUNNING, CTX_WAITING):
                            with phase("npc_poll_advance"):
                                emu.advance_frames(POST_NAV_POLL_FRAMES)
                            continue
                    # No active script — stale buffer data, skip.
                    with phase("npc_poll_advance"):
                        emu.advance_frames(POST_NAV_POLL_FRAMES)
                    continue

            # msgBox is open — real dialogue. If the text is the egg-hatch
            # trigger "Oh?" and the party has an egg, capture the hatching
            # slot now — by the time advance_dialogue finishes (~60 sec for
            # the full hatch animation), is_egg will already have flipped.
            egg_slot_before = None
            if dialogue.get("text") == "Oh?":
                egg_slot_before = _find_hatching_egg_slot(emu)

            with phase("npc_advance_dialogue"):
                adv_result = advance_dialogue(emu)

            # After dialogue, check if it transitioned into a battle
            with phase("npc_read_battle"):
                battlers = read_battle(emu)
            if battlers:
                with phase("npc_wait_action_prompt"):
                    prompt_result = _wait_for_action_prompt(emu)
                with phase("npc_read_battle"):
                    battle_state = read_battle(emu)
                result: dict[str, Any] = {
                    "encounter": "battle",
                    "dialogue": adv_result,
                    "battle_log": prompt_result["log"],
                    "battle_state": battle_state,
                    "battle_state_formatted": format_battle(battle_state),
                    "prompt_ready": prompt_result["ready"],
                }
                if prompt_result.get("prompt_type"):
                    result["prompt_type"] = prompt_result["prompt_type"]
                if prompt_result.get("state"):
                    result["final_state"] = prompt_result["state"]
                return result

            # Classify egg hatch: captured before advance_dialogue because
            # the egg flag flips during the hatch animation.  Without the
            # egg check we'd misclassify any NPC "Oh?" as a hatch.
            if egg_slot_before is not None:
                return {
                    "encounter": "egg_hatch",
                    "hatching_slot": egg_slot_before,
                    "dialogue": adv_result,
                }

            return {
                "encounter": "dialogue",
                "dialogue": adv_result,
            }

        with phase("npc_poll_advance"):
            emu.advance_frames(POST_NAV_POLL_FRAMES)

    return None


def _handle_door_transition(
    emu: EmulatorClient, behavior: int, original_map: int,
) -> dict[str, Any] | None:
    """Handle a door/warp tile after navigation reaches it.

    For walk-into doors (0x69, 0x6E), the warp may have already triggered.
    For step-on doors (0x65, 0x5F, 0x5E), presses the activation direction.
    For directional warps (0x62, 0x63, etc.), walks in the required direction.
    Waits for map transition to complete and returns new position info.

    Returns dict with new map info, or None if no transition occurred.
    """
    activation = DOOR_ACTIVATION.get(behavior)
    if activation is None:
        activation = DIRECTIONAL_WARP.get(behavior)

    # For doors/warps that need a direction press, do it now
    if activation is not None:
        emu.advance_frames(HOLD_FRAMES, buttons=[activation])
        emu.advance_frames(WAIT_FRAMES)

    # Wait for map transition — map_id should change
    from renegade_mcp.addresses import addr as _addr
    pos_base = _addr("PLAYER_POS_BASE")
    result = emu.advance_frames_until(
        max_frames=DOOR_TRANSITION_POLLS * DOOR_POLL_FRAMES,
        conditions=[{"type": "changed", "address": pos_base, "size": "long"}],
        poll_interval=DOOR_POLL_FRAMES,
    )
    if result["triggered"]:
        # Transition happened — settle and return new position
        emu.advance_frames(SETTLE_FRAMES)
        final_map, final_x, final_y = _read_position(emu)
        return {
            "door_entered": True,
            "door_behavior": f"0x{behavior:02X}",
            "new_map": final_map,
            "new_position": _pos_with_map(final_x, final_y, final_map),
        }

    return None
