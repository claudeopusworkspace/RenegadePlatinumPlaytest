"""Tests for the move-learn prompt handling during battle.

Save states used:
  test_move_learn_prompt — Prinplup wants to learn Icy Wind, has 4 moves.
    At "Make it forget?" prompt (Prompt 1).
  bug_move_learn_skip_fire_fang_stuck — Luxio Lv24 mid-battle, at
    'Should this Pokemon give up on learning Fire Fang?' (Prompt 2 of
    the Gen 4 two-step flow). Regression: Prompt-2 skip looped back to
    Prompt 1 infinitely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestMoveLearn:
    """Move-learn prompt handling during battle."""

    def test_skip_move_learn_keeps_moves(self, emu: EmulatorClient):
        """Skip learning (forget_move=-1) — original moves unchanged."""
        load_state(emu, "test_move_learn_prompt")
        from renegade_mcp.turn import battle_turn
        from renegade_mcp.party import read_party
        result = battle_turn(emu, forget_move=-1)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
            "SWITCH_PROMPT",
        ), f"After skip, unexpected state: {result['final_state']}"
        # Verify Prinplup (slot 3) still has original 4 moves
        party = read_party(emu)
        prinplup = party[3]
        move_names = [m["name"] for m in prinplup["moves"]]
        assert "Peck" in move_names, f"Peck should still be known after skip, got: {move_names}"
        assert "Icy Wind" not in move_names, (
            f"Icy Wind should NOT be learned after skip, got: {move_names}"
        )

    def test_forget_move_and_learn(self, emu: EmulatorClient):
        """Forget Peck (slot 3) and learn Icy Wind — move list updated.

        Verification happens after battle ends: read_party returns stale
        (pre-battle) data during battle on melonDS because the encrypted party
        block is frozen until the battle result is written back.
        """
        load_state(emu, "test_move_learn_prompt")
        from renegade_mcp.turn import battle_turn
        from renegade_mcp.party import read_party
        result = battle_turn(emu, forget_move=3)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
            "SWITCH_PROMPT",
        ), f"After forget, unexpected state: {result['final_state']}"
        # Fight through remaining trainer Pokemon to end the battle
        for _ in range(20):
            state = result["final_state"]
            if state == "BATTLE_ENDED":
                break
            elif state == "MOVE_LEARN":
                result = battle_turn(emu, forget_move=-1)
            elif state == "SWITCH_PROMPT":
                result = battle_turn(emu, move_index=0)
            else:
                result = battle_turn(emu, move_index=0)
        assert result["final_state"] == "BATTLE_ENDED", (
            f"Battle should have ended, got: {result['final_state']}"
        )
        # Verify Prinplup (slot 3) now has Icy Wind instead of Peck
        party = read_party(emu)
        prinplup = party[3]
        move_names = [m["name"] for m in prinplup["moves"]]
        assert "Icy Wind" in move_names, f"Icy Wind should be learned, got: {move_names}"
        assert "Peck" not in move_names, f"Peck should be forgotten, got: {move_names}"

    def test_skip_move_learn_at_prompt2(self, emu: EmulatorClient):
        """Skip learning when already at Prompt 2 ('give up on Fire Fang?').

        Regression test: _skip_move_learn_flow assumed Prompt 1, so tapping
        'Keep old moves!' at Prompt 2 hit 'Don't give up!' instead, looping
        back to Prompt 1 infinitely. Fix detects Prompt 2 and taps 'Give up!'
        directly.
        """
        load_state(emu, "bug_move_learn_skip_fire_fang_stuck")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, forget_move=-1)
        assert result["final_state"] == "BATTLE_ENDED", (
            f"Expected BATTLE_ENDED after skipping Fire Fang, got: {result['final_state']}"
        )
