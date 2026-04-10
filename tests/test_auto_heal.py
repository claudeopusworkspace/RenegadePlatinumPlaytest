"""Tests for cross-map auto-heal in auto_grind.

Tests the auto_heal=True feature: finding nearest PC, navigating there,
healing, and returning to the grind position.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


# ---------------------------------------------------------------------------
# _find_nearest_pc — pure logic, no navigation
# ---------------------------------------------------------------------------


class TestFindNearestPc:
    """Test nearest PC detection from various locations."""

    def test_from_eterna_city(self, emu: EmulatorClient):
        """In Eterna City, nearest PC is Eterna's own."""
        load_state(emu, "test_eterna_city_overworld")
        from renegade_mcp.auto_grind import _find_nearest_pc
        from renegade_mcp.map_state import read_player_state

        map_id, px, py, _ = read_player_state(emu)
        result = _find_nearest_pc(emu, map_id, px, py)
        assert result is not None, "Should find a PC from Eterna City"
        assert result["city_code"] == "C04", f"Expected Eterna (C04), got {result['city_code']}"
        assert result["chunk_dist"] <= 1, f"Should be very close, got {result['chunk_dist']} chunks"

    def test_from_route203(self, emu: EmulatorClient):
        """From Route 203, nearest PC is Oreburgh City."""
        load_state(emu, "route203_trainers_cleared")
        from renegade_mcp.auto_grind import _find_nearest_pc
        from renegade_mcp.map_state import read_player_state

        map_id, px, py, _ = read_player_state(emu)
        result = _find_nearest_pc(emu, map_id, px, py)
        assert result is not None, "Should find a PC from Route 203"
        assert result["city_code"] == "C03", f"Expected Oreburgh (C03), got {result['city_code']}"
        assert result["chunk_dist"] <= 5, f"Should be nearby, got {result['chunk_dist']} chunks"

    def test_from_interior_returns_none(self, emu: EmulatorClient):
        """Interior maps not on the overworld matrix return None."""
        load_state(emu, "test_eterna_city_overworld")
        from renegade_mcp.auto_grind import _find_nearest_pc

        # Oreburgh Gate B1F (map 261) is not on any matrix
        result = _find_nearest_pc(emu, 261, 16, 10)
        assert result is None, "Interior maps should return None"


# ---------------------------------------------------------------------------
# _auto_heal_and_return — full integration
# ---------------------------------------------------------------------------


class TestAutoHealAndReturn:
    """Test the full auto-heal-and-return flow."""

    def test_heal_from_eterna_city(self, emu: EmulatorClient):
        """From Eterna City overworld, navigate to PC, heal, return."""
        load_state(emu, "test_eterna_city_overworld")
        from renegade_mcp.auto_grind import _auto_heal_and_return
        from renegade_mcp.map_state import read_player_state
        from renegade_mcp.data import map_table

        # Record starting position
        start_map, start_x, start_y, _ = read_player_state(emu)
        assert map_table().get(start_map, {}).get("code") == "C04"

        # Run auto heal (not in battle)
        result = _auto_heal_and_return(emu, in_battle=False, fainted=False)
        assert result.get("success"), f"Auto-heal failed: {result.get('error')}"

        # Verify we're back near the starting position (same map, within a few tiles)
        end_map, end_x, end_y, _ = read_player_state(emu)
        entry = map_table().get(end_map, {})
        # Should be back on Eterna City or very close
        assert entry.get("code", "").startswith("C04"), (
            f"Expected Eterna City area, got {entry.get('code')} (map {end_map})"
        )
        # Position should be close to start (within a few tiles of navigation variance)
        assert abs(end_x - start_x) <= 3, f"X drifted: {start_x} -> {end_x}"
        assert abs(end_y - start_y) <= 3, f"Y drifted: {start_y} -> {end_y}"

    def test_heal_from_route(self, emu: EmulatorClient):
        """From Route 203, auto-heal finds a reachable city and returns."""
        load_state(emu, "route203_trainers_cleared")
        from renegade_mcp.auto_grind import _auto_heal_and_return
        from renegade_mcp.map_state import read_player_state

        start_map, start_x, start_y, _ = read_player_state(emu)

        result = _auto_heal_and_return(emu, in_battle=False, fainted=False)
        assert result.get("success"), f"Auto-heal failed: {result.get('error')}"

        # Should return to approximately the same position
        end_map, end_x, end_y, _ = read_player_state(emu)
        assert abs(end_x - start_x) <= 3, f"X drifted: {start_x} -> {end_x}"
        assert abs(end_y - start_y) <= 3, f"Y drifted: {start_y} -> {end_y}"
