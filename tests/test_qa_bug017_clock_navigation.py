"""Regression tests for QA BUG-017.

BUG-017: ``navigate_to`` / ``interact_with`` silently teleport the player to
(15, 13) when pathing across Eterna Gym (map 67) floral-clock tiles.

Root cause: the Eterna Gym BDHC defines an L0 strip (height = -2) at row 20
that separates the northern clock-area L1 perimeter from the southern warp
L1 perimeter. The only L1↔L0 height delta on this map is 2 units — the game
engine crosses it without a ramp animation, but the 3D BFS treated the two
levels as disconnected and refused to plan a path around a blocked clock
arm. With the south arm fountain-blocked, repath loops exhausted without
ever considering the outer L1 perimeter route.

Fix: ``STEPPABLE_HEIGHT`` threshold (nav_constants.py) + updated
``_tile_on_level`` in ``_bfs_pathfind_level`` accept same-level neighbours
whose defined elevation is within 4 height-units of the current level. Also
wired 3D BFS into ``interact_with`` so it respects elevation (previously 2D
only).

Save state: ``bug_navigate_eterna_gym_clock_tile_stuck`` (Eterna Gym, player
at (15, 13) L2 on the east clock arm, post-trainer-rotation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestQaBug017ClockNavigation:
    """navigate_to / interact_with across Eterna Gym clock tiles."""

    def test_setup_save_state(self, emu: EmulatorClient):
        """Sanity: save state loads at the expected position."""
        load_state(emu, "bug_navigate_eterna_gym_clock_tile_stuck")
        from renegade_mcp.map_state import get_map_state

        state = get_map_state(emu)
        assert state["map_id"] == 67, "Expected Eterna Gym (map 67)"
        assert state["px"] == 15 and state["py"] == 13, (
            f"Expected player at (15, 13), got ({state['px']}, {state['py']})"
        )

    def test_steppable_height_constant_exists(self, emu: EmulatorClient):
        """STEPPABLE_HEIGHT is the new constant driving the fix."""
        from renegade_mcp.nav_constants import STEPPABLE_HEIGHT
        # Must accept L0/L1 (diff 2) but reject L1/L2 (diff 16)
        assert 2 <= STEPPABLE_HEIGHT < 16, (
            f"STEPPABLE_HEIGHT={STEPPABLE_HEIGHT} must cover L0/L1 dip "
            f"but not L1/L2 ramp height"
        )

    def test_bfs_allows_l0_l1_crossing(self, emu: EmulatorClient):
        """3D BFS finds an L1 path that crosses the row-20 L0 strip."""
        load_state(emu, "bug_navigate_eterna_gym_clock_tile_stuck")
        from renegade_mcp.map_state import (
            analyze_elevation, get_land_data_id, get_map_state, parse_bdhc,
            read_player_height,
        )
        from renegade_mcp.pathfinding import (
            _bfs_pathfind_level, _build_terrain_info, _height_to_level,
        )

        state = get_map_state(emu)
        terrain_info, npc_set, _ = _build_terrain_info(
            state["terrain"], state["objects"],
        )
        bdhc = parse_bdhc(get_land_data_id(emu, 67, state["px"], state["py"]))
        elev = analyze_elevation(bdhc, state["terrain"])

        # Starting from (4, 13) on L1 (west arm end, off the clock), BFS on
        # L1 must find a path south to (11, 27) by crossing the L0 strip at
        # row 20. Before the fix, this returned None.
        path, _ = _bfs_pathfind_level(
            terrain_info, npc_set, elev,
            start_x=4, start_y=13, goal_x=11, goal_y=27,
            current_level=1,
        )
        assert path is not None, (
            "L1 BFS must cross L0 dip — got None (STEPPABLE_HEIGHT "
            "threshold not applied?)"
        )
        # Path must step through row 20 (the L0 strip) to reach the south
        # perimeter.
        cy = 13
        ys = []
        for d in path:
            if d == "down":
                cy += 1
            elif d == "up":
                cy -= 1
            ys.append(cy)
        assert any(y == 20 for y in ys), (
            f"Path should traverse row 20 (L0 strip); y-values: {ys}"
        )

    def test_navigate_to_south_warp_from_east_arm(self, emu: EmulatorClient):
        """navigate_to(11, 27) from bug state reaches the exit warp.

        Original failure: path collapsed to "warp_failed, repaths=15,
        final=(15,13)". Post-fix: 3D BFS routes around a blocked south arm
        via the outer L1 perimeter and the player walks through the south
        warp into Eterna City (map 65).
        """
        load_state(emu, "bug_navigate_eterna_gym_clock_tile_stuck")
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, 11, 27)
        assert "warp_failed" not in result, (
            f"warp_failed: {result.get('note')}"
        )
        final = result.get("final", {})
        assert final.get("map_id") == 65, (
            f"Expected to exit to Eterna City (map 65), got "
            f"map_id={final.get('map_id')} at ({final.get('x')}, "
            f"{final.get('y')})"
        )

    def test_interact_with_breeder_east_from_east_arm(self, emu: EmulatorClient):
        """interact_with Breeder (index 4, (20, 17)) completes navigation.

        BUG-017 also manifested in interact_with (it used 2D BFS, ignoring
        elevation). Post-fix: 3D BFS finds an adjacent tile on L1 via the
        east arm → east L1-floor transition.
        """
        load_state(emu, "bug_navigate_eterna_gym_clock_tile_stuck")
        from renegade_mcp.interaction import interact_with

        result = interact_with(emu, object_index=4)
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        # Either navigation ran successfully (path with no stopped_early)
        # or dialogue/battle was auto-triggered — either outcome means we
        # made it adjacent to the target.
        if result.get("stopped_early"):
            # A stopped_early without dialogue/encounter means the same
            # symptom as the bug.  If an encounter or dialogue landed, the
            # nav actually reached the trainer.
            assert (
                result.get("encounter") or result.get("dialogue")
            ), (
                f"stopped_early without encounter/dialogue — likely "
                f"BUG-017 regression: {result}"
            )
