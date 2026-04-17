"""Tests for post-battle event animation text dismissal.

Uses save state: bug_post_battle_dialogue_stuck_fountain
  - Eterna Gym, Charmeleon vs Aroma Lady Jenna's Gloom (last Pokemon)
  - Defeating this trainer triggers gym clock rotation + event text:
    "The fountain's water level dropped!" / "It's possible to walk
    across the fountain now!"

Bug: event text doesn't set is_msg_box_open, so advance_dialogue
missed it and battle_turn left the player stuck on the text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


STATE = "bug_post_battle_dialogue_stuck_fountain"


class TestEventAnimationText:
    """battle_turn dismisses post-battle event animation text."""

    def test_player_free_after_gym_event(self, emu: EmulatorClient):
        """After defeating a gym trainer that triggers event text,
        battle_turn returns with the player free to move."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=2)

        assert result["final_state"] == "BATTLE_ENDED"
        assert result.get("post_battle_dialogue"), "Should capture trainer dialogue"

        # Player should be free — verify by checking script state
        from renegade_mcp.dialogue import (
            _find_script_manager, _read_script_state, _read_context_state,
        )
        mgr = _find_script_manager(emu)
        if mgr:
            ss = _read_script_state(emu, mgr)
            ctx_ptr = ss["ctx0_ptr"]
            if ctx_ptr:
                ctx = _read_context_state(emu, ctx_ptr)
                assert ctx["state"] != 1, (
                    "Script context still CTX_RUNNING — event text not dismissed"
                )

    def test_navigation_works_after_gym_event(self, emu: EmulatorClient):
        """After the gym event text is dismissed, navigation tools work."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        battle_turn(emu, move_index=2)

        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import get_map_state
        state = get_map_state(emu)
        start_x, start_y = state["px"], state["py"]
        # Navigate to exit — should not error due to stuck text
        result = navigate_to(emu, 11, 27, flee_encounters=True)
        assert "error" not in result, f"Navigation failed: {result.get('error')}"
        final = result.get("final", {})
        final_pos = (final.get("x", start_x), final.get("y", start_y))
        assert final_pos != (start_x, start_y), (
            "Player didn't move — may be stuck on event text"
        )
