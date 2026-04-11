"""Tests for HM obstacle auto-clearing in navigate_to.

Uses Wayne's E4 save states with full HM coverage.
These are state-changing tests — each reloads a save state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state


# ---------------------------------------------------------------------------
# Rock Smash auto-clear
# ---------------------------------------------------------------------------

class TestRockSmashAutoClear:
    """navigate_to auto-clears Rock Smash rocks when the obstacle path is shorter."""

    def test_navigate_through_rock(self, emu: EmulatorClient):
        """Walking through a Rock Smash rock clears it and reaches target."""
        do_load_state(emu, "hm_test_rock_smash_oreburgh_mine_b2f", redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # Player at (18, 28), rock at (19, 28), target at (21, 28)
        # Obstacle path: 3 steps right (through rock)
        # Clean path: 5 steps (around via row 29)
        result = navigate_to(emu, 21, 28)

        assert result["final"]["x"] == 21
        assert result["final"]["y"] == 28
        assert "obstacles_cleared" in result
        cleared = result["obstacles_cleared"]
        assert len(cleared) == 1
        assert cleared[0]["type"] == "rock_smash"
        assert cleared[0]["move"] == "Rock Smash"
        assert cleared[0]["x"] == 19
        assert cleared[0]["y"] == 28

    def test_clean_path_preferred_when_shorter(self, emu: EmulatorClient):
        """When clean path is shorter than obstacle path, takes clean path."""
        do_load_state(emu, "hm_test_rock_smash_oreburgh_mine_b2f", redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # Navigate south — clean path is just 1 step down, no obstacles needed
        result = navigate_to(emu, 18, 29)

        assert result["final"]["x"] == 18
        assert result["final"]["y"] == 29
        assert "obstacles_cleared" not in result

    def test_obstacle_path_only_when_required(self, emu: EmulatorClient):
        """When only path goes through obstacles and no clean path exists."""
        do_load_state(emu, "hm_test_rock_smash_oreburgh_mine_b2f", redetect_shift=True)
        from renegade_mcp.navigation import navigate_to, _read_position

        # Navigate to (20, 28) — 2 steps right through rock vs 4 steps around
        result = navigate_to(emu, 20, 28)

        assert result["final"]["x"] == 20
        assert result["final"]["y"] == 28
        # Should have cleared the rock at (19, 28)
        assert "obstacles_cleared" in result
        assert result["obstacles_cleared"][0]["x"] == 19

    def test_multiple_rocks_same_path(self, emu: EmulatorClient):
        """Navigate through two rocks on the same row."""
        do_load_state(emu, "hm_test_rock_smash_oreburgh_mine_b2f", redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # Rocks at (17, 28) and (19, 28), player at (18, 28)
        # Navigate to (16, 28) — must go through rock at (17, 28)
        result = navigate_to(emu, 16, 28)

        assert result["final"]["x"] == 16
        assert result["final"]["y"] == 28
        assert "obstacles_cleared" in result
        assert any(c["x"] == 17 for c in result["obstacles_cleared"])

    def test_field_move_availability_checked(self, emu: EmulatorClient):
        """BFS correctly detects Rock Smash availability from party + badges."""
        do_load_state(emu, "hm_test_rock_smash_oreburgh_mine_b2f", redetect_shift=True)
        from renegade_mcp.navigation import _get_field_move_availability

        field_moves = _get_field_move_availability(emu)
        assert field_moves["Rock Smash"] is True
        assert field_moves["Cut"] is True

    def test_obstacle_map_populated(self, emu: EmulatorClient):
        """Rocks are correctly classified in the obstacle_map."""
        do_load_state(emu, "hm_test_rock_smash_oreburgh_mine_b2f", redetect_shift=True)
        from renegade_mcp.map_state import get_map_state
        from renegade_mcp.navigation import _build_terrain_info

        state = get_map_state(emu)
        _, npc_set, obstacle_map = _build_terrain_info(state["terrain"], state["objects"])

        # Rocks at (19, 28) and (17, 28) should be in obstacle_map, not npc_set
        assert (19, 28) in obstacle_map
        assert (17, 28) in obstacle_map
        assert obstacle_map[(19, 28)]["type"] == "rock_smash"
        assert obstacle_map[(17, 28)]["type"] == "rock_smash"
        # Should NOT be in npc_set
        assert (19, 28) not in npc_set
        assert (17, 28) not in npc_set


# ---------------------------------------------------------------------------
# Surf auto-navigation
# ---------------------------------------------------------------------------

class TestSurfNavigation:
    """navigate_to auto-uses Surf to cross water when available.

    Uses Route 218 save state — player at (112, 754) on the east land strip,
    water canal to the west, land on far west side around x=98-103.
    """

    SAVE_STATE = "hm_test_surf_route218_at_water"

    def test_surf_field_move_available(self, emu: EmulatorClient):
        """Wayne's E4 save has Surf available (party + Fen Badge)."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import _get_field_move_availability

        field_moves = _get_field_move_availability(emu)
        assert field_moves["Surf"] is True

    def test_water_tiles_in_terrain(self, emu: EmulatorClient):
        """Water tiles are present in Route 218 terrain data."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.map_state import get_map_state
        from renegade_mcp.navigation import WATER_BEHAVIORS

        state = get_map_state(emu)
        assert state is not None

        water_count = 0
        for row in state["terrain"]:
            for val in row:
                behavior = val & 0x00FF
                if behavior in WATER_BEHAVIORS:
                    water_count += 1

        assert water_count > 0, "Expected water tiles in Route 218"

    def test_obstacle_bfs_finds_surf_path(self, emu: EmulatorClient):
        """Obstacle-aware BFS finds a path through water when Surf is available."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import (
            _bfs_pathfind,
            _bfs_pathfind_obstacles,
            _build_multi_chunk_terrain,
            _classify_objects_for_grid,
            _get_field_move_availability,
            _read_position,
        )
        from renegade_mcp.map_state import get_map_state

        _, px, py = _read_position(emu)
        state = get_map_state(emu)
        map_id = state["map_id"]
        field_moves = _get_field_move_availability(emu)

        # Target: west side of canal at (100, 756)
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, 100, 756)
        assert mc_result is not None
        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result
        npc_set, obstacle_map = _classify_objects_for_grid(
            state["objects"], grid_ox, grid_oy, grid_w, grid_h,
        )

        rel_px, rel_py = px - grid_ox, py - grid_oy
        rel_tx, rel_ty = 100 - grid_ox, 756 - grid_oy

        # Clean BFS should NOT find a path (water blocks)
        clean_path = _bfs_pathfind(
            terrain_info, npc_set | set(obstacle_map.keys()),
            rel_px, rel_py, rel_tx, rel_ty,
            width=grid_w, height=grid_h,
        )
        assert clean_path is None, "Clean BFS should not cross water"

        # Obstacle BFS with Surf SHOULD find a path
        obs_path, obs_crossed = _bfs_pathfind_obstacles(
            terrain_info, npc_set, obstacle_map,
            rel_px, rel_py, rel_tx, rel_ty,
            field_moves, width=grid_w, height=grid_h,
        )
        assert obs_path is not None, "Obstacle BFS should find a path through water"
        water_obs = [ob for ob in obs_crossed if ob["type"] == "water"]
        assert len(water_obs) > 0, "Path should include water obstacles"

    def test_navigate_across_water(self, emu: EmulatorClient):
        """navigate_to crosses water via Surf and reaches target on far side."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # Player at (112, 754) on east side, target on west side of canal.
        result = navigate_to(emu, 100, 756)

        assert "error" not in result, f"navigate_to failed: {result.get('error')}"
        assert "status" not in result, f"Got obstacle_choice: {result.get('message')}"
        assert result["final"]["x"] == 100
        assert result["final"]["y"] == 756
        assert "obstacles_cleared" in result
        surf_cleared = [c for c in result["obstacles_cleared"] if c["type"] == "water"]
        assert len(surf_cleared) >= 1
        assert surf_cleared[0]["move"] == "Surf"

    def test_navigate_back_via_bridge(self, emu: EmulatorClient):
        """After surfing west, navigating east uses the bridge (clean path)."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # First: cross water to the west
        result1 = navigate_to(emu, 100, 756)
        assert "obstacles_cleared" in result1

        # Now navigate back east — bridge provides a clean path, no Surf needed
        result2 = navigate_to(emu, 118, 756)
        assert "error" not in result2, f"Return trip failed: {result2.get('error')}"
        assert "obstacles_cleared" not in result2, "Bridge path should not need Surf"

    def test_surf_not_available_without_badge(self, emu: EmulatorClient):
        """BFS does not cross water when Surf is unavailable."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import (
            _bfs_pathfind_obstacles,
            _build_multi_chunk_terrain,
            _classify_objects_for_grid,
            _read_position,
        )
        from renegade_mcp.map_state import get_map_state

        _, px, py = _read_position(emu)
        state = get_map_state(emu)
        map_id = state["map_id"]

        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, 100, 756)
        assert mc_result is not None
        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result
        npc_set, obstacle_map = _classify_objects_for_grid(
            state["objects"], grid_ox, grid_oy, grid_w, grid_h,
        )

        rel_px, rel_py = px - grid_ox, py - grid_oy
        rel_tx, rel_ty = 100 - grid_ox, 756 - grid_oy

        # Simulate no Surf available
        no_surf = {"Rock Smash": True, "Cut": True, "Surf": False,
                   "Strength": False, "Waterfall": False, "Rock Climb": False}

        obs_path, obs_crossed = _bfs_pathfind_obstacles(
            terrain_info, npc_set, obstacle_map,
            rel_px, rel_py, rel_tx, rel_ty,
            no_surf, width=grid_w, height=grid_h,
        )
        water_obs = [ob for ob in obs_crossed if ob["type"] == "water"]
        assert len(water_obs) == 0, "BFS should not cross water without Surf"

    def test_surf_auto_navigate_types(self, emu: EmulatorClient):
        """Water type is included in AUTO_NAVIGATE_TYPES alongside Rock Smash/Cut."""
        from renegade_mcp.navigation import (
            AUTO_NAVIGATE_TYPES, CLEARABLE_TYPES, SURF_TYPES,
        )

        assert "water" in AUTO_NAVIGATE_TYPES
        assert "water" in SURF_TYPES
        assert "water" not in CLEARABLE_TYPES
        assert "rock_smash" in AUTO_NAVIGATE_TYPES
        assert "cut_tree" in AUTO_NAVIGATE_TYPES


# ---------------------------------------------------------------------------
# Rock Climb auto-navigation
# ---------------------------------------------------------------------------

class TestRockClimbNavigation:
    """navigate_to auto-uses Rock Climb to traverse cliff walls.

    Uses Veilstone City save state — player at (691, 617) south of a
    Rock Climb wall. The wall at (691, 615)/(691, 616) separates the
    gym area (west) from the main city. Clean path around = 68 steps.
    """

    SAVE_STATE = "hm_test_rock_climb_veilstone"

    def test_rock_climb_field_move_available(self, emu: EmulatorClient):
        """Wayne's E4 save has Rock Climb available (party + Icicle Badge)."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import _get_field_move_availability

        field_moves = _get_field_move_availability(emu)
        assert field_moves["Rock Climb"] is True

    def test_rock_climb_tiles_in_terrain(self, emu: EmulatorClient):
        """Rock Climb tiles (0x4A/0x4B) are present in Veilstone terrain."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.map_state import get_map_state
        from renegade_mcp.navigation import ROCK_CLIMB_BEHAVIORS

        state = get_map_state(emu)
        assert state is not None

        rc_count = 0
        for row in state["terrain"]:
            for val in row:
                behavior = val & 0x00FF
                if behavior in ROCK_CLIMB_BEHAVIORS:
                    rc_count += 1

        assert rc_count > 0, "Expected Rock Climb tiles in Veilstone City"

    def test_obstacle_bfs_finds_rock_climb_path(self, emu: EmulatorClient):
        """Obstacle-aware BFS finds a path through Rock Climb wall."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import (
            _bfs_pathfind,
            _bfs_pathfind_obstacles,
            _build_multi_chunk_terrain,
            _classify_objects_for_grid,
            _get_field_move_availability,
            _read_position,
        )
        from renegade_mcp.map_state import get_map_state

        _, px, py = _read_position(emu)
        state = get_map_state(emu)
        map_id = state["map_id"]
        field_moves = _get_field_move_availability(emu)

        # Target: other side of the Rock Climb wall
        target_x, target_y = 691, 614
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
        assert mc_result is not None
        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result
        npc_set, obstacle_map = _classify_objects_for_grid(
            state["objects"], grid_ox, grid_oy, grid_w, grid_h,
        )

        rel_px, rel_py = px - grid_ox, py - grid_oy
        rel_tx, rel_ty = target_x - grid_ox, target_y - grid_oy

        # Clean BFS should NOT find a path (wall blocks)
        clean_path = _bfs_pathfind(
            terrain_info, npc_set | set(obstacle_map.keys()),
            rel_px, rel_py, rel_tx, rel_ty,
            width=grid_w, height=grid_h,
        )
        assert clean_path is None, "Clean BFS should not cross Rock Climb wall"

        # Obstacle BFS with Rock Climb SHOULD find a path
        obs_path, obs_crossed = _bfs_pathfind_obstacles(
            terrain_info, npc_set, obstacle_map,
            rel_px, rel_py, rel_tx, rel_ty,
            field_moves, width=grid_w, height=grid_h,
        )
        assert obs_path is not None, "Obstacle BFS should find a path through Rock Climb wall"
        rc_obs = [ob for ob in obs_crossed if ob["type"] == "rock_climb"]
        assert len(rc_obs) >= 1, "Path should include rock_climb obstacles"

    def test_navigate_through_rock_climb_wall(self, emu: EmulatorClient):
        """navigate_to traverses Rock Climb wall and reaches target."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # Player at (691, 617), target at (691, 614) — 3 steps through wall
        result = navigate_to(emu, 691, 614)

        assert "error" not in result, f"navigate_to failed: {result.get('error')}"
        assert "status" not in result, f"Got obstacle status: {result.get('message')}"
        assert result["final"]["x"] == 691
        assert result["final"]["y"] == 614
        assert "obstacles_cleared" in result
        rc_cleared = [c for c in result["obstacles_cleared"] if c["type"] == "rock_climb"]
        assert len(rc_cleared) >= 1
        assert rc_cleared[0]["move"] == "Rock Climb"

    def test_navigate_continues_after_rock_climb(self, emu: EmulatorClient):
        """After climbing, player can continue navigating to a further target."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # First climb the wall to (691, 614)
        result1 = navigate_to(emu, 691, 614)
        assert "obstacles_cleared" in result1
        assert result1["final"]["x"] == 691
        assert result1["final"]["y"] == 614

        # Now navigate further from the top — should work without issues
        result2 = navigate_to(emu, 688, 612)
        assert "error" not in result2, f"Post-climb nav failed: {result2.get('error')}"
        assert result2["final"]["x"] == 688
        assert result2["final"]["y"] == 612

    def test_rock_climb_in_auto_navigate_types(self, emu: EmulatorClient):
        """rock_climb is included in AUTO_NAVIGATE_TYPES."""
        from renegade_mcp.navigation import (
            AUTO_NAVIGATE_TYPES, ROCK_CLIMB_TYPES, MULTI_TILE_HM_TYPES,
        )

        assert "rock_climb" in AUTO_NAVIGATE_TYPES
        assert "rock_climb" in ROCK_CLIMB_TYPES
        assert "rock_climb" in MULTI_TILE_HM_TYPES

    def test_rock_climb_not_available_without_badge(self, emu: EmulatorClient):
        """BFS does not cross Rock Climb wall when move is unavailable."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import (
            _bfs_pathfind_obstacles,
            _build_multi_chunk_terrain,
            _classify_objects_for_grid,
            _read_position,
        )
        from renegade_mcp.map_state import get_map_state

        _, px, py = _read_position(emu)
        state = get_map_state(emu)
        map_id = state["map_id"]

        target_x, target_y = 691, 614
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
        assert mc_result is not None
        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result
        npc_set, obstacle_map = _classify_objects_for_grid(
            state["objects"], grid_ox, grid_oy, grid_w, grid_h,
        )

        rel_px, rel_py = px - grid_ox, py - grid_oy
        rel_tx, rel_ty = target_x - grid_ox, target_y - grid_oy

        # Simulate no Rock Climb available
        no_rc = {"Rock Smash": True, "Cut": True, "Surf": True,
                 "Strength": False, "Waterfall": True, "Rock Climb": False}

        obs_path, obs_crossed = _bfs_pathfind_obstacles(
            terrain_info, npc_set, obstacle_map,
            rel_px, rel_py, rel_tx, rel_ty,
            no_rc, width=grid_w, height=grid_h,
        )
        rc_obs = [ob for ob in obs_crossed if ob["type"] == "rock_climb"]
        assert len(rc_obs) == 0, "BFS should not cross Rock Climb wall without the move"


# ---------------------------------------------------------------------------
# Waterfall auto-navigation
# ---------------------------------------------------------------------------

class TestWaterfallNavigation:
    """navigate_to auto-uses Waterfall to traverse waterfall tiles.

    Uses Pokemon League outdoor save state — player at (847, 560),
    path south requires Surf across water + Waterfall at a waterfall tile.
    """

    SAVE_STATE = "hm_test_surf_waterfall_pokemon_league"

    def test_waterfall_field_move_available(self, emu: EmulatorClient):
        """Wayne's E4 save has Waterfall available (party + Beacon Badge)."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import _get_field_move_availability

        field_moves = _get_field_move_availability(emu)
        assert field_moves["Waterfall"] is True

    def test_waterfall_tiles_in_terrain(self, emu: EmulatorClient):
        """Waterfall tiles (0x13) are present in the Pokemon League terrain."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.map_state import get_map_state
        from renegade_mcp.navigation import WATERFALL_BEHAVIOR

        state = get_map_state(emu)
        assert state is not None

        wf_count = 0
        for row in state["terrain"]:
            for val in row:
                behavior = val & 0x00FF
                if behavior == WATERFALL_BEHAVIOR:
                    wf_count += 1

        assert wf_count > 0, "Expected Waterfall tiles in Pokemon League area"

    def test_obstacle_bfs_finds_waterfall_path(self, emu: EmulatorClient):
        """Obstacle-aware BFS finds a path through Surf + Waterfall."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import (
            _bfs_pathfind_obstacles,
            _build_multi_chunk_terrain,
            _classify_objects_for_grid,
            _get_field_move_availability,
            _read_position,
        )
        from renegade_mcp.map_state import get_map_state

        _, px, py = _read_position(emu)
        state = get_map_state(emu)
        map_id = state["map_id"]
        field_moves = _get_field_move_availability(emu)

        # Target: south of waterfall
        target_x, target_y = 847, 575
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
        assert mc_result is not None
        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result
        npc_set, obstacle_map = _classify_objects_for_grid(
            state["objects"], grid_ox, grid_oy, grid_w, grid_h,
        )

        rel_px, rel_py = px - grid_ox, py - grid_oy
        rel_tx, rel_ty = target_x - grid_ox, target_y - grid_oy

        obs_path, obs_crossed = _bfs_pathfind_obstacles(
            terrain_info, npc_set, obstacle_map,
            rel_px, rel_py, rel_tx, rel_ty,
            field_moves, width=grid_w, height=grid_h,
        )
        assert obs_path is not None, "Obstacle BFS should find path through water + waterfall"
        wf_obs = [ob for ob in obs_crossed if ob["type"] == "waterfall"]
        assert len(wf_obs) >= 1, "Path should include waterfall obstacle"
        water_obs = [ob for ob in obs_crossed if ob["type"] == "water"]
        assert len(water_obs) >= 1, "Path should also include water obstacles"

    def test_navigate_through_waterfall(self, emu: EmulatorClient):
        """navigate_to crosses water + waterfall and reaches target."""
        do_load_state(emu, self.SAVE_STATE, redetect_shift=True)
        from renegade_mcp.navigation import navigate_to

        # Player at (847, 560), target south past water and waterfall
        result = navigate_to(emu, 847, 575)

        assert "error" not in result, f"navigate_to failed: {result.get('error')}"
        assert "status" not in result, f"Got obstacle status: {result.get('message')}"
        assert result["final"]["x"] == 847
        assert result["final"]["y"] == 575
        assert "obstacles_cleared" in result
        wf_cleared = [c for c in result["obstacles_cleared"] if c["type"] == "waterfall"]
        assert len(wf_cleared) >= 1
        assert wf_cleared[0]["move"] == "Waterfall"
        # Should also include Surf obstacles
        surf_cleared = [c for c in result["obstacles_cleared"] if c["type"] == "water"]
        assert len(surf_cleared) >= 1

    def test_waterfall_in_auto_navigate_types(self, emu: EmulatorClient):
        """waterfall is included in AUTO_NAVIGATE_TYPES."""
        from renegade_mcp.navigation import (
            AUTO_NAVIGATE_TYPES, WATERFALL_TYPES, MULTI_TILE_HM_TYPES,
        )

        assert "waterfall" in AUTO_NAVIGATE_TYPES
        assert "waterfall" in WATERFALL_TYPES
        assert "waterfall" in MULTI_TILE_HM_TYPES


# ---------------------------------------------------------------------------
# GFX ID correctness
# ---------------------------------------------------------------------------

class TestHMObstacleGfxIds:
    """Verify HM obstacle graphics_id → type mapping is correct."""

    def test_gfx_id_mapping(self, emu: EmulatorClient):
        """GFX IDs match obj_event_gfx.txt definitions."""
        from renegade_mcp.navigation import HM_OBSTACLES, CLEARABLE_OBSTACLES, PUZZLE_OBSTACLES

        # Verify correct GFX IDs (from data/obj_event_gfx.txt)
        assert 84 in HM_OBSTACLES  # STRENGTH_BOULDER
        assert 85 in HM_OBSTACLES  # ROCK_SMASH
        assert 86 in HM_OBSTACLES  # CUT_TREE

        assert HM_OBSTACLES[84]["type"] == "strength_boulder"
        assert HM_OBSTACLES[85]["type"] == "rock_smash"
        assert HM_OBSTACLES[86]["type"] == "cut_tree"

        assert CLEARABLE_OBSTACLES == {85, 86}
        assert PUZZLE_OBSTACLES == {84}
