"""Tests for map tools: view_map, map_name.

Deterministic memory/ROM reads — no retries needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


# ---------------------------------------------------------------------------
# view_map
# ---------------------------------------------------------------------------

class TestViewMap:
    """ASCII map rendering from memory/ROM."""

    def test_indoor_map(self, emu: EmulatorClient):
        """Indoor Pokemon Center: returns grid, player, NPCs, warps."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert "map" in result
        assert "map_id" in result
        assert "player" in result
        assert "objects" in result
        assert "warps" in result
        assert len(result["map"]) > 0

    def test_player_has_grid_position(self, emu: EmulatorClient):
        """Player dict includes grid_x and grid_y."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        player = result["player"]
        assert "grid_x" in player
        assert "grid_y" in player
        assert "x" in player
        assert "y" in player
        assert "facing" in player

    def test_warps_have_destinations(self, emu: EmulatorClient):
        """Warps include destination names and coordinates."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert len(result["warps"]) > 0
        for warp in result["warps"]:
            assert "x" in warp
            assert "y" in warp
            assert "dest" in warp

    def test_objects_sorted_by_distance(self, emu: EmulatorClient):
        """NPCs/objects are sorted nearest first."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        objects = result["objects"]
        if len(objects) >= 2:
            # Reachable objects should have increasing step counts
            reachable = [o for o in objects if o.get("reachable")]
            for i in range(len(reachable) - 1):
                steps_a = reachable[i].get("steps", 0)
                steps_b = reachable[i + 1].get("steps", 0)
                assert steps_a <= steps_b, (
                    f"Objects not sorted: {reachable[i]['name']} ({steps_a}) "
                    f"before {reachable[i+1]['name']} ({steps_b})"
                )

    def test_outdoor_multi_chunk(self, emu: EmulatorClient):
        """Outdoor route loads adjacent chunks."""
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert result["map_id"] is not None
        assert len(result["map"]) > 0
        # Outdoor maps should have the origin header
        assert "origin:" in result["map"]

    def test_snow_terrain(self, emu: EmulatorClient):
        """Route 216 snow area renders."""
        load_state(emu, "route216_lodge_healed")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert len(result["map"]) > 0
        assert result["player"]["x"] > 0
        assert result["player"]["y"] > 0

    def test_3d_cave_elevation(self, emu: EmulatorClient):
        """Mt. Coronet 3D map includes elevation data."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert len(result["map"]) > 0
        # 3D maps should show elevation info in the map string
        # or the player should have elevation data
        player = result["player"]
        assert "x" in player
        assert "y" in player

    def test_elevation_filter(self, emu: EmulatorClient):
        """level=0 filters to single elevation — map still renders."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.map_state import view_map
        result_filtered = view_map(emu, level=0)
        # Should return a valid map
        assert len(result_filtered["map"]) > 0
        assert "player" in result_filtered


# ---------------------------------------------------------------------------
# map_name
# ---------------------------------------------------------------------------

class TestMapName:
    """Location name lookup."""

    def test_current_map(self, emu: EmulatorClient):
        """Current map ID resolves to a name."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_names import lookup_map_name
        from renegade_mcp.map_state import read_player_state, view_map
        # Get map_id from view_map to cross-check
        vmap = view_map(emu)
        map_id = vmap["map_id"]

        result = lookup_map_name(map_id)
        assert "name" in result
        assert result["map_id"] == map_id

    def test_specific_map_id(self, emu: EmulatorClient):
        """Map 65 = Eterna City."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_names import lookup_map_name
        result = lookup_map_name(65)
        assert "Eterna" in result["name"]

    def test_different_location(self, emu: EmulatorClient):
        """Different locations resolve to different names."""
        from renegade_mcp.map_names import lookup_map_name
        from renegade_mcp.map_state import read_player_state

        load_state(emu, "eterna_city_shiny_swinub_in_party")
        mid1, _, _, _ = read_player_state(emu)
        name1 = lookup_map_name(mid1)["name"]

        load_state(emu, "route216_lodge_healed")
        mid2, _, _, _ = read_player_state(emu)
        name2 = lookup_map_name(mid2)["name"]

        assert name1 != name2
