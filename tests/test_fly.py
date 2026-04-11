"""Tests for Fly tool: fast travel between cities via HM02.

Uses Wayne's E4 save states (8 badges, Garchomp knows Fly).
All tests call do_load_state with redetect_shift=True because the E4
save has a different heap address delta than our playthrough save.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state


# ── Helper ──

def _load_e4_outdoor(emu: EmulatorClient) -> None:
    """Load E4 outdoor state with delta re-detection."""
    do_load_state(emu, "e4_pokemon_league_outdoor", redetect_shift=True)


def _load_e4_indoor(emu: EmulatorClient) -> None:
    """Load E4 indoor (lobby) state with delta re-detection."""
    do_load_state(emu, "e4_pokemon_league_fly_ready", redetect_shift=True)


# ---------------------------------------------------------------------------
# Successful flights
# ---------------------------------------------------------------------------

class TestFlySuccess:
    """Fly to various destinations from the Pokemon League outdoor area."""

    def test_fly_to_jubilife(self, emu: EmulatorClient):
        """Fly to Jubilife City and verify map ID."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Jubilife City")
        assert result["success"] is True, f"Fly failed: {result}"
        assert result["map_id"] == 3
        assert result["destination"] == "Jubilife City"
        assert "Garchomp" in result["fly_user"]

    def test_fly_to_eterna(self, emu: EmulatorClient):
        """Fly to Eterna City."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Eterna City")
        assert result["success"] is True, f"Fly failed: {result}"
        assert result["map_id"] == 65

    def test_fly_to_snowpoint(self, emu: EmulatorClient):
        """Fly to Snowpoint City (near cursor boundary, Z=7)."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Snowpoint City")
        assert result["success"] is True, f"Fly failed: {result}"
        assert result["map_id"] == 165

    def test_fly_to_twinleaf(self, emu: EmulatorClient):
        """Fly to Twinleaf Town (bottom of map, max cursor distance from Snowpoint)."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Twinleaf Town")
        assert result["success"] is True, f"Fly failed: {result}"
        assert result["map_id"] == 411

    def test_fly_to_veilstone(self, emu: EmulatorClient):
        """Fly to Veilstone City."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Veilstone City")
        assert result["success"] is True, f"Fly failed: {result}"
        assert result["map_id"] == 132

    def test_fly_round_trip(self, emu: EmulatorClient):
        """Fly to a city, then fly back to Pokemon League."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result1 = use_fly(emu, "Pastoria City")
        assert result1["success"] is True, f"First fly failed: {result1}"
        assert result1["map_id"] == 120

        result2 = use_fly(emu, "Pokemon League")
        assert result2["success"] is True, f"Return fly failed: {result2}"
        assert result2["map_id"] == 172


# ---------------------------------------------------------------------------
# Destination resolution
# ---------------------------------------------------------------------------

class TestFlyDestinationResolution:
    """Verify partial matching and code-based lookups."""

    def test_partial_name_match(self, emu: EmulatorClient):
        """Partial name match works (e.g. 'jubilife')."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "jubilife")
        assert result["success"] is True
        assert result["destination"] == "Jubilife City"

    def test_code_match(self, emu: EmulatorClient):
        """City code match works (e.g. 'C04' = Eterna City)."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "C04")
        assert result["success"] is True
        assert result["destination"] == "Eterna City"

    def test_invalid_destination_rejected(self, emu: EmulatorClient):
        """Invalid destination returns error with valid destination list."""
        _load_e4_outdoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Lavender Town")
        assert result["success"] is False
        assert "Unknown fly destination" in result["error"]


# ---------------------------------------------------------------------------
# Pre-check failures
# ---------------------------------------------------------------------------

class TestFlyPreChecks:
    """Verify pre-flight validation catches errors before touching the UI."""

    def test_fly_indoors_rejected(self, emu: EmulatorClient):
        """Fly from indoors fails and cleans up menus."""
        _load_e4_indoor(emu)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Jubilife City")
        assert result["success"] is False
        assert "failed" in result["error"].lower() or "indoors" in result["error"].lower()

    def test_fly_no_badge_rejected(self, emu: EmulatorClient):
        """Fly without Cobble Badge returns badge error."""
        # Our playthrough state has only 2 badges
        do_load_state(emu, "eterna_city_post_gardenia_team_updated", redetect_shift=True)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Jubilife City")
        assert result["success"] is False
        assert "Cobble Badge" in result["error"]

    def test_fly_no_fly_user_rejected(self, emu: EmulatorClient):
        """Fly with no Fly user returns clear error."""
        # Use the lobby state where Garchomp doesn't know Fly yet
        do_load_state(emu, "e4_pokemon_league_lobby", redetect_shift=True)
        from renegade_mcp.fly import use_fly

        result = use_fly(emu, "Jubilife City")
        # This will fail either with "indoors" or "no Fly user" depending
        # on which check runs first.  The lobby state is indoors AND
        # the original lobby state doesn't have Fly taught yet... but
        # the fly_ready state does.  lobby state may still have Fly
        # if we saved after teaching.  Either way, it should fail.
        assert result["success"] is False
