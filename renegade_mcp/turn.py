"""Automated battle turn: action selection + poll + state detection.

Handles all battle states:
- Normal turns: FIGHT + move or POKEMON + switch
- Faint recovery: wild (flee or switch) and trainer (forced switch)
- Trainer switch prompts: swap Pokemon or keep battling
- Level-up, move learning, battle end detection
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.battle import format_battle, read_battle
from renegade_mcp.party import read_party
from renegade_mcp.battle_tracker import (
    _tracker,
    _classify_stop,
    _scan_for_new_text,
    POLL_FRAMES,
    SCAN_SIZE,
    SCAN_START,
)

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Battle action screen (bottom screen) ──
FIGHT_XY = (128, 90)
POKEMON_XY = (210, 170)  # Bottom-right of action screen (green button)

# Move selection screen (bottom screen, after tapping FIGHT)
MOVE_XY = [
    (70, 50),    # Move 0 — top-left
    (190, 50),   # Move 1 — top-right
    (70, 110),   # Move 2 — bottom-left
    (190, 110),  # Move 3 — bottom-right
]

# ── Battle party screen (touch targets, 2-column grid) ──
# Layout:  0  1       Row y values estimated from 2-Pokemon test;
#          2  3       rows 1-2 need calibration with 4+ Pokemon.
#          4  5
PARTY_TOUCH_XY = [
    (65, 30),    # Slot 0 — top-left
    (190, 30),   # Slot 1 — top-right
    (65, 80),    # Slot 2 — mid-left
    (190, 80),   # Slot 3 — mid-right
    (65, 130),   # Slot 4 — bottom-left
    (190, 130),  # Slot 5 — bottom-right
]  # Calibrated via gameplay with 5-Pokemon party
SHIFT_XY = (128, 100)  # "SHIFT" confirmation button

# ── Faint/switch prompt buttons (bottom screen) ──
PROMPT_YES_XY = (128, 67)     # "Use next Pokemon" / "Switch Pokemon" (red)
PROMPT_NO_XY = (128, 127)     # "Flee" / "Keep battling" (blue)

# ── Move learn prompt buttons (bottom screen) ──
GIVE_UP_XY = (128, 75)        # "Give up on [Move]!" (red, top)
DONT_GIVE_UP_XY = (128, 145)  # "Don't give up on [Move]!" (green, bottom)
FORGET_A_MOVE_XY = (128, 75)  # "Forget a move!" (red, top)
FORGET_BTN_XY = (128, 178)    # "FORGET" button on move detail view

# Move forget screen grid (shifted down from battle MOVE_XY due to Pokemon info header)
FORGET_MOVE_XY = [
    (70, 75),    # Move 0 — top-left
    (190, 75),   # Move 1 — top-right
    (70, 125),   # Move 2 — bottom-left
    (190, 125),  # Move 3 — bottom-right
]

# Battle struct address for garbage detection
BATTLE_BASE = 0x022C5774
BATTLE_SLOT_SIZE = 0xC0

# Post-timeout recovery: press B to advance through stat screens / text
RECOVERY_PRESSES = 8
RECOVERY_WAIT = 300  # frames between B presses (~5 seconds per press)

# Timing
ACTION_SETTLE = 120   # frames before first tap (covers send-out animations)
PROMPT_SETTLE = 300   # frames before tapping switch/faint prompts (game delays control handoff)
TAP_WAIT = 60         # frames between sequential taps
DPAD_WAIT = 30        # frames between D-pad presses
ACTION_PROMPT_MAX_POLLS = 120  # polls waiting for "What will X do?" (~30 sec)
TEXT_ADVANCE_WAIT = 120  # frames between B presses during text advancement


# ── Helpers ──

def _is_battle_over(emu: EmulatorClient) -> bool:
    """Check if battle struct contains garbage data (= back in overworld)."""
    raw = emu.read_memory_range(BATTLE_BASE, size="byte", count=BATTLE_SLOT_SIZE)
    data = bytes(raw)

    species = struct.unpack_from("<H", data, 0x00)[0]
    level = data[0x34]
    cur_hp = struct.unpack_from("<H", data, 0x4C)[0]
    max_hp = struct.unpack_from("<H", data, 0x50)[0]

    if species == 0 or species > 493:
        return True
    if level == 0 or level > 100:
        return True
    if max_hp == 0 or max_hp > 999:
        return True
    if cur_hp > max_hp:
        return True
    return False


def _get_player_hp(emu: EmulatorClient) -> int:
    """Read player's current HP from battle struct slot 0."""
    raw = emu.read_memory_range(BATTLE_BASE + 0x4C, size="long", count=1)
    return raw[0] if raw else -1


def _log_has(log: list[dict], text: str) -> bool:
    """Check if any log entry contains the given text."""
    return any(text in e.get("text", "") for e in log)


def _classify_prompt(text: str) -> str:
    """Classify a WAIT_FOR_ACTION prompt by its text content."""
    if "Use next" in text:
        return "FAINT_SWITCH"
    if "Will you switch" in text:
        return "SWITCH_PROMPT"
    if "give up on" in text or "forget another move" in text:
        return "MOVE_LEARN"
    return "ACTION"


def _extract_new_move_name(log: list[dict]) -> str | None:
    """Extract the new move name from a LEVEL_UP/MOVE_LEARN log.

    Scans log entries between 'grew to' and the move-learn prompt text,
    matching against known move names from the ROM.
    """
    from renegade_mcp.data import move_names
    known_moves = set(move_names().values())

    in_range = False
    candidate = None
    for entry in log:
        text = entry.get("text", "").strip()
        if "grew to" in text:
            in_range = True
            continue
        if "give up on" in text or "forget another move" in text:
            break
        if in_range and text in known_moves:
            candidate = text
    return candidate


def _advance_text(emu: EmulatorClient, presses: int = 1, wait: int = TEXT_ADVANCE_WAIT) -> None:
    """Press B to advance through dialogue text."""
    for _ in range(presses):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(wait)


# ── Prompt detection ──

def _wait_for_action_prompt(emu: EmulatorClient) -> dict[str, Any]:
    """Wait for a battle prompt that requires player input.

    Detects and classifies the prompt type:
    - ACTION: normal "What will X do?" turn prompt
    - FAINT_SWITCH: wild battle faint, "Use next Pokemon?" (can flee)
    - SWITCH_PROMPT: trainer sending next Pokemon, "Will you switch?"
    - MOVE_LEARN: move learning prompt, "give up on learning?"
    - FAINT_FORCED: trainer battle faint, party grid shown (no text prompt)

    On turns 2+, the prompt is already in the text buffer and returns
    immediately. On turn 1, polls through send-out animations (~30 sec max).
    """
    log: list[dict] = []
    prev_text: str | None = None

    for _ in range(ACTION_PROMPT_MAX_POLLS):
        raw_bytes = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
        if raw_bytes:
            data = bytes(raw_bytes)
            results = _scan_for_new_text(data, SCAN_START, {})

            # Check every active marker for the action prompt stop type.
            # Multiple WAIT_FOR_ACTION texts may coexist (stale "What will X do?"
            # alongside new "Will you switch?" or "Use next Pokemon?").
            # Prefer specific prompts over generic ACTION.
            action_candidates: list[tuple[str, str]] = []
            for _, text, vals, _ in results:
                if _classify_stop(vals) == "WAIT_FOR_ACTION":
                    action_candidates.append((text, _classify_prompt(text)))

            if action_candidates:
                # Return the most specific prompt (non-ACTION first)
                for cand_text, cand_type in action_candidates:
                    if cand_type != "ACTION":
                        if cand_text != prev_text:
                            log.append({"text": cand_text, "stop": "WAIT_FOR_ACTION"})
                        return {"ready": True, "log": log, "prompt_type": cand_type}
                # All ACTION — return the first
                cand_text, cand_type = action_candidates[0]
                if cand_text != prev_text:
                    log.append({"text": cand_text, "stop": "WAIT_FOR_ACTION"})
                return {"ready": True, "log": log, "prompt_type": cand_type}

            # No action prompt yet — log the best result and advance
            if results:
                _, text, vals, _ = results[0]
                stop = _classify_stop(vals)

                if text != prev_text:
                    prev_text = text
                    log.append({"text": text, "stop": stop})

                # Dismiss text that waits for B (ability announcements, etc.)
                if stop == "WAIT_FOR_INPUT":
                    emu.press_buttons(["b"], frames=8)
                    emu.advance_frames(30)
                    continue

        emu.advance_frames(POLL_FRAMES)

    # Timed out — check for forced switch (trainer faint, party grid showing)
    if not _is_battle_over(emu) and _get_player_hp(emu) == 0:
        return {"ready": True, "log": log, "prompt_type": "FAINT_FORCED"}

    state = "BATTLE_ENDED" if _is_battle_over(emu) else "NO_ACTION_PROMPT"
    return {"ready": False, "log": log, "state": state}


# ── Action flows ──

def _fight_flow(emu: EmulatorClient, move_index: int) -> None:
    """Tap FIGHT, then tap the selected move."""
    emu.tap_touch_screen(FIGHT_XY[0], FIGHT_XY[1], frames=8)
    emu.advance_frames(TAP_WAIT)

    mx, my = MOVE_XY[move_index]
    emu.tap_touch_screen(mx, my, frames=8)


def _switch_flow(emu: EmulatorClient, switch_to: int) -> None:
    """Tap POKEMON, tap party slot, tap SHIFT to confirm (normal voluntary switch)."""
    emu.tap_touch_screen(POKEMON_XY[0], POKEMON_XY[1], frames=8)
    emu.advance_frames(ACTION_SETTLE)

    px, py = PARTY_TOUCH_XY[switch_to]
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    emu.tap_touch_screen(SHIFT_XY[0], SHIFT_XY[1], frames=8)


def _prompt_switch_flow(emu: EmulatorClient, switch_to: int) -> None:
    """Handle 'Use next Pokemon?' or 'Switch Pokemon?' — tap yes, select, SHIFT."""
    # Tap the "yes" button (Use next Pokemon / Switch Pokemon)
    emu.tap_touch_screen(PROMPT_YES_XY[0], PROMPT_YES_XY[1], frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # Tap party slot → opens detail view
    px, py = PARTY_TOUCH_XY[switch_to]
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # Tap SHIFT to confirm
    emu.tap_touch_screen(SHIFT_XY[0], SHIFT_XY[1], frames=8)


def _forced_switch_flow(emu: EmulatorClient, switch_to: int) -> None:
    """Handle trainer faint — already on party grid, select and SHIFT."""
    px, py = PARTY_TOUCH_XY[switch_to]
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    emu.tap_touch_screen(SHIFT_XY[0], SHIFT_XY[1], frames=8)


def _decline_flow(emu: EmulatorClient) -> None:
    """Tap 'Flee' (wild faint) or 'Keep battling' (switch prompt)."""
    emu.tap_touch_screen(PROMPT_NO_XY[0], PROMPT_NO_XY[1], frames=8)


def _skip_move_learn_flow(emu: EmulatorClient) -> None:
    """Tap 'Give up on [Move]!' to skip learning the new move."""
    emu.tap_touch_screen(GIVE_UP_XY[0], GIVE_UP_XY[1], frames=8)
    emu.advance_frames(TAP_WAIT)
    # Advance through "did not learn [Move]" text
    _advance_text(emu, presses=3, wait=180)


def _learn_move_flow(emu: EmulatorClient, forget_index: int) -> None:
    """Navigate from 'give up?' prompt through move selection to learn the new move.

    Steps: Don't give up → text → Forget a move! → move grid → tap slot → FORGET
    """
    # 1. Tap "Don't give up on [Move]!" (green button)
    emu.tap_touch_screen(DONT_GIVE_UP_XY[0], DONT_GIVE_UP_XY[1], frames=8)
    emu.advance_frames(TAP_WAIT)

    # 2. Advance through "wants to learn" / "can't learn more than four" text
    #    Two text boxes, each needs B to complete scroll + B to advance.
    #    Stop before the "Forget a move?" touch prompt appears.
    _advance_text(emu, presses=4, wait=90)
    emu.advance_frames(300)  # Wait for "Forget a move?" touch prompt

    # 3. Tap "Forget a move!" (red button)
    emu.tap_touch_screen(FORGET_A_MOVE_XY[0], FORGET_A_MOVE_XY[1], frames=8)
    emu.advance_frames(TAP_WAIT)

    # 4. Advance through "Which move should be forgotten?" text
    _advance_text(emu, presses=2, wait=120)
    emu.advance_frames(180)  # Wait for move grid to render

    # 5. Tap the target move slot on the grid
    mx, my = FORGET_MOVE_XY[forget_index]
    emu.tap_touch_screen(mx, my, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # 6. Tap FORGET on the detail view
    emu.tap_touch_screen(FORGET_BTN_XY[0], FORGET_BTN_XY[1], frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # 7. Advance through "1, 2, and... Poof!" / "forgot [old]" / "learned [new]" text
    _advance_text(emu, presses=6, wait=180)


def _poll_after_action(emu: EmulatorClient, prompt_log: list[dict]) -> dict[str, Any]:
    """Re-init tracker and poll for the next battle state after an action."""
    _tracker.init(emu)
    result = _tracker.poll(emu, auto_press=True)
    # Classify on poll-only log first (avoids stale prompt text contamination)
    result["final_state"] = _classify_final_state(emu, result)
    # Then prepend prompt log for complete display
    result["log"] = prompt_log + result.get("log", [])
    return result


# ── Main entry point ──

def battle_turn(
    emu: EmulatorClient, move_index: int = -1, switch_to: int = -1,
    forget_move: int = -2,
) -> dict[str, Any]:
    """Execute a battle action: move, switch, flee, keep battling, or handle move learning.

    The tool detects the current game state and validates parameters:

    Normal turn (ACTION — "What will X do?"):
        move_index (0-3): Use FIGHT and select a move.
        switch_to (1-5): Use POKEMON to switch voluntarily.

    Faint in wild battle (FAINT_SWITCH — "Use next Pokemon?"):
        switch_to (1-5): Send in a replacement.
        No args / switch_to=-1: Flee the battle.

    Faint in trainer battle (FAINT_FORCED — party grid shown):
        switch_to (1-5): Send in a replacement (required).

    Trainer switch prompt (SWITCH_PROMPT — "Will you switch?"):
        switch_to (1-5): Switch to a different Pokemon.
        No args / switch_to=-1: Keep battling with current Pokemon.

    Move learning (MOVE_LEARN — "give up on learning?"):
        forget_move (0-3): Forget that move slot and learn the new move.
        forget_move=-1: Skip learning the new move.
        No forget_move: Return MOVE_LEARN state with move info for decision.

    Returns dict with: log, final_state, formatted, battle_state.
    """
    has_move = move_index >= 0
    has_switch = switch_to >= 0
    has_forget = forget_move >= -1  # -1 = skip, 0-3 = forget slot

    # 1. Detect current game state
    prompt = _wait_for_action_prompt(emu)

    if not prompt["ready"]:
        result: dict[str, Any] = {
            "log": prompt["log"],
            "final_state": prompt.get("state", "NO_ACTION_PROMPT"),
        }
        result["formatted"] = _reformat(result)
        battlers = read_battle(emu)
        result["battle_state"] = battlers
        result["formatted"] += "\n\n" + format_battle(battlers)
        return result

    pt = prompt["prompt_type"]

    # 2. Validate parameters for current state
    if pt == "ACTION":
        if has_forget:
            return {"error": "Not at a move learning prompt. Use move_index or switch_to."}
        if has_move and has_switch:
            return {"error": "Specify move_index OR switch_to, not both."}
        if not has_move and not has_switch:
            return {"error": "Must specify move_index (0-3) or switch_to (1-5)."}
        if has_move and move_index > 3:
            return {"error": f"move_index must be 0-3, got {move_index}"}
        if has_switch and switch_to == 0:
            return {"error": "switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."}
        if has_switch and switch_to > 5:
            return {"error": f"switch_to must be 1-5, got {switch_to}"}
    elif pt in ("FAINT_SWITCH", "SWITCH_PROMPT"):
        if has_forget:
            return {"error": f"Not at a move learning prompt. Currently in {pt} state."}
        if has_move:
            return {"error": f"Can't use a move in {pt} state. Use switch_to (1-5), or omit to {'flee' if pt == 'FAINT_SWITCH' else 'keep battling'}."}
        if has_switch and switch_to == 0:
            return {"error": "switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."}
        if has_switch and switch_to > 5:
            return {"error": f"switch_to must be 1-5, got {switch_to}"}
    elif pt == "FAINT_FORCED":
        if has_forget:
            return {"error": "Not at a move learning prompt. Your Pokemon fainted — use switch_to."}
        if has_move:
            return {"error": "Can't use a move — your Pokemon fainted. Use switch_to (1-5) to send a replacement."}
        if not has_switch:
            return {"error": "Must switch in a trainer battle — specify switch_to (1-5)."}
        if has_switch and switch_to == 0:
            return {"error": "switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."}
        if switch_to > 5:
            return {"error": f"switch_to must be 1-5, got {switch_to}"}
    elif pt == "MOVE_LEARN":
        if has_move or has_switch:
            return {"error": "At move learning prompt. Use forget_move (0-3) to forget a move, or forget_move=-1 to skip."}
        if has_forget and forget_move > 3:
            return {"error": f"forget_move must be -1 (skip) or 0-3, got {forget_move}"}

    # 3. Execute the appropriate flow
    if pt == "ACTION":
        result = _execute_action(emu, prompt, move_index, switch_to, has_move)
    elif pt == "FAINT_SWITCH":
        result = _execute_faint_switch(emu, prompt, switch_to, has_switch)
    elif pt == "FAINT_FORCED":
        result = _execute_forced_switch(emu, prompt, switch_to)
    elif pt == "SWITCH_PROMPT":
        result = _execute_switch_prompt(emu, prompt, switch_to, has_switch)
    elif pt == "MOVE_LEARN":
        result = _execute_move_learn(emu, prompt, forget_move, has_forget)
    else:
        result = {"log": prompt["log"], "final_state": "NO_ACTION_PROMPT"}

    # 4. Enrich MOVE_LEARN results with move info
    if result["final_state"] == "MOVE_LEARN":
        _enrich_move_learn_result(result, emu)

    # 4.5. Add party order for switch states
    if result["final_state"] in ("SWITCH_PROMPT", "FAINT_SWITCH", "FAINT_FORCED"):
        _enrich_switch_result(result, emu)

    # 5. Format and append battle state
    result["formatted"] = _reformat(result)
    battlers = read_battle(emu)
    result["battle_state"] = battlers
    result["formatted"] += "\n\n" + format_battle(battlers)
    return result


# ── State-specific execution ──

def _execute_action(
    emu: EmulatorClient, prompt: dict, move_index: int, switch_to: int, has_move: bool,
) -> dict[str, Any]:
    """Normal turn: FIGHT + move or POKEMON + switch."""
    _tracker.init(emu)
    emu.advance_frames(ACTION_SETTLE)

    if has_move:
        _fight_flow(emu, move_index)
    else:
        _switch_flow(emu, switch_to)

    result = _tracker.poll(emu, auto_press=True)
    # Classify on poll-only log (avoids stale prompt text contamination)
    result["final_state"] = _classify_final_state(emu, result)
    result["log"] = prompt["log"] + result.get("log", [])

    if result["final_state"] == "TIMEOUT" and _log_has(result.get("log", []), "grew to"):
        result = _recover_from_level_up(emu, result)

    return result


def _execute_faint_switch(
    emu: EmulatorClient, prompt: dict, switch_to: int, has_switch: bool,
) -> dict[str, Any]:
    """Wild faint: send replacement or flee."""
    emu.advance_frames(PROMPT_SETTLE)
    if has_switch:
        _prompt_switch_flow(emu, switch_to)
        return _poll_after_action(emu, prompt["log"])
    else:
        # Flee
        _decline_flow(emu)
        emu.advance_frames(300)  # flee animation
        result: dict[str, Any] = {"log": prompt["log"]}
        if _is_battle_over(emu):
            result["final_state"] = "BATTLE_ENDED"
        else:
            # Flee might need more time or might have failed
            emu.advance_frames(300)
            result["final_state"] = "BATTLE_ENDED" if _is_battle_over(emu) else "WAIT_FOR_ACTION"
        return result


def _execute_forced_switch(
    emu: EmulatorClient, prompt: dict, switch_to: int,
) -> dict[str, Any]:
    """Trainer faint: must send replacement."""
    emu.advance_frames(PROMPT_SETTLE)
    _forced_switch_flow(emu, switch_to)
    return _poll_after_action(emu, prompt["log"])


def _execute_switch_prompt(
    emu: EmulatorClient, prompt: dict, switch_to: int, has_switch: bool,
) -> dict[str, Any]:
    """Trainer switch prompt: swap Pokemon or keep battling."""
    emu.advance_frames(PROMPT_SETTLE)
    if has_switch:
        _prompt_switch_flow(emu, switch_to)
    else:
        _decline_flow(emu)
    return _poll_after_action(emu, prompt["log"])


def _execute_move_learn(
    emu: EmulatorClient, prompt: dict, forget_move: int, has_forget: bool,
) -> dict[str, Any]:
    """Handle move learning prompt: skip, learn, or return info for decision."""
    if not has_forget:
        # No decision yet — return MOVE_LEARN state for the caller to decide
        return {"log": prompt["log"], "final_state": "MOVE_LEARN"}

    if forget_move == -1:
        _skip_move_learn_flow(emu)
    else:
        _learn_move_flow(emu, forget_move)

    return _poll_after_action(emu, prompt["log"])


# ── Post-action processing ──

def _recover_from_level_up(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any]:
    """After level-up causes a timeout, press B to advance through stat screens."""
    for _ in range(RECOVERY_PRESSES):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(RECOVERY_WAIT)

        _tracker.init(emu)
        poll = _tracker.poll(emu, auto_press=True)

        if poll["final_state"] == "WAIT_FOR_ACTION":
            result["log"].extend(poll.get("log", []))
            result["final_state"] = _classify_final_state(emu, poll)
            return result

        if poll["final_state"] != "NO_TEXT":
            result["log"].extend(poll.get("log", []))

        if _is_battle_over(emu):
            result["final_state"] = "BATTLE_ENDED"
            return result

    result["final_state"] = "LEVEL_UP"
    return result


def _enrich_switch_result(result: dict[str, Any], emu: EmulatorClient) -> None:
    """Add current party order to switch state results for informed slot selection.

    Only includes slot index, species, and level — NOT HP, since party HP data
    is stale during battle (doesn't reflect in-battle damage).
    """
    party = read_party(emu)
    result["party"] = [
        {"slot": p["slot"], "name": p["name"], "level": p["level"]}
        for p in party
    ]


def _enrich_move_learn_result(result: dict[str, Any], emu: EmulatorClient) -> None:
    """Add move_to_learn and current_moves info to a MOVE_LEARN result."""
    move_name = _extract_new_move_name(result.get("log", []))
    if move_name:
        result["move_to_learn"] = move_name

    # Get current moves from battle state
    battlers = read_battle(emu)
    for b in battlers:
        if b.get("side") == "player":
            result["current_moves"] = [
                {"slot": i, "name": m["name"], "pp": m["pp"]}
                for i, m in enumerate(b.get("moves", []))
            ]
            break


def _classify_final_state(emu: EmulatorClient, result: dict[str, Any]) -> str:
    """Refine the raw poll state into a more specific battle state."""
    raw_state = result.get("final_state", "")

    if raw_state == "WAIT_FOR_ACTION":
        for entry in result.get("log", []):
            text = entry.get("text", "")
            if "Use next" in text:
                return "FAINT_SWITCH"
            if "Will you switch" in text:
                return "SWITCH_PROMPT"
            if "give up on" in text or "forget another move" in text:
                return "MOVE_LEARN"
        return "WAIT_FOR_ACTION"

    if raw_state in ("TIMEOUT", "NO_TEXT"):
        if _is_battle_over(emu):
            return "BATTLE_ENDED"
        # Trainer faint: no text prompt, player HP = 0, battle still active
        if _log_has(result.get("log", []), "fainted") and _get_player_hp(emu) == 0:
            return "FAINT_FORCED"

    return raw_state


def _reformat(result: dict[str, Any]) -> str:
    """Reformat the log with the updated final state."""
    lines = ["=== Battle Log ==="]
    for entry in result.get("log", []):
        text = entry["text"].replace("\n", " / ")
        for code in ("[FFFE]", "[VAR]"):
            while code in text:
                text = text[: text.index(code)].rstrip()
        lines.append(f"  {text}")

    state = result["final_state"]

    # Special formatting for MOVE_LEARN
    if state == "MOVE_LEARN" and "move_to_learn" in result:
        move = result["move_to_learn"]
        lines.append(f"\nState: MOVE_LEARN — wants to learn {move}")
        if "current_moves" in result:
            lines.append("  Current moves:")
            for m in result["current_moves"]:
                lines.append(f"    {m['slot']}: {m['name']} (PP {m['pp']})")
        lines.append(f"  Use battle_turn(forget_move=N) to forget move N and learn {move}")
        lines.append(f"  Use battle_turn(forget_move=-1) to skip learning {move}")
        return "\n".join(lines)

    state_labels = {
        "WAIT_FOR_ACTION": "Your turn — select next move",
        "SWITCH_PROMPT": "Opponent sending next Pokemon — use battle_turn(switch_to=N) to swap, or battle_turn() to keep battling",
        "FAINT_SWITCH": "Your Pokemon fainted (wild) — use battle_turn(switch_to=N) to send replacement, or battle_turn() to flee",
        "FAINT_FORCED": "Your Pokemon fainted (trainer) — use battle_turn(switch_to=N) to send replacement",
        "BATTLE_ENDED": "Battle is over — back in overworld",
        "MOVE_LEARN": "Move learning prompt — use battle_turn(forget_move=N) or battle_turn(forget_move=-1)",
        "LEVEL_UP": "Level up with move learning — handle manually",
        "CAUGHT": "Pokemon caught! Back in overworld",
        "NOT_CAUGHT": "Ball failed — back at action prompt",
        "TIMEOUT": "Polling timed out — check game state manually",
        "NO_TEXT": "No battle text detected — action may not have registered",
        "NO_ACTION_PROMPT": "No action prompt detected — game may need manual input to proceed",
    }
    label = state_labels.get(state, state)
    lines.append(f"\nState: {state} — {label}")

    # Show party order for switch states (slot + species only, no HP — it's stale during battle)
    if state in ("SWITCH_PROMPT", "FAINT_SWITCH", "FAINT_FORCED") and "party" in result:
        lines.append("  Party:")
        for p in result["party"]:
            lines.append(f"    {p['slot']}. {p['name']} Lv{p['level']}")

    return "\n".join(lines)
