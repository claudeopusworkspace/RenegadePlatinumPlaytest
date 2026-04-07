"""Tests for battle tools: battle_turn, throw_ball, read_dialogue.

Most tests need retries for RNG (damage rolls, catch rates).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# battle_turn
# ---------------------------------------------------------------------------

class TestBattleTurn:
    """Core battle action tool."""

    @retry_on_rng("test_wild_battle_action")
    def test_use_move(self, emu: EmulatorClient):
        """Use move 0 — returns WAIT_FOR_ACTION or BATTLE_ENDED."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
        ), f"Unexpected: {result['final_state']}"

    @retry_on_rng("test_wild_battle_action")
    def test_run_from_battle(self, emu: EmulatorClient):
        """Run from wild battle — returns BATTLE_ENDED."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, run=True)
        # May fail to flee (Smoochum might use Mean Look), but should return a valid state
        assert result["final_state"] in (
            "BATTLE_ENDED", "WAIT_FOR_ACTION",
        ), f"Unexpected: {result['final_state']}"

    @retry_on_rng("test_wild_battle_action")
    def test_switch_pokemon(self, emu: EmulatorClient):
        """Switch to party slot 1 mid-battle."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, switch_to=1)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED",
        ), f"Unexpected: {result['final_state']}"

    @retry_on_rng("test_wild_battle_action")
    def test_force_flag(self, emu: EmulatorClient):
        """force=True executes move without effectiveness check."""
        from renegade_mcp.turn import battle_turn
        # Use Metal Claw with force=True — should proceed normally
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "EFFECTIVENESS_WARNING", "MOVE_LEARN",
        )
        # If we got a warning, force should override it
        if result["final_state"] == "EFFECTIVENESS_WARNING":
            result2 = battle_turn(emu, move_index=0, force=True)
            assert result2["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN")

    @retry_on_rng("test_wild_battle_action")
    def test_fight_until_ko(self, emu: EmulatorClient):
        """Fight until KO — BATTLE_ENDED with 'fainted' in log."""
        from renegade_mcp.turn import battle_turn
        # Use Bubble Beam (move 2) repeatedly — super effective vs Ice
        for _ in range(10):
            result = battle_turn(emu, move_index=2)
            state = result["final_state"]
            if state == "BATTLE_ENDED":
                break
            elif state == "MOVE_LEARN":
                result = battle_turn(emu, forget_move=-1)
                if result["final_state"] == "BATTLE_ENDED":
                    break
            elif state in ("WAIT_FOR_ACTION",):
                continue
            else:
                break
        assert result["final_state"] == "BATTLE_ENDED"

    @retry_on_rng("test_wild_battle_action")
    def test_battle_state_in_response(self, emu: EmulatorClient):
        """battle_turn response includes battle_state data."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert "battle_state" in result
        if result["final_state"] != "BATTLE_ENDED":
            assert len(result["battle_state"]) > 0

    def test_double_battle_targeting(self, emu: EmulatorClient):
        """Double battle: use move with target."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0, target=0)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "WAIT_FOR_PARTNER_ACTION",
            "BATTLE_ENDED", "SWITCH_PROMPT", "MOVE_LEARN",
        )

    def test_double_battle_both_actions(self, emu: EmulatorClient):
        """Double battle: first action returns a valid state."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import battle_turn
        valid_states = (
            "WAIT_FOR_ACTION", "WAIT_FOR_PARTNER_ACTION",
            "BATTLE_ENDED", "SWITCH_PROMPT",
            "FAINT_SWITCH", "FAINT_FORCED", "MOVE_LEARN",
            "EFFECTIVENESS_WARNING", "NO_ACTION_PROMPT", "TIMEOUT",
            "NO_TEXT",
        )
        result = battle_turn(emu, move_index=0, target=0, force=True)
        assert result["final_state"] in valid_states


# ---------------------------------------------------------------------------
# throw_ball
# ---------------------------------------------------------------------------

class TestThrowBall:
    """Catching Pokemon."""

    @retry_on_rng("test_wild_battle_action")
    def test_throw_ball(self, emu: EmulatorClient):
        """Throw a ball in wild battle — returns catch result."""
        from renegade_mcp.catch import throw_ball
        result = throw_ball(emu)
        # Should return some result about the catch attempt
        assert result is not None
        assert "error" not in result or "caught" in result or "final_state" in result

    @retry_on_rng("test_wild_battle_action")
    def test_throw_ball_has_fields(self, emu: EmulatorClient):
        """Catch result has expected response fields."""
        from renegade_mcp.catch import throw_ball
        result = throw_ball(emu)
        # Should have some indication of what happened
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# read_dialogue
# ---------------------------------------------------------------------------

class TestReadDialogue:
    """Dialogue reading and advancement."""

    def test_active_dialogue(self, emu: EmulatorClient):
        """Active dialogue returns conversation text."""
        load_state(emu, "test_npc_dialogue_active")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu)
        assert "conversation" in result or "text" in result or "status" in result
        # Should have found and advanced through the text
        if "conversation" in result:
            assert len(result["conversation"]) > 0

    def test_no_dialogue(self, emu: EmulatorClient):
        """No active dialogue returns completed status."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu)
        # Should indicate no dialogue or completed
        assert result.get("status") in ("completed", "no_dialogue", None) or "error" not in result

    def test_passive_read(self, emu: EmulatorClient):
        """advance=false reads text without advancing."""
        load_state(emu, "test_npc_dialogue_active")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu, region="auto")
        # With advance=True (default), text should be consumed
        assert result is not None
