"""Tests for QA bug fixes from 2026-04-15 triage session.

Covers BUG-002, BUG-003, BUG-004, BUG-008, BUG-009.
BUG-005 (evolution race) and BUG-010 (blackout) are code-confirmed only
(too expensive to repro — ~15 battles and 3-KO party wipe respectively).

Save states:
  qa_oreburgh_gate_entrance:
    - Player inside Oreburgh Gate, map_id=258
    - Used for BUG-008 (map_name correctness)

  test_bug004_dawn_battle_taunt:
    - Chimchar Lv10 vs Turtwig Lv9 (Dawn rival), at action prompt
    - Taunt is move slot 3, Turtwig has Withdraw
    - Used for BUG-004 (Taunt false MOVE_BLOCKED)

  test_bug009_roark_battle_monferno_lead:
    - Monferno Lv16 (slot 0) at action prompt vs Roark's Nosepass
    - Luxio (slot 1) and Eevee (slot 2) on bench
    - Bag has Potions
    - Used for BUG-009 (use_battle_item target reporting)

  qa_lake_verity_cyrus_cutscene_done:
    - Post-Cyrus cutscene at Lake Verity
    - Script in CTX_WAITING, Barry dialogue pending B press
    - Used for BUG-002 (cutscene dialogue CTX_WAITING)

  test_bug003_oreburgh_city_post_event:
    - Oreburgh City overworld, scripted NPC event already cleared
    - 0 badges, has Potions and money for purchases
    - Used for BUG-003 (Premier Ball bonus)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, assert_final_state, retry_on_rng


# ---------------------------------------------------------------------------
# BUG-008: map_name returns wrong names for reshuffled map IDs
# ---------------------------------------------------------------------------

class TestBug008MapName:
    """map_id_to_name.json rebuilt from ROM zone headers."""

    def test_oreburgh_gate_not_floaroma_meadow(self, emu: EmulatorClient):
        """Map 258 should be 'Oreburgh Gate', not 'Floaroma Meadow'."""
        load_state(emu, "qa_oreburgh_gate_entrance")
        from renegade_mcp.map_names import lookup_map_name
        result = lookup_map_name(258)
        assert result["name"] == "Oreburgh Gate", (
            f"Expected 'Oreburgh Gate', got '{result['name']}'"
        )

    def test_map_name_from_live_map_id(self, emu: EmulatorClient):
        """lookup_map_name() with the live map_id returns the correct name."""
        load_state(emu, "qa_oreburgh_gate_entrance")
        from renegade_mcp.map_names import lookup_map_name
        from renegade_mcp.map_state import read_player_state
        map_id, _, _, _ = read_player_state(emu)
        result = lookup_map_name(map_id)
        assert result["map_id"] == 258
        assert result["name"] == "Oreburgh Gate"

    def test_map_table_no_unknowns(self, emu: EmulatorClient):
        """Every entry in the rebuilt table has a resolved name (no 'Unknown')."""
        from renegade_mcp.data import map_table
        table = map_table()
        unknowns = [
            (k, v) for k, v in table.items()
            if "Unknown" in v.get("name", "")
        ]
        assert len(unknowns) == 0, (
            f"Found {len(unknowns)} unknown entries: {unknowns[:5]}"
        )


# ---------------------------------------------------------------------------
# BUG-004: battle_turn returns MOVE_BLOCKED when opponent is Taunt-blocked
# ---------------------------------------------------------------------------

class TestBug004TauntNotMoveBlocked:
    """Our Taunt landing on the opponent should NOT return MOVE_BLOCKED."""

    def test_taunt_returns_wait_for_action(self, emu: EmulatorClient):
        """Using Taunt on Turtwig returns WAIT_FOR_ACTION, not MOVE_BLOCKED.

        Turtwig tries Withdraw after being Taunted — game shows
        "The foe's Turtwig can't use Withdraw after the taunt!" which
        contains "can't use" but must NOT trigger MOVE_BLOCKED.
        """
        load_state(emu, "test_bug004_dawn_battle_taunt")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)  # Taunt

        assert result["final_state"] != "MOVE_BLOCKED", (
            "Taunt on opponent falsely returned MOVE_BLOCKED"
        )
        assert result["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED"), (
            f"Unexpected state: {result['final_state']}"
        )

    def test_taunt_pp_consumed(self, emu: EmulatorClient):
        """Taunt PP decrements (turn was consumed, not rejected)."""
        load_state(emu, "test_bug004_dawn_battle_taunt")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)

        # Read battle state to check Taunt PP
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        for b in battlers:
            if b.get("side") == "player":
                taunt_move = b["moves"][3]
                assert taunt_move["name"] == "Taunt"
                assert taunt_move["pp"] == 19, (
                    f"Taunt PP should be 19 (20-1), got {taunt_move['pp']}"
                )
                break

    def test_taunt_landed_in_log(self, emu: EmulatorClient):
        """Battle log confirms Taunt landed on the opponent."""
        load_state(emu, "test_bug004_dawn_battle_taunt")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)

        # "fell for the taunt" always appears when Taunt lands, regardless
        # of whether Turtwig tries a blocked move (RNG-dependent).
        # Normalize newlines within log entries (text has \n mid-line).
        log_text = " ".join(
            e.get("text", "").replace("\n", " ") for e in result.get("log", [])
        ).lower()
        assert "fell for the taunt" in log_text, (
            f"Expected 'fell for the taunt' in log, got: {log_text}"
        )


# ---------------------------------------------------------------------------
# BUG-009: use_battle_item target reporting hardcoded to slot 0
# ---------------------------------------------------------------------------

class TestBug009BattleItemTarget:
    """use_battle_item on bench Pokemon reports correct target, not slot 0."""

    def test_potion_on_bench_reports_correct_slot(self, emu: EmulatorClient):
        """Potion on party_slot=1 (bench Luxio) should NOT say 'Monferno'."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=1)

        assert result["success"] is True
        assert result["party_slot"] == 1
        # Must NOT report the active Pokemon (Monferno)
        target = result.get("target", "")
        assert "Monferno" not in target, (
            f"Target should not be Monferno (active slot 0), got: '{target}'"
        )

    def test_bench_pokemon_hp_unverifiable(self, emu: EmulatorClient):
        """Bench Pokemon healing returns success with unverifiable note."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=1)

        assert result["success"] is True
        assert "bench" in result.get("formatted", "").lower(), (
            f"Expected 'bench' in formatted message: {result.get('formatted')}"
        )

    def test_active_pokemon_reports_correct_name(self, emu: EmulatorClient):
        """Potion on party_slot=0 (active Monferno) reports 'Monferno'.

        Monferno is at full HP so the game says "It won't have any effect" —
        HP is unchanged, but the target name should still be resolved correctly.
        """
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)

        # Full HP → HP unchanged → tool reports failure (no effect).
        # The key assertion: target name should be "Monferno", not some other
        # Pokemon. Even on failure, the target is correctly identified.
        target = result.get("target", "")
        assert "Monferno" in target, (
            f"Expected 'Monferno' in target for active slot 0, got: '{target}'"
        )

    def test_final_state_is_wait_for_action(self, emu: EmulatorClient):
        """Using battle item returns WAIT_FOR_ACTION (not internal 'ACTION')."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=1)
        assert result["final_state"] == "WAIT_FOR_ACTION", (
            f"Expected WAIT_FOR_ACTION, got {result['final_state']}"
        )


# ---------------------------------------------------------------------------
# BUG-002: read_dialogue bails on cutscene CTX_WAITING state
# ---------------------------------------------------------------------------

class TestBug002CutsceneDialogue:
    """advance_dialogue handles CTX_WAITING (cutscene waiting for B press)."""

    def test_lake_verity_cutscene_not_no_dialogue(self, emu: EmulatorClient):
        """Post-Cyrus cutscene at Lake Verity should find dialogue, not bail."""
        load_state(emu, "qa_lake_verity_cyrus_cutscene_done")
        emu.advance_frames(30)
        from renegade_mcp.dialogue import advance_dialogue
        result = advance_dialogue(emu)

        assert result["status"] != "no_dialogue", (
            "advance_dialogue bailed with no_dialogue on CTX_WAITING cutscene"
        )
        assert result["status"] == "completed"

    def test_barry_dialogue_collected(self, emu: EmulatorClient):
        """Barry's dialogue lines are collected from the cutscene."""
        load_state(emu, "qa_lake_verity_cyrus_cutscene_done")
        emu.advance_frames(30)
        from renegade_mcp.dialogue import advance_dialogue
        result = advance_dialogue(emu)

        conversation = result.get("conversation", [])
        all_text = " ".join(conversation).lower()
        assert "did you hear that" in all_text, (
            f"Expected Barry's 'Did you hear that' in conversation: {conversation}"
        )


# ---------------------------------------------------------------------------
# BUG-003: buy_item Premier Ball bonus breaks next purchase
# ---------------------------------------------------------------------------

class TestBug003PremierBallBonus:
    """Buying 10+ Poke Balls (Premier Ball bonus) doesn't poison next buy."""

    @retry_on_rng("test_bug003_oreburgh_city_post_event")
    def test_buy_10_pokeballs_then_potions(self, emu: EmulatorClient):
        """Buy 10 Poke Balls, then 3 Potions — both succeed with correct cost."""
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        status = read_trainer_status(emu)
        badges = status.get("badges", 0)

        # First purchase: 10 Poke Balls (triggers Premier Ball bonus)
        result1 = buy_item(emu, "Poké Ball", quantity=10, badge_count=badges)
        assert result1["success"] is True, f"Poke Ball buy failed: {result1}"
        assert result1["money_spent"] == result1["total_cost"], (
            f"Poke Ball cost mismatch: spent={result1['money_spent']} "
            f"vs expected={result1['total_cost']}"
        )

        # Second purchase: 3 Potions (this was broken before the fix)
        result2 = buy_item(emu, "Potion", quantity=3, badge_count=badges)
        assert result2["success"] is True, f"Potion buy failed: {result2}"
        assert result2["item"] == "Potion", (
            f"Expected to buy Potion, got '{result2.get('item')}'"
        )
        assert result2["money_spent"] == result2["total_cost"], (
            f"Potion cost mismatch: spent={result2['money_spent']} "
            f"vs expected={result2['total_cost']}"
        )

    @retry_on_rng("test_bug003_oreburgh_city_post_event")
    def test_money_sanity_check(self, emu: EmulatorClient):
        """Purchase verification catches cost mismatch (sanity check exists)."""
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        status = read_trainer_status(emu)
        badges = status.get("badges", 0)

        # Normal single buy — sanity check should pass
        result = buy_item(emu, "Potion", quantity=1, badge_count=badges)
        assert result["success"] is True
        assert result["money_spent"] == result["total_cost"]
