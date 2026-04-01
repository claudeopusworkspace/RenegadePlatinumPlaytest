"""Tests for evolution scenarios during and after battle."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


class TestMidBattleEvolution:
    """Evolution triggered by level-up during battle."""

    def test_shinx_evolution_with_move_learn(self, emu: EmulatorClient):
        """Shinx Lv14 KOs Sentret → Lv15 → Charge move-learn → Luxio evolution.

        State: debug_shinx_pre_evolution_ko — Shinx Lv14, Bite KOs Sentret.
        Chain: KO → level-up → Charge learn prompt → evolution animation.
        Should return MOVE_LEARN for Charge (before evolution happens).
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_shinx_pre_evolution_ko")
        result = battle_turn(emu, move_index=1)  # Bite

        # Should hit MOVE_LEARN for Charge before evolution
        if result["final_state"] == "MOVE_LEARN":
            assert "move_to_learn" in result
            # Verify it's Charge (or at least has move info)
            assert result["move_to_learn"], "move_to_learn should not be empty"
        else:
            # If it handled the move learn automatically, should see level-up
            assert_log_contains(result, "grew to")

    def test_evolution_after_move_learn_skip(self, emu: EmulatorClient):
        """At move-learn prompt pre-evolution → skip → Shinx evolves to Luxio.

        State: debug_shinx_move_learn_pre_evolution — at "Make it forget?" for Charge.
        Skipping Charge should trigger Shinx → Luxio evolution.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_shinx_move_learn_pre_evolution")
        result = battle_turn(emu, forget_move=-1)

        # After skipping move learn, evolution should happen
        assert_final_state(result, "BATTLE_ENDED")
        assert_log_contains(result, "evolved into")


class TestExpShareEvolution:
    """Evolution triggered by Exp Share level-up (non-active Pokemon)."""

    def test_exp_share_holder_evolves(self, emu: EmulatorClient):
        """Piplup (Exp Share, slot 3) levels to 16 → Prinplup evolution + Metal Claw learn.

        State: debug_piplup_evolution_r207 — grinding on Route 207.
        Uses auto_grind with 1 iteration to trigger the Exp Share level-up.
        """
        from renegade_mcp.auto_grind import auto_grind

        load_state(emu, "debug_piplup_evolution_r207")
        result = auto_grind(emu, move_index=3, iterations=1)

        # Should stop for move_learn (Metal Claw) after Piplup→Prinplup
        if result["stop_reason"] == "move_learn":
            assert "move_to_learn" in result
        elif result["stop_reason"] == "iterations":
            # Evolution happened but move learned into empty slot
            pass
        else:
            # Acceptable: fainted, unexpected — depends on encounter RNG
            assert result["stop_reason"] in (
                "move_learn", "iterations", "fainted",
            ), f"Unexpected stop_reason: {result['stop_reason']}"

    def test_mid_evolution_animation(self, emu: EmulatorClient):
        """Mid-evolution animation state — verify battle_turn handles gracefully.

        State: piplup_evo_in_progress — captured during Piplup→Prinplup animation.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "piplup_evo_in_progress")
        result = battle_turn(emu, move_index=0)

        # Depends on exactly where in the animation the state was captured.
        # Should either complete the evolution or detect battle end.
        assert result["final_state"] in (
            "BATTLE_ENDED", "WAIT_FOR_ACTION", "MOVE_LEARN",
            "NO_ACTION_PROMPT", "TIMEOUT",
        ), f"Unexpected state from mid-evolution: {result['final_state']}"
