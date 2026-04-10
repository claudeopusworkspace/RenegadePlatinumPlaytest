"""Tests for party-wipe blackout recovery in battle_turn and auto_grind.

Uses save state: qol_battle_wipe_blackout_handling
  - Swinub (shiny, Lv19) is last alive Pokemon, at action prompt
  - vs Tangela Lv25 with +2 all stats (Ancient Power boost)
  - Ice Shard (slot 1) deals super effective damage but Grass Knot KOs Swinub
  - Full party wipe triggers blackout sequence

The test is deterministic — Tangela always KOs Swinub with Grass Knot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, assert_log_contains

STATE = "qol_battle_wipe_blackout_handling"


class TestBlackoutRecovery:
    """battle_turn advances through blackout and returns with free movement."""

    def test_blackout_returns_battle_ended(self, emu: EmulatorClient):
        """Full wipe returns BATTLE_ENDED with blackout flag."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=1)
        assert result["final_state"] == "BATTLE_ENDED", (
            f"Expected BATTLE_ENDED, got: {result['final_state']}"
        )
        assert result.get("blackout") is True, "Missing blackout=True flag"
        assert_log_contains(result, "is out of")

    def test_blackout_party_fully_healed(self, emu: EmulatorClient):
        """After blackout, party is fully healed by Nurse Joy."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        battle_turn(emu, move_index=1)
        from renegade_mcp.party import read_party
        party = read_party(emu)
        for mon in party:
            if mon.get("partial"):
                continue
            assert mon["hp"] == mon["max_hp"], (
                f"{mon['name']} not fully healed: {mon['hp']}/{mon['max_hp']}"
            )

    def test_blackout_player_in_pokemon_center(self, emu: EmulatorClient):
        """After blackout, player is in a Pokemon Center (free movement)."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        battle_turn(emu, move_index=1)
        from renegade_mcp.map_state import get_map_state
        state = get_map_state(emu)
        # Pokemon Centers have a "Pokecenter Nurse" NPC in the objects list
        npc_names = [o.get("name", "") for o in state.get("objects", [])]
        assert any("Pokecenter Nurse" in n for n in npc_names), (
            f"Expected Pokecenter Nurse NPC, but objects are: {npc_names}"
        )


class TestAutoGrindBlackout:
    """auto_grind stops with 'fainted' when a full party wipe occurs.

    Regression test: _fight_battle only checked final_state (BATTLE_ENDED)
    but not the blackout flag, so auto_grind continued looping from inside
    the Pokemon Center after a whiteout.
    """

    def test_fight_battle_returns_fainted_on_blackout(self, emu: EmulatorClient):
        """_fight_battle returns stop_reason='fainted' on full party wipe."""
        load_state(emu, STATE)
        from renegade_mcp.auto_grind import _fight_battle
        stop_reason, stop_detail, battle_log, _ = _fight_battle(emu, move_index=1)
        assert stop_reason == "fainted", (
            f"Expected stop_reason='fainted', got: '{stop_reason}'"
        )
        assert "party wipe" in stop_detail.lower() or "blacked out" in stop_detail.lower(), (
            f"Expected blackout detail, got: '{stop_detail}'"
        )
