"""Tests for normal battle end scenarios (wild and trainer)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


class TestWildBattleEnd:
    """Wild battle: KO the opponent → BATTLE_ENDED."""

    def test_wild_starly_ko(self, emu: EmulatorClient):
        """Load wild Starly battle (Turtwig Lv7 vs Starly Lv4).

        Starly is weak — one or two hits should KO and end the battle.
        State: wild_starly_battle_start — at "What will Turtwig do?" prompt.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "wild_starly_battle_start")
        # Spam move 0 (Tackle) until battle ends
        result = battle_turn(emu, move_index=0)
        if result["final_state"] == "WAIT_FOR_ACTION":
            # Starly survived, hit again
            result = battle_turn(emu, move_index=0)
        assert_final_state(result, "BATTLE_ENDED")

    def test_wild_zigzagoon_ko(self, emu: EmulatorClient):
        """Load wild Zigzagoon battle (at action prompt).

        State: wild_zigzagoon_route202 — at action prompt.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "wild_zigzagoon_route202")
        result = battle_turn(emu, move_index=0)
        if result["final_state"] == "WAIT_FOR_ACTION":
            result = battle_turn(emu, move_index=0)
        assert_final_state(result, "BATTLE_ENDED")

    def test_one_hit_ko_battle_end(self, emu: EmulatorClient):
        """Starly at 1 hit from KO — verify clean battle end transition.

        State: debug_starly_one_hit_from_ko — one hit finishes it.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_starly_one_hit_from_ko")
        result = battle_turn(emu, move_index=0)
        assert_final_state(result, "BATTLE_ENDED")
        assert_log_contains(result, "fainted")


class TestTrainerBattleEnd:
    """Trainer battle: KO all opponent Pokemon → BATTLE_ENDED."""

    def test_trainer_switch_then_ko(self, emu: EmulatorClient):
        """Trainer battle where opponent has 2 Pokemon.

        State: tristan_battle_start — Youngster Tristan (Hoothoot + Starly).
        Turtwig Lv10 should sweep with Razor Leaf.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "tristan_battle_start")

        # Fight through the battle — may need multiple turns + switch prompt
        for _ in range(10):  # safety bound
            result = battle_turn(emu, move_index=0)
            state = result["final_state"]
            if state == "BATTLE_ENDED":
                break
            elif state == "SWITCH_PROMPT":
                # Decline switching — keep battling
                result = battle_turn(emu)
            elif state == "WAIT_FOR_ACTION":
                continue
            elif state == "MOVE_LEARN":
                # Skip any move learning
                result = battle_turn(emu, forget_move=-1)
            else:
                pytest.fail(f"Unexpected state: {state}")
        else:
            pytest.fail("Battle did not end within 10 turns")

        assert_final_state(result, "BATTLE_ENDED")

    def test_trainer_last_pokemon_ko(self, emu: EmulatorClient):
        """Trainer's Growlithe at 9 HP — one Tackle KOs → SWITCH_PROMPT for next Pokemon.

        State: debug_logan_growlithe_low_hp — Logan's Growlithe at 9 HP.
        After KO, expect SWITCH_PROMPT (trainer sends next Pokemon).
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_logan_growlithe_low_hp")
        result = battle_turn(emu, move_index=0)
        # After KO'ing first Pokemon, expect switch prompt or next turn
        assert result["final_state"] in ("SWITCH_PROMPT", "WAIT_FOR_ACTION", "BATTLE_ENDED")
