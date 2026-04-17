"""Tests for trainer-battle flows: multi-Pokemon, SWITCH_PROMPT, post-battle.

Save state used:
  test_trainer_battle_action — Bird Keeper Alexandra: Natu Lv20, Swablu Lv20.
    Luxio Lv21 lead, at action prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import retry_on_rng, assert_log_contains


class TestTrainerBattle:
    """Trainer battle scenarios — multi-Pokemon, switch prompt, battle end."""

    @retry_on_rng("test_trainer_battle_action")
    def test_trainer_use_move(self, emu: EmulatorClient):
        """Spark vs Natu — super effective OHKO into SWITCH_PROMPT."""
        from renegade_mcp.turn import battle_turn
        # Spark (Electric) vs Natu (Psychic/Flying) = SE, should OHKO
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] == "SWITCH_PROMPT", (
            f"Expected SWITCH_PROMPT (Spark OHKO), got: {result['final_state']}"
        )
        assert_log_contains(result, "Spark", "super effective", "fainted")

    @retry_on_rng("test_trainer_battle_action")
    def test_switch_prompt_has_next_pokemon(self, emu: EmulatorClient):
        """After KO, SWITCH_PROMPT includes the trainer's next Pokemon."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] == "SWITCH_PROMPT"
        # Battle state should show Swablu as next enemy
        enemies = [b for b in result["battle_state"] if b["side"] == "enemy"]
        assert len(enemies) > 0, "Should have next enemy Pokemon in battle state"
        assert enemies[0]["species"] == "Swablu", (
            f"Expected Swablu next, got: {enemies[0]['species']}"
        )

    @retry_on_rng("test_trainer_battle_action")
    def test_decline_switch_and_continue(self, emu: EmulatorClient):
        """At SWITCH_PROMPT, decline switch via move_index — battle advances."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] == "SWITCH_PROMPT"
        # Pass move_index to decline switch AND queue the next move
        result2 = battle_turn(emu, move_index=0)
        assert result2["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
            "SWITCH_PROMPT",  # can chain if KO triggers another
        ), f"After decline+move, unexpected state: {result2['final_state']}"

    @retry_on_rng("test_trainer_battle_action")
    def test_accept_switch_at_prompt(self, emu: EmulatorClient):
        """At SWITCH_PROMPT, switch to slot 1 — Machop becomes active."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] == "SWITCH_PROMPT"
        result2 = battle_turn(emu, switch_to=1)
        assert result2["final_state"] in (
            "WAIT_FOR_ACTION", "SWITCH_PROMPT",
        ), f"Expected WAIT_FOR_ACTION or SWITCH_PROMPT after switch, got: {result2['final_state']}"
        # Verify Machop is now the active battler
        player = next(b for b in result2["battle_state"] if b["side"] == "player")
        assert player["species"] == "Machop", (
            f"Expected Machop active after switch, got: {player['species']}"
        )

    @retry_on_rng("test_trainer_battle_action")
    def test_trainer_full_battle(self, emu: EmulatorClient):
        """Fight through entire trainer battle — ends with BATTLE_ENDED."""
        from renegade_mcp.turn import battle_turn
        for _ in range(20):
            result = battle_turn(emu, move_index=0)
            state = result["final_state"]
            if state == "BATTLE_ENDED":
                break
            elif state == "SWITCH_PROMPT":
                continue  # next loop iteration will pass move_index to decline+attack
            elif state == "MOVE_LEARN":
                result = battle_turn(emu, forget_move=-1)
                if result["final_state"] == "BATTLE_ENDED":
                    break
            elif state in ("WAIT_FOR_ACTION",):
                continue
            else:
                break
        assert result["final_state"] == "BATTLE_ENDED"

    @retry_on_rng("test_trainer_battle_action")
    def test_trainer_post_battle_dialogue(self, emu: EmulatorClient):
        """Trainer battle end includes post-battle dialogue."""
        from renegade_mcp.turn import battle_turn
        for _ in range(20):
            result = battle_turn(emu, move_index=0)
            state = result["final_state"]
            if state == "BATTLE_ENDED":
                break
            elif state == "SWITCH_PROMPT":
                continue
            elif state == "MOVE_LEARN":
                result = battle_turn(emu, forget_move=-1)
                if result["final_state"] == "BATTLE_ENDED":
                    break
            elif state in ("WAIT_FOR_ACTION",):
                continue
            else:
                break
        assert result["final_state"] == "BATTLE_ENDED"
        # Trainer defeat text should appear in the battle log
        # (either in post_battle_dialogue or directly in log)
        assert_log_contains(result, "defeated")
