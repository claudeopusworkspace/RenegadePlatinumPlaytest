"""Tests for faint and switch scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


class TestWildFaintSwitch:
    """Wild battle: your Pokemon faints → "Use next Pokemon?" prompt."""

    def test_faint_switch_send_replacement(self, emu: EmulatorClient):
        """At "Use next Pokemon?" → send in slot 1.

        State: debug_wild_faint_use_next — Turtwig fainted vs wild Zigzagoon.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_wild_faint_use_next")
        result = battle_turn(emu, switch_to=1)

        # After switching, should be at action prompt for the new Pokemon
        assert result["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED"), (
            f"After faint switch, got: {result['final_state']}"
        )

    def test_faint_switch_flee(self, emu: EmulatorClient):
        """At "Use next Pokemon?" → flee (no switch_to).

        State: debug_wild_faint_use_next — same state, but we flee.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_wild_faint_use_next")
        result = battle_turn(emu)  # no switch_to = flee

        assert_final_state(result, "BATTLE_ENDED")


class TestTrainerSwitchPrompt:
    """Trainer battle: "Will you switch your Pokemon?" after KO."""

    def test_switch_prompt_decline(self, emu: EmulatorClient):
        """At "Will you switch?" → decline (keep battling).

        State: tristan_switch_prompt — after KO'ing Hoothoot, before Starly.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "tristan_switch_prompt")
        result = battle_turn(emu)  # no switch_to = keep battling

        assert_final_state(result, "WAIT_FOR_ACTION")

    def test_switch_prompt_accept(self, emu: EmulatorClient):
        """At "Will you switch?" → switch to slot 1.

        State: tristan_switch_prompt — same state, but we switch.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "tristan_switch_prompt")
        result = battle_turn(emu, switch_to=1)

        assert_final_state(result, "WAIT_FOR_ACTION")


class TestSwitchDuringBattle:
    """Voluntary switch during normal battle turn."""

    def test_voluntary_switch(self, emu: EmulatorClient):
        """Normal action prompt → switch to slot 1 instead of attacking.

        State: debug_switch_test_baseline — Wild Zigzagoon, 2 Pokemon.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_switch_test_baseline")
        result = battle_turn(emu, switch_to=1)

        # After voluntary switch, should be at next action prompt
        assert_final_state(result, "WAIT_FOR_ACTION")
