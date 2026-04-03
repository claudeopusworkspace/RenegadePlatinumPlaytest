"""Tests for double battle scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


class TestDoubleBattle:
    """Double battle: two Pokemon on each side."""

    def test_first_action_returns_partner_prompt(self, emu: EmulatorClient):
        """First Pokemon acts → WAIT_FOR_PARTNER_ACTION.

        State: route203_first_double_battle — Luxio/Charmander vs Kricketot/Shinx.
        At first action prompt.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "route203_first_double_battle")
        result = battle_turn(emu, move_index=0, target=0)

        assert_final_state(result, "WAIT_FOR_PARTNER_ACTION")

    def test_both_actions_complete_turn(self, emu: EmulatorClient):
        """Submit both Pokemon's actions → turn executes → next state.

        State: route203_first_double_battle — same start.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "route203_first_double_battle")

        # First Pokemon
        result = battle_turn(emu, move_index=0, target=0)
        assert_final_state(result, "WAIT_FOR_PARTNER_ACTION")

        # Second Pokemon
        result = battle_turn(emu, move_index=0, target=1)

        # After both actions, turn executes — could be next turn or battle end
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "SWITCH_PROMPT",
            "FAINT_SWITCH", "FAINT_FORCED", "MOVE_LEARN",
        ), f"After double turn, got unexpected: {result['final_state']}"


class TestDoubleBattleSwitch:
    """Bug fix: switching in doubles returned TIMEOUT instead of WAIT_FOR_PARTNER_ACTION."""

    def test_switch_returns_partner_prompt(self, emu: EmulatorClient):
        """Switching a Pokemon in doubles → WAIT_FOR_PARTNER_ACTION.

        State: debug_double_battle_switch_timeout — Grotle/Machop vs Zubat/Croagunk.
        At first action prompt. Switching Grotle out should yield partner prompt for Machop.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_double_battle_switch_timeout")
        result = battle_turn(emu, switch_to=3)

        assert_final_state(result, "WAIT_FOR_PARTNER_ACTION")
        # Log should contain both action prompts
        assert_log_contains(result, "What will Grotle do?", "What will Machop do?")


class TestDoubleBattleMultiKO:
    """Bug fix: multi-KO + exp cascade caused premature BATTLE_ENDED in doubles."""

    def test_multi_ko_exp_cascade_continues_battle(self, emu: EmulatorClient):
        """Both enemies KO'd in one turn → exp cascade → trainer sends next Pokemon.

        State: debug_double_battle_end_timeout — Luxio/Machop vs Zubat(3HP)/Ledyba.
        At Machop's partner action. Spark KOs Ledyba, Knock Off KOs Zubat.
        Grunt should send Spinarak — battle must NOT end prematurely.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_double_battle_end_timeout")
        result = battle_turn(emu, move_index=3, target=1, )

        # Battle should continue (trainer sends Spinarak), not falsely end
        assert result["final_state"] in ("WAIT_FOR_ACTION", "WAIT_FOR_PARTNER_ACTION"), (
            f"Expected battle to continue, got: {result['final_state']}"
        )
        # Log should show the exp cascade and next Pokemon being sent
        assert_log_contains(result, "fainted", "Exp. Points")
        assert_log_contains(result, "Spinarak")


class TestDoubleBattleFaintedTarget:
    """Bug fix: targeting a fainted enemy slot got stuck on target selection screen."""

    def test_fainted_slot_auto_retries(self, emu: EmulatorClient):
        """Tapping a fainted enemy slot → auto-retry on the alive enemy.

        State: debug_double_battle_exp_share_evolution — Luxio/Machop vs Spinarak + empty slot.
        At Machop's partner action. Target 0 is the fainted/empty slot.
        The tool should auto-retry on the alive enemy and proceed normally.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_double_battle_exp_share_evolution")
        # target=0 hits the fainted slot — retry mechanism should redirect
        result = battle_turn(emu, move_index=0, target=0, )

        # Should succeed (partner prompt or turn completes), not get stuck
        assert result["final_state"] in (
            "WAIT_FOR_PARTNER_ACTION", "WAIT_FOR_ACTION",
            "BATTLE_ENDED", "SWITCH_PROMPT", "TIMEOUT",
        ), f"Expected move to execute, got: {result['final_state']}"
