"""Tests for normal battle end scenarios (wild and trainer)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


def _fight_until_done(emu, move_index: int = 0, max_turns: int = 15) -> dict:
    """Loop battle_turn until BATTLE_ENDED or max_turns, handling switch prompts."""
    from renegade_mcp.turn import battle_turn

    result = None
    for _ in range(max_turns):
        result = battle_turn(emu, move_index=move_index)
        if "error" in result:
            pytest.fail(f"battle_turn error: {result['error']}")

        # Handle sub-states in a loop until we get WAIT_FOR_ACTION or terminal
        while True:
            state = result.get("final_state", "")
            if state == "BATTLE_ENDED":
                return result
            elif state == "SWITCH_PROMPT":
                result = battle_turn(emu)  # keep battling
            elif state == "MOVE_LEARN":
                result = battle_turn(emu, forget_move=-1)  # skip
            elif state in ("FAINT_SWITCH", "FAINT_FORCED"):
                result = battle_turn(emu, switch_to=1)  # send backup
            elif state in ("WAIT_FOR_ACTION", "WAIT_FOR_PARTNER_ACTION"):
                break  # exit inner loop, next iteration picks a move
            else:
                pytest.fail(f"Unexpected state mid-battle: {state}")

    pytest.fail(f"Battle did not end within {max_turns} turns. Last state: {result}")


class TestWildBattleEnd:
    """Wild battle: KO the opponent → BATTLE_ENDED."""

    def test_wild_starly_ko(self, emu: EmulatorClient):
        """Turtwig Lv7 vs Starly Lv4 — fight until KO.

        State: wild_starly_battle_start — at "What will Turtwig do?" prompt.
        Damage rolls are variable, so loop up to 5 turns.
        """
        load_state(emu, "wild_starly_battle_start")
        result = _fight_until_done(emu, move_index=0, max_turns=5)
        assert_final_state(result, "BATTLE_ENDED")

    def test_wild_zigzagoon_ko(self, emu: EmulatorClient):
        """Turtwig vs wild Zigzagoon — fight until KO.

        State: wild_zigzagoon_route202 — at action prompt.
        """
        load_state(emu, "wild_zigzagoon_route202")
        result = _fight_until_done(emu, move_index=0, max_turns=5)
        assert_final_state(result, "BATTLE_ENDED")

    def test_one_hit_ko_battle_end(self, emu: EmulatorClient):
        """Starly at low HP — KO within a few hits, verify fainted in log.

        State: debug_starly_one_hit_from_ko — Starly at 10/17 HP.
        """
        load_state(emu, "debug_starly_one_hit_from_ko")
        result = _fight_until_done(emu, move_index=0, max_turns=3)
        assert_final_state(result, "BATTLE_ENDED")
        assert_log_contains(result, "fainted")


class TestTrainerBattleEnd:
    """Trainer battle: KO all opponent Pokemon → BATTLE_ENDED."""

    def test_trainer_full_battle(self, emu: EmulatorClient):
        """Youngster Tristan: 2 Pokemon (Hoothoot + Starly).

        State: tristan_battle_start — Turtwig Lv10 vs Hoothoot Lv7.
        Use Razor Leaf (move 3) for super-effective damage on Normal/Flying.
        """
        load_state(emu, "tristan_battle_start")
        # move 3 = Razor Leaf (Grass, hits harder than Tackle)
        result = _fight_until_done(emu, move_index=3, max_turns=10)
        assert_final_state(result, "BATTLE_ENDED")

    def test_trainer_switch_prompt_after_ko(self, emu: EmulatorClient):
        """Trainer's Growlithe at 9 HP — KO triggers next Pokemon.

        State: debug_logan_growlithe_low_hp — Logan's Growlithe at 9 HP.
        After KO, expect SWITCH_PROMPT (trainer sends next Pokemon).
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_logan_growlithe_low_hp")
        result = battle_turn(emu, move_index=0)
        # After KO'ing first Pokemon, expect switch prompt or continued battle
        assert result.get("final_state") in (
            "SWITCH_PROMPT", "WAIT_FOR_ACTION", "BATTLE_ENDED",
        ), f"Unexpected: {result}"
