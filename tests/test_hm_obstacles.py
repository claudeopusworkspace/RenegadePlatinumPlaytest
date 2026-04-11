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
