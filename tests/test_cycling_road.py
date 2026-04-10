"""Tests for cycling road (Route 206) navigation.

Bridge body tiles (0x71) force downhill sliding on the bicycle.
These tests verify detection, movement in all directions, and encounter handling.

All tests use the cycling_road_edge save state: Route 206, y=592 (last ground
tile before bridge), on bicycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestCyclingRoadDetection:
    """is_on_cycling_road() detection logic."""

    @retry_on_rng("cycling_road_edge")
    def test_not_detected_on_ground_tiles(self, emu: EmulatorClient):
        """Player at y=592 (ground tile, pre-bridge) — not on cycling road."""
        from renegade_mcp.map_state import is_on_cycling_road
        assert not is_on_cycling_road(emu), "Should not detect cycling road on ground tile"

    @retry_on_rng("cycling_road_edge")
    def test_detected_with_target_on_bridge(self, emu: EmulatorClient):
        """Player at y=592 but target at y=600 (bridge body) — detected via path scan."""
        from renegade_mcp.map_state import is_on_cycling_road
        assert is_on_cycling_road(emu, target_x=304, target_y=600), (
            "Should detect cycling road when target is on bridge body tiles"
        )

    @retry_on_rng("cycling_road_edge")
    def test_detected_on_bridge_body(self, emu: EmulatorClient):
        """Step onto bridge body tile — detected by current tile behavior."""
        from renegade_mcp.map_state import is_on_cycling_road
        # Step onto bridge: 2 bike steps south (592→593→594, where 594 is 0x71)
        emu.advance_frames(4, buttons=["down"])
        emu.advance_frames(8)
        emu.advance_frames(4, buttons=["down"])
        emu.advance_frames(8)
        assert is_on_cycling_road(emu), "Should detect cycling road on bridge body tile"

    @retry_on_rng("test_eterna_city_overworld")
    def test_not_detected_off_bicycle(self, emu: EmulatorClient):
        """Not on bicycle — never detected as cycling road."""
        from renegade_mcp.map_state import is_on_cycling_road
        # Eterna City overworld, walking — even with a bridge target, no detection
        assert not is_on_cycling_road(emu, target_x=304, target_y=600), (
            "Should not detect cycling road when not on bicycle"
        )


# ---------------------------------------------------------------------------
# Terrain labels
# ---------------------------------------------------------------------------

class TestTerrainLabels:
    """BEHAVIORS dict correctness from decomp."""

    def test_bridge_labels(self, emu: EmulatorClient):
        """Bridge tiles (0x70-0x71) labeled correctly."""
        from renegade_mcp.map_state import BEHAVIORS
        assert BEHAVIORS[0x70] == "bridge_start"
        assert BEHAVIORS[0x71] == "bridge"

    def test_snow_labels(self, emu: EmulatorClient):
        """Snow tiles (0xA1-0xA3) labeled correctly from decomp."""
        from renegade_mcp.map_state import BEHAVIORS
        assert BEHAVIORS[0xA1] == "snow_deep"
        assert BEHAVIORS[0xA2] == "snow_deeper"
        assert BEHAVIORS[0xA3] == "snow_deepest"

    def test_bike_slope_labels(self, emu: EmulatorClient):
        """Bike slope/ramp tiles labeled correctly."""
        from renegade_mcp.map_state import BEHAVIORS
        assert BEHAVIORS[0xD9] == "bike_slope_top"
        assert BEHAVIORS[0xDA] == "bike_slope_bottom"

    def test_bridge_behaviors_set(self, emu: EmulatorClient):
        """BIKE_BRIDGE_BEHAVIORS contains expected bridge tiles."""
        from renegade_mcp.map_state import BIKE_BRIDGE_BEHAVIORS
        assert 0x70 in BIKE_BRIDGE_BEHAVIORS
        assert 0x71 in BIKE_BRIDGE_BEHAVIORS
        assert 0x00 not in BIKE_BRIDGE_BEHAVIORS  # ground is not bridge


# ---------------------------------------------------------------------------
# navigate_manual blocking
# ---------------------------------------------------------------------------

class TestNavigateManualBlocking:
    """navigate (manual) refuses on cycling road."""

    @retry_on_rng("cycling_road_edge")
    def test_blocked_on_bridge(self, emu: EmulatorClient):
        """navigate refuses with cycling_road error when on bridge body."""
        from renegade_mcp.navigation import navigate_manual
        # Step onto bridge body tile first
        emu.advance_frames(4, buttons=["down"])
        emu.advance_frames(8)
        emu.advance_frames(4, buttons=["down"])
        emu.advance_frames(8)
        result = navigate_manual(emu, "d1")
        assert "error" in result, "Expected error on cycling road"
        assert result.get("cycling_road") is True

    @retry_on_rng("cycling_road_edge")
    def test_allowed_on_ground(self, emu: EmulatorClient):
        """navigate works normally on ground tiles before bridge."""
        from renegade_mcp.navigation import navigate_manual
        # y=592 is ground — should work fine
        result = navigate_manual(emu, "u1")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["steps"] == 1


# ---------------------------------------------------------------------------
# Cycling road navigation — southbound
# ---------------------------------------------------------------------------

class TestCyclingRoadSouth:
    """Southbound navigation using auto-slide."""

    @retry_on_rng("cycling_road_edge")
    def test_slide_south(self, emu: EmulatorClient):
        """navigate_to south target on bridge — auto-slides to exact position."""
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 304, 600)
        assert result.get("cycling_road") is True
        assert result.get("reached_target") is True
        assert result["final"]["x"] == 304
        assert result["final"]["y"] == 600

    @retry_on_rng("cycling_road_edge")
    def test_slide_uses_no_input(self, emu: EmulatorClient):
        """Steps log shows 'slide' entries for southbound auto-movement."""
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 304, 600)
        slide_entries = [s for s in result["steps_log"] if s.startswith("slide")]
        assert len(slide_entries) > 0, "Expected slide entries in steps_log"


# ---------------------------------------------------------------------------
# Cycling road navigation — northbound (uphill)
# ---------------------------------------------------------------------------

class TestCyclingRoadNorth:
    """Northbound (uphill) navigation against the slide."""

    @retry_on_rng("cycling_road_edge")
    def test_uphill_return(self, emu: EmulatorClient):
        """Navigate south then back north — reaches both targets."""
        from renegade_mcp.navigation import navigate_to
        # Go south to y=598
        south = navigate_to(emu, 304, 598)
        assert south.get("reached_target") is True, f"South failed: {south}"
        # Go back north to y=594
        north = navigate_to(emu, 304, 594)
        assert north.get("reached_target") is True, f"North failed: {north}"
        assert north["final"]["y"] == 594

    @retry_on_rng("cycling_road_edge")
    def test_uphill_exits_bridge(self, emu: EmulatorClient):
        """Navigate uphill past bridge_start tile back to ground."""
        from renegade_mcp.navigation import navigate_to
        # Go south first
        navigate_to(emu, 304, 596)
        # Go north past bridge entirely (y=590 is ground)
        result = navigate_to(emu, 304, 590)
        assert result.get("reached_target") is True
        assert result["final"]["y"] == 590


# ---------------------------------------------------------------------------
# Cycling road navigation — lateral
# ---------------------------------------------------------------------------

class TestCyclingRoadLateral:
    """Lateral (east/west) movement with south drift."""

    @retry_on_rng("cycling_road_edge")
    def test_lateral_with_south(self, emu: EmulatorClient):
        """Navigate to (302, 600) — requires lateral moves + south slide."""
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 302, 600)
        assert result.get("cycling_road") is True
        assert result.get("reached_target") is True
        assert result["final"]["x"] == 302
        assert result["final"]["y"] == 600

    @retry_on_rng("cycling_road_edge")
    def test_lateral_logged(self, emu: EmulatorClient):
        """Lateral moves appear in steps_log as left/right entries."""
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 302, 600)
        lateral_entries = [s for s in result["steps_log"]
                          if s.startswith("left") or s.startswith("right")]
        assert len(lateral_entries) > 0, "Expected lateral entries in steps_log"


# ---------------------------------------------------------------------------
# Encounter detection
# ---------------------------------------------------------------------------

class TestCyclingRoadEncounter:
    """Battle/dialogue detection during cycling road movement."""

    @retry_on_rng("cycling_road_edge")
    def test_trainer_encounter_detected(self, emu: EmulatorClient):
        """Sliding into trainer sight range returns encounter with battle state."""
        from renegade_mcp.navigation import navigate_to
        # Trainer at (302, 601) — navigate straight south on x=304
        result = navigate_to(emu, 304, 610)
        assert result.get("reached_target") is False, "Should stop at trainer"
        assert "encounter" in result, "Expected encounter dict"
        enc = result["encounter"]
        assert enc["encounter"] == "battle", f"Expected battle encounter, got: {enc.get('encounter')}"
        # Should have dialogue (trainer pre-battle text)
        assert "dialogue" in enc, "Expected pre-battle dialogue"
        # Should have battle state ready
        assert "battle_state" in enc
        assert len(enc["battle_state"]) >= 2, "Expected at least 2 battlers"

    @retry_on_rng("cycling_road_edge")
    def test_clean_path_avoids_trainer(self, emu: EmulatorClient):
        """Navigating on a different column avoids the trainer entirely."""
        from renegade_mcp.navigation import navigate_to
        # Trainer is at x=302 — go to x=300 to avoid
        result = navigate_to(emu, 300, 610)
        assert result.get("reached_target") is True, (
            f"Should reach target avoiding trainer, got: {result.get('note', result)}"
        )
        assert "encounter" not in result, "Should not encounter trainer on different column"
