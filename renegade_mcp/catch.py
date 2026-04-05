"""Throw a Poké Ball at the wild Pokemon in battle.

Navigates BAG → Poké Balls → select → USE, then polls for catch result.
Returns CAUGHT, NOT_CAUGHT (broke free → back to action prompt), or BATTLE_ENDED.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.battle_tracker import _tracker
from renegade_mcp.turn import _is_battle_over

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# Touch coordinates for battle bag navigation
BAG_XY = (45, 170)
POKE_BALLS_XY = (190, 75)
USE_XY = (128, 170)

# Post-catch recovery (pokedex, nickname prompt, etc.)
CATCH_RECOVERY_PRESSES = 12
CATCH_RECOVERY_WAIT = 300


def throw_ball(emu: EmulatorClient) -> dict[str, Any]:
    """Throw a Poké Ball at the wild Pokemon.

    Must be called at the "What will X do?" action prompt in a wild battle.
    Navigates the bag UI, throws the first available Poké Ball, and polls
    for the result.

    Returns dict with:
        log: Battle narration entries.
        final_state: CAUGHT, NOT_CAUGHT, BATTLE_ENDED, TIMEOUT.
    """
    # 1. Snapshot text baseline
    _tracker.init(emu)

    # 2. Navigate bag: BAG → Poké Balls → select → USE
    emu.advance_frames(60)
    emu.tap_touch_screen(BAG_XY[0], BAG_XY[1], frames=8)
    emu.advance_frames(60)
    emu.tap_touch_screen(POKE_BALLS_XY[0], POKE_BALLS_XY[1], frames=8)
    emu.advance_frames(60)
    emu.press_buttons(["a"], frames=8)  # Select ball
    emu.advance_frames(60)
    emu.press_buttons(["a"], frames=8)  # Show description
    emu.advance_frames(60)
    emu.tap_touch_screen(USE_XY[0], USE_XY[1], frames=8)  # Tap USE

    # 3. Poll for catch result
    result = _tracker.poll(emu, auto_press=True)

    # 4. Classify the result
    log = result.get("log", [])
    raw_state = result.get("final_state", "")

    if raw_state == "WAIT_FOR_ACTION":
        # Back at action prompt — ball didn't catch
        result["final_state"] = "NOT_CAUGHT"
    elif _log_has_catch(log):
        # Caught text found — advance through pokedex + nickname screens
        result = _recover_from_catch(emu, result)
    elif raw_state in ("TIMEOUT", "NO_TEXT"):
        if _is_battle_over(emu):
            result["final_state"] = "BATTLE_ENDED"
    # else: keep raw state (TIMEOUT etc.)

    return result


def _log_has_catch(log: list[dict]) -> bool:
    """Check if any log entry indicates a successful catch."""
    return any("was caught" in e.get("text", "") for e in log)


def _recover_from_catch(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any]:
    """After catching, press through pokedex registration + nickname prompt.

    The catch sequence after "Gotcha! X was caught!":
    1. Pokedex registration screen (touch to dismiss, first catch only)
    2. "Give a nickname?" prompt (down + A to decline)
    3. If naming screen appears, tap OK (222, 74) to keep default
    4. Return to overworld
    """
    for i in range(CATCH_RECOVERY_PRESSES):
        # Alternate between B, touch, and down+A to handle various screens
        if i % 4 == 0:
            # Touch center to dismiss pokedex
            emu.tap_touch_screen(128, 96, frames=8)
        elif i % 4 == 1:
            # Down + A to decline nickname
            emu.press_buttons(["down"], frames=8)
            emu.advance_frames(15)
            emu.press_buttons(["a"], frames=8)
        elif i % 4 == 2:
            # Tap OK on keyboard if we ended up there
            emu.tap_touch_screen(222, 74, frames=8)
        else:
            # B to dismiss remaining screens
            emu.press_buttons(["b"], frames=8)

        emu.advance_frames(CATCH_RECOVERY_WAIT)

        if _is_battle_over(emu):
            result["final_state"] = "CAUGHT"
            return result

    # If we exhausted recovery, assume caught (we saw the text)
    result["final_state"] = "CAUGHT"
    return result
