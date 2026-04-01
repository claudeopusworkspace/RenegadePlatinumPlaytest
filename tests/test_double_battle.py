"""Tests for double battle scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import assert_final_state, do_load_state as load_state


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
