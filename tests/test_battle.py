"""Tests for battle tools: battle_turn, throw_ball, read_dialogue.

Most tests need retries for RNG (damage rolls, catch rates).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import (
    do_load_state as load_state,
    retry_on_rng,
    assert_log_contains,
    assert_final_state,
)


# ---------------------------------------------------------------------------
# battle_turn
# ---------------------------------------------------------------------------

class TestBattleTurn:
    """Core battle action tool."""

    @retry_on_rng("test_wild_battle_action")
    def test_use_move(self, emu: EmulatorClient):
        """Use move 0 — log shows the move was used."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
        ), f"Unexpected: {result['final_state']}"
        assert_log_contains(result, "used")

    @retry_on_rng("test_wild_battle_action")
    def test_run_from_battle(self, emu: EmulatorClient):
        """Run from wild battle — BATTLE_ENDED on success, WAIT_FOR_ACTION on fail."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, run=True)
        state = result["final_state"]
        assert state in ("BATTLE_ENDED", "WAIT_FOR_ACTION"), f"Unexpected: {state}"
        if state == "BATTLE_ENDED":
            assert_log_contains(result, "got away")
        else:
            assert_log_contains(result, "can't escape")

    @retry_on_rng("test_wild_battle_action")
    def test_switch_pokemon(self, emu: EmulatorClient):
        """Switch to party slot 1 mid-battle — new Pokemon is now active."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, switch_to=1)
        assert result["final_state"] == "WAIT_FOR_ACTION", (
            f"Switch should return WAIT_FOR_ACTION, got: {result['final_state']}"
        )
        # Active battler should now be slot 1's species (Machop in this state)
        player = next(b for b in result["battle_state"] if b["side"] == "player")
        assert player["species"] != "Prinplup", "Active battler should have changed from lead"

    @retry_on_rng("test_wild_battle_action")
    def test_battle_state_has_battlers(self, emu: EmulatorClient):
        """battle_turn response includes player and enemy battler data."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert "battle_state" in result, "Response missing battle_state"
        if result["final_state"] != "BATTLE_ENDED":
            bs = result["battle_state"]
            assert len(bs) >= 2, f"Expected >=2 battlers, got {len(bs)}"
            player = next((b for b in bs if b["side"] == "player"), None)
            enemy = next((b for b in bs if b["side"] == "enemy"), None)
            assert player is not None, "No player battler in battle_state"
            assert enemy is not None, "No enemy battler in battle_state"
            assert "species" in player and "hp" in player
            assert "species" in enemy and "hp" in enemy

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
    def test_fight_log_contains_damage(self, emu: EmulatorClient):
        """Using a damaging move produces log with move name and damage text."""
        from renegade_mcp.turn import battle_turn
        # Move 0 is Metal Claw (Steel, Physical) — should deal damage to Smoochum
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN")
        assert_log_contains(result, "Metal Claw")

    def test_double_battle_first_action(self, emu: EmulatorClient):
        """Double battle: first action returns WAIT_FOR_PARTNER_ACTION."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0, target=0)
        # First action in doubles should prompt for partner's action
        assert result["final_state"] == "WAIT_FOR_PARTNER_ACTION", (
            f"Expected WAIT_FOR_PARTNER_ACTION, got: {result['final_state']}"
        )

    @retry_on_rng("debug_doubles_target_swapped")
    def test_double_battle_both_actions(self, emu: EmulatorClient):
        """Double battle: submit both actions — turn resolves."""
        from renegade_mcp.turn import battle_turn
        # First Pokemon's action
        result1 = battle_turn(emu, move_index=0, target=0)
        assert result1["final_state"] == "WAIT_FOR_PARTNER_ACTION", (
            f"First action: expected WAIT_FOR_PARTNER_ACTION, got {result1['final_state']}"
        )
        # Second Pokemon's action
        result2 = battle_turn(emu, move_index=0, target=0)
        assert result2["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "SWITCH_PROMPT",
            "FAINT_SWITCH", "FAINT_FORCED", "MOVE_LEARN", "LEVEL_UP",
        ), f"Second action: unexpected state {result2['final_state']}"


# ---------------------------------------------------------------------------
# throw_ball
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Trainer battle (test_trainer_battle_action state)
# Bird Keeper Alexandra: Natu Lv20, Swablu Lv20. Luxio Lv21 lead.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Move learn (test_move_learn_prompt state)
# Prinplup wants to learn Icy Wind, has 4 moves. At "Make it forget?" prompt.
# ---------------------------------------------------------------------------

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

        Save state: Luxio Lv24 mid-battle, game at 'Should this Pokemon give
        up on learning Fire Fang?' (Prompt 2 of Gen 4 two-step flow).
        """
        load_state(emu, "bug_move_learn_skip_fire_fang_stuck")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, forget_move=-1)
        assert result["final_state"] == "BATTLE_ENDED", (
            f"Expected BATTLE_ENDED after skipping Fire Fang, got: {result['final_state']}"
        )


class TestThrowBall:
    """Catching Pokemon."""

    @retry_on_rng("test_wild_battle_action")
    def test_throw_ball_returns_valid_state(self, emu: EmulatorClient):
        """Throw a ball — returns CAUGHT, NOT_CAUGHT, or BATTLE_ENDED."""
        from renegade_mcp.catch import throw_ball
        result = throw_ball(emu)
        assert "final_state" in result, f"Missing final_state in: {list(result.keys())}"
        assert result["final_state"] in ("CAUGHT", "NOT_CAUGHT", "BATTLE_ENDED"), (
            f"Unexpected final_state: {result['final_state']}"
        )

    @retry_on_rng("test_wild_battle_action")
    def test_throw_ball_has_log(self, emu: EmulatorClient):
        """Catch attempt includes battle log entries."""
        from renegade_mcp.catch import throw_ball
        result = throw_ball(emu)
        assert "log" in result, f"Missing log in: {list(result.keys())}"
        assert len(result["log"]) > 0, "Log should not be empty after throw"


# ---------------------------------------------------------------------------
# read_dialogue
# ---------------------------------------------------------------------------

class TestReadDialogue:
    """Dialogue reading and advancement."""

    def test_active_dialogue_has_text(self, emu: EmulatorClient):
        """Active dialogue returns non-empty text from the Galactic Grunt."""
        load_state(emu, "test_npc_dialogue_active")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu)
        assert "text" in result, f"Missing 'text' in result: {list(result.keys())}"
        assert len(result["text"]) > 0, "Text should not be empty for active dialogue"

    def test_no_dialogue_returns_empty(self, emu: EmulatorClient):
        """No active dialogue returns placeholder text."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu)
        # read_dialogue returns "(no active text)" when nothing is on screen
        assert result["region"] == "none" or "no active" in result.get("text", ""), (
            f"Expected no-dialogue indicator, got region={result.get('region')}, text={result.get('text', '')[:50]}"
        )

    def test_advance_dialogue_completes(self, emu: EmulatorClient):
        """advance_dialogue processes full conversation and returns status."""
        load_state(emu, "test_npc_dialogue_active")
        from renegade_mcp.dialogue import advance_dialogue
        result = advance_dialogue(emu)
        assert "status" in result, f"Missing 'status' in result: {list(result.keys())}"
        assert "conversation" in result, f"Missing 'conversation' in result"
        assert len(result["conversation"]) > 0, "Should have captured dialogue text"
        assert result["status"] in ("completed", "yes_no_prompt", "multi_choice_prompt")
