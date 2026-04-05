"""Tests for move learning scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


class TestLevelUpMoveLearn:
    """KO triggers level-up → move learn prompt."""

    def test_level_up_triggers_move_learn(self, emu: EmulatorClient):
        """Tristan battle: Hoothoot at 7 HP. KO → Turtwig Lv11 → learns Curse.

        State: debug_pre_level_up_ko — one hit KOs Hoothoot, Turtwig levels to 11.
        Cursor already knows Curse is the new move. Should return MOVE_LEARN.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_pre_level_up_ko")
        result = battle_turn(emu, move_index=0)

        # Could get MOVE_LEARN if Turtwig already knows 4 moves,
        # or WAIT_FOR_ACTION/SWITCH_PROMPT if Curse auto-learns into an empty slot.
        state = result["final_state"]
        if state == "MOVE_LEARN":
            assert "move_to_learn" in result, "MOVE_LEARN state should include move_to_learn"
        elif state in ("WAIT_FOR_ACTION", "SWITCH_PROMPT", "BATTLE_ENDED"):
            # Curse auto-learned — check log
            assert_log_contains(result, "grew to")
        else:
            pytest.fail(f"Unexpected state after level-up KO: {state}")

    def test_shinx_auto_learns_quick_attack(self, emu: EmulatorClient):
        """Shinx Lv5 KOs Sentret → Lv6 → auto-learns Quick Attack (has open slot).

        State: debug_shinx_pre_levelup_ko_5hp — Sentret at 5 HP, Shinx Lv5.
        Quick Attack should auto-learn since Shinx has <4 moves.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_shinx_pre_levelup_ko_5hp")
        result = battle_turn(emu, move_index=0)

        # Should level up and auto-learn (no MOVE_LEARN prompt needed)
        assert result["final_state"] in ("BATTLE_ENDED", "WAIT_FOR_ACTION"), (
            f"Expected clean level-up, got {result['final_state']}"
        )
        assert_log_contains(result, "grew to")


class TestMoveLearnResolution:
    """Tests for resolving move-learn prompts (forget or skip)."""

    def test_skip_move_learn(self, emu: EmulatorClient):
        """At "Make it forget?" prompt → skip learning.

        State: debug_move_learn_forget_prompt — at the move forget prompt.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_move_learn_forget_prompt")
        result = battle_turn(emu, forget_move=-1)

        # After skipping, should continue battle or end
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "SWITCH_PROMPT", "BATTLE_ENDED",
        ), f"After skip, got unexpected state: {result['final_state']}"

    def test_forget_move_and_learn(self, emu: EmulatorClient):
        """At move selection screen → forget move 0, learn the new move.

        State: debug_move_select_screen — at the move forget selection grid.
        Moves: Tackle/Withdraw/Absorb/Razor Leaf + Curse.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_move_learn_forget_prompt")
        result = battle_turn(emu, forget_move=0)

        # After forgetting, should continue battle or end
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "SWITCH_PROMPT", "BATTLE_ENDED",
        ), f"After forget+learn, got unexpected state: {result['final_state']}"


class TestPostBattleMoveLearn:
    """Post-battle move learning (Exp Share level-up after BATTLE_ENDED).

    SKIPPED: No save state exists at the actual post-battle move-learn prompt.
    debug_post_battle_move_learn_ui is in the overworld pre-battle and requires
    fighting through a full Roark gym battle with precise XP accumulation.
    Add this test when the scenario occurs naturally during gameplay.
    """

    @pytest.mark.skip(reason="No save state at post-battle move-learn prompt yet")
    def test_post_battle_exp_share_move_learn(self, emu: EmulatorClient):
        """Win fight → Machop (Exp Share) levels up → move-learn UI in overworld."""
        from renegade_mcp.turn import battle_turn

        load_state(emu, "post_battle_move_learn_at_prompt")
        result = battle_turn(emu, forget_move=-1)
        assert result["final_state"] == "BATTLE_ENDED"
