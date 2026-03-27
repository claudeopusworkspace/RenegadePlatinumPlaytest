"""Automated battle turn: init + move selection + poll + state detection.

Single tool that handles a complete battle turn:
1. Snapshots text baseline (absorbs battle_init)
2. Taps FIGHT, then taps the selected move
3. Polls for battle narration with auto-dismiss
4. Detects end states: next turn, switch prompt, battle end, level up
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.battle_tracker import _tracker

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# Touch coordinates for the move selection screen (bottom screen)
FIGHT_XY = (128, 90)
MOVE_XY = [
    (70, 50),    # Move 0 — top-left
    (190, 50),   # Move 1 — top-right
    (70, 110),   # Move 2 — bottom-left
    (190, 110),  # Move 3 — bottom-right
]

# Battle struct address for garbage detection
BATTLE_BASE = 0x022C5774
BATTLE_SLOT_SIZE = 0xC0

# Post-timeout recovery: press B to advance through stat screens / text
RECOVERY_PRESSES = 8
RECOVERY_WAIT = 300  # frames between B presses (~5 seconds per press)


def _is_battle_over(emu: EmulatorClient) -> bool:
    """Check if battle struct contains garbage data (= back in overworld).

    After battle ends, the struct retains stale data with impossible values.
    The most reliable signal is cur_hp > max_hp, which cannot happen in battle.
    """
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


def _log_has(log: list[dict], text: str) -> bool:
    """Check if any log entry contains the given text."""
    return any(text in e.get("text", "") for e in log)


def battle_turn(emu: EmulatorClient, move_index: int) -> dict[str, Any]:
    """Execute a full battle turn: init + select move + poll + detect state.

    Args:
        emu: Emulator client.
        move_index: Which move to use (0-3, left-to-right, top-to-bottom).

    Returns dict with:
        log: List of battle narration entries.
        final_state: WAIT_FOR_ACTION, SWITCH_PROMPT, BATTLE_ENDED,
                     LEVEL_UP, TIMEOUT.
        formatted: Human-readable battle log.
    """
    if move_index < 0 or move_index > 3:
        return {"error": f"move_index must be 0-3, got {move_index}"}

    # 1. Snapshot text baseline (replaces separate battle_init call)
    _tracker.init(emu)

    # 2. Tap FIGHT on bottom screen (settle first — touch may not register immediately)
    emu.advance_frames(60)
    emu.tap_touch_screen(FIGHT_XY[0], FIGHT_XY[1], frames=8)
    emu.advance_frames(60)

    # 3. Tap the move
    mx, my = MOVE_XY[move_index]
    emu.tap_touch_screen(mx, my, frames=8)

    # 4. Poll for battle narration (auto-dismiss mid-battle text)
    result = _tracker.poll(emu, auto_press=True)

    # 5. Enhanced state detection
    result["final_state"] = _classify_final_state(emu, result)

    # 6. On TIMEOUT with level-up text, try to recover through stat/move screens
    if result["final_state"] == "TIMEOUT" and _log_has(result.get("log", []), "grew to"):
        result = _recover_from_level_up(emu, result)

    result["formatted"] = _reformat(result)
    return result


def _recover_from_level_up(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any]:
    """After level-up causes a timeout, press B to advance through stat screens.

    The level-up sequence (stat popup, move learning prompt) uses a different
    UI that the battle text scanner can't see. Press B repeatedly to advance,
    then re-init and re-poll for the next battle state.
    """
    for _ in range(RECOVERY_PRESSES):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(RECOVERY_WAIT)

        # Check if we've returned to a battle text state
        # Re-init to pick up the current text as a new baseline
        _tracker.init(emu)
        poll = _tracker.poll(emu, auto_press=True)

        if poll["final_state"] == "WAIT_FOR_ACTION":
            # Found an action prompt — check if it's a switch prompt or normal turn
            result["log"].extend(poll.get("log", []))
            result["final_state"] = _classify_final_state(emu, poll)
            return result

        if poll["final_state"] != "NO_TEXT":
            # Got some text — keep going
            result["log"].extend(poll.get("log", []))

        # Check if battle ended during recovery
        if _is_battle_over(emu):
            result["final_state"] = "BATTLE_ENDED"
            return result

    # If we exhausted recovery attempts, it's likely a move learning prompt
    # that needs manual interaction (touch screen for move selection)
    result["final_state"] = "LEVEL_UP"
    return result


def _classify_final_state(emu: EmulatorClient, result: dict[str, Any]) -> str:
    """Refine the raw poll state into a more specific battle state."""
    raw_state = result.get("final_state", "")

    # Check log text for specific prompts
    if raw_state == "WAIT_FOR_ACTION":
        for entry in result.get("log", []):
            text = entry.get("text", "")
            if "Will you switch" in text:
                return "SWITCH_PROMPT"
            if "give up on" in text or "forget another move" in text:
                return "LEVEL_UP"
        return "WAIT_FOR_ACTION"

    # On timeout or no-text, check if battle actually ended
    if raw_state in ("TIMEOUT", "NO_TEXT"):
        if _is_battle_over(emu):
            return "BATTLE_ENDED"

    return raw_state


def _reformat(result: dict[str, Any]) -> str:
    """Reformat the log with the updated final state."""
    lines = ["=== Battle Log ==="]
    for entry in result.get("log", []):
        text = entry["text"].replace("\n", " / ")
        # Strip control codes from display
        for code in ("[FFFE]", "[VAR]"):
            while code in text:
                text = text[: text.index(code)].rstrip()
        lines.append(f"  {text}")

    state = result["final_state"]
    state_labels = {
        "WAIT_FOR_ACTION": "Your turn — select next move",
        "SWITCH_PROMPT": "Trainer sending next Pokemon — switch or keep battling?",
        "BATTLE_ENDED": "Battle is over — back in overworld",
        "LEVEL_UP": "Level up with move learning — handle manually",
        "TIMEOUT": "Polling timed out — check game state manually",
        "NO_TEXT": "No battle text detected — move may not have registered",
    }
    label = state_labels.get(state, state)
    lines.append(f"\nState: {state} — {label}")

    return "\n".join(lines)
