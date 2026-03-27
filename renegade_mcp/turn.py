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
    (65, 80),    # Slot 2 — mid-left (estimated)
    (190, 80),   # Slot 3 — mid-right (estimated)
    (65, 130),   # Slot 4 — bottom-left (estimated)
    (190, 130),  # Slot 5 — bottom-right (estimated)
]
SHIFT_XY = (128, 100)  # "SHIFT" confirmation button

# ── Faint/switch prompt buttons (bottom screen) ──
PROMPT_YES_XY = (128, 95)     # "Use next Pokemon" / "Switch Pokemon" (red)
PROMPT_NO_XY = (128, 150)     # "Flee" / "Keep battling" (blue)

# Battle struct address for garbage detection
BATTLE_BASE = 0x022C5774
BATTLE_SLOT_SIZE = 0xC0

# Post-timeout recovery: press B to advance through stat screens / text
RECOVERY_PRESSES = 8
RECOVERY_WAIT = 300  # frames between B presses (~5 seconds per press)

# Timing
ACTION_SETTLE = 120   # frames before first tap (covers send-out animations)
TAP_WAIT = 60         # frames between sequential taps
DPAD_WAIT = 30        # frames between D-pad presses
ACTION_PROMPT_MAX_POLLS = 120  # polls waiting for "What will X do?" (~30 sec)


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
    return "ACTION"


# ── Prompt detection ──

def _wait_for_action_prompt(emu: EmulatorClient) -> dict[str, Any]:
    """Wait for a battle prompt that requires player input.

    Detects and classifies the prompt type:
    - ACTION: normal "What will X do?" turn prompt
    - FAINT_SWITCH: wild battle faint, "Use next Pokemon?" (can flee)
    - SWITCH_PROMPT: trainer sending next Pokemon, "Will you switch?"
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


def _poll_after_action(emu: EmulatorClient, prompt_log: list[dict]) -> dict[str, Any]:
    """Re-init tracker and poll for the next battle state after an action."""
    _tracker.init(emu)
    result = _tracker.poll(emu, auto_press=True)
    result["log"] = prompt_log + result.get("log", [])
    result["final_state"] = _classify_final_state(emu, result)
    return result


# ── Main entry point ──

def battle_turn(
    emu: EmulatorClient, move_index: int = -1, switch_to: int = -1,
) -> dict[str, Any]:
    """Execute a battle action: move, switch, flee, or keep battling.

    The tool detects the current game state and validates parameters:

    Normal turn (ACTION — "What will X do?"):
        move_index (0-3): Use FIGHT and select a move.
        switch_to (0-5): Use POKEMON to switch voluntarily.

    Faint in wild battle (FAINT_SWITCH — "Use next Pokemon?"):
        switch_to (0-5): Send in a replacement.
        No args / switch_to=-1: Flee the battle.

    Faint in trainer battle (FAINT_FORCED — party grid shown):
        switch_to (0-5): Send in a replacement (required).

    Trainer switch prompt (SWITCH_PROMPT — "Will you switch?"):
        switch_to (0-5): Switch to a different Pokemon.
        No args / switch_to=-1: Keep battling with current Pokemon.

    Returns dict with: log, final_state, formatted, battle_state.
    """
    has_move = move_index >= 0
    has_switch = switch_to >= 0

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
        if has_move and has_switch:
            return {"error": "Specify move_index OR switch_to, not both."}
        if not has_move and not has_switch:
            return {"error": "Must specify move_index (0-3) or switch_to (0-5)."}
        if has_move and move_index > 3:
            return {"error": f"move_index must be 0-3, got {move_index}"}
        if has_switch and switch_to > 5:
            return {"error": f"switch_to must be 0-5, got {switch_to}"}
    elif pt in ("FAINT_SWITCH", "SWITCH_PROMPT"):
        if has_move:
            return {"error": f"Can't use a move in {pt} state. Use switch_to (0-5), or omit to {'flee' if pt == 'FAINT_SWITCH' else 'keep battling'}."}
        if has_switch and switch_to > 5:
            return {"error": f"switch_to must be 0-5, got {switch_to}"}
    elif pt == "FAINT_FORCED":
        if has_move:
            return {"error": "Can't use a move — your Pokemon fainted. Use switch_to (0-5) to send a replacement."}
        if not has_switch:
            return {"error": "Must switch in a trainer battle — specify switch_to (0-5)."}
        if switch_to > 5:
            return {"error": f"switch_to must be 0-5, got {switch_to}"}

    # 3. Execute the appropriate flow
    if pt == "ACTION":
        result = _execute_action(emu, prompt, move_index, switch_to, has_move)
    elif pt == "FAINT_SWITCH":
        result = _execute_faint_switch(emu, prompt, switch_to, has_switch)
    elif pt == "FAINT_FORCED":
        result = _execute_forced_switch(emu, prompt, switch_to)
    elif pt == "SWITCH_PROMPT":
        result = _execute_switch_prompt(emu, prompt, switch_to, has_switch)
    else:
        result = {"log": prompt["log"], "final_state": "NO_ACTION_PROMPT"}

    # 4. Format and append battle state
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
    result["log"] = prompt["log"] + result.get("log", [])
    result["final_state"] = _classify_final_state(emu, result)

    if result["final_state"] == "TIMEOUT" and _log_has(result.get("log", []), "grew to"):
        result = _recover_from_level_up(emu, result)

    return result


def _execute_faint_switch(
    emu: EmulatorClient, prompt: dict, switch_to: int, has_switch: bool,
) -> dict[str, Any]:
    """Wild faint: send replacement or flee."""
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
    _forced_switch_flow(emu, switch_to)
    return _poll_after_action(emu, prompt["log"])


def _execute_switch_prompt(
    emu: EmulatorClient, prompt: dict, switch_to: int, has_switch: bool,
) -> dict[str, Any]:
    """Trainer switch prompt: swap Pokemon or keep battling."""
    if has_switch:
        _prompt_switch_flow(emu, switch_to)
    else:
        _decline_flow(emu)
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
                return "LEVEL_UP"
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
    state_labels = {
        "WAIT_FOR_ACTION": "Your turn — select next move",
        "SWITCH_PROMPT": "Opponent sending next Pokemon — use battle_turn(switch_to=N) to swap, or battle_turn() to keep battling",
        "FAINT_SWITCH": "Your Pokemon fainted (wild) — use battle_turn(switch_to=N) to send replacement, or battle_turn() to flee",
        "FAINT_FORCED": "Your Pokemon fainted (trainer) — use battle_turn(switch_to=N) to send replacement",
        "BATTLE_ENDED": "Battle is over — back in overworld",
        "LEVEL_UP": "Level up with move learning — handle manually",
        "CAUGHT": "Pokemon caught! Back in overworld",
        "NOT_CAUGHT": "Ball failed — back at action prompt",
        "TIMEOUT": "Polling timed out — check game state manually",
        "NO_TEXT": "No battle text detected — action may not have registered",
        "NO_ACTION_PROMPT": "No action prompt detected — game may need manual input to proceed",
    }
    label = state_labels.get(state, state)
    lines.append(f"\nState: {state} — {label}")

    return "\n".join(lines)
