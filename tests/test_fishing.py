"""Integration tests for fishing via seek_encounter(rod=...)."""

from __future__ import annotations

import pytest

from helpers import do_load_state
from renegade_mcp.navigation import seek_encounter


# ── E4 save: Wayne has Old Rod + Good Rod, near water at Pokemon League ──

FISHING_STATE = "fishing_test_near_water"  # (842, 563), map 172, adjacent to water


class TestFishingBasic:
    """Basic fishing — use rod, get encounter."""

    def test_old_rod_encounter(self, emu):
        """Old Rod should produce an encounter within 20 casts."""
        do_load_state(emu, FISHING_STATE)
        result = seek_encounter(emu, rod="Old Rod")
        assert result["result"] == "encounter", f"Expected encounter, got: {result}"
        assert result["steps_taken"] >= 1
        enc = result["encounter"]
        assert enc["encounter"] == "battle"
        assert enc["prompt_ready"] is True
        # Should have battle state with enemy
        bs = enc["battle_state"]
        assert len(bs) >= 2
        enemy = [b for b in bs if b["side"] == "enemy"]
        assert len(enemy) >= 1
        assert enemy[0]["species"]  # non-empty species name

    def test_good_rod_encounter(self, emu):
        """Good Rod should produce an encounter within 20 casts."""
        do_load_state(emu, FISHING_STATE)
        result = seek_encounter(emu, rod="Good Rod")
        assert result["result"] == "encounter", f"Expected encounter, got: {result}"
        enc = result["encounter"]
        assert enc["encounter"] == "battle"
        assert enc["prompt_ready"] is True
        enemy = [b for b in enc["battle_state"] if b["side"] == "enemy"]
        assert len(enemy) >= 1
        # Good Rod yields higher-level fish than Old Rod
        assert enemy[0]["level"] > 5


class TestFishingValidation:
    """Error handling — bad rod names, missing rods."""

    def test_invalid_rod_name(self, emu):
        """Unknown rod name returns clear error."""
        do_load_state(emu, FISHING_STATE)
        result = seek_encounter(emu, rod="Fishing Pole")
        assert "error" in result
        assert "Unknown rod" in result["error"]

    def test_missing_rod(self, emu):
        """Rod not in bag returns error listing available rods."""
        do_load_state(emu, FISHING_STATE)
        result = seek_encounter(emu, rod="Super Rod")
        assert "error" in result
        assert "not found" in result["error"]
        assert "Old Rod" in result["error"]  # should list available rods

    def test_no_water_nearby(self, emu):
        """Fishing far from water returns error."""
        # Load the lobby state — indoors, no water tiles
        do_load_state(emu, "e4_pokemon_league_lobby")
        result = seek_encounter(emu, rod="Old Rod")
        assert "error" in result
        assert "water" in result["error"].lower() or "pause menu" in result["error"].lower()


class TestFishingPositioning:
    """Verify auto-positioning near water."""

    def test_navigates_to_water(self, emu):
        """From E4 outdoor spawn, should auto-navigate to water and fish."""
        do_load_state(emu, "e4_pokemon_league_outdoor")
        result = seek_encounter(emu, rod="Old Rod")
        assert result["result"] == "encounter", f"Expected encounter, got: {result}"
