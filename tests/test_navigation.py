"""Tests for navigation tools: navigate, navigate_to, interact_with, seek_encounter.

State-changing tools — many tests use retry_on_rng for encounter RNG.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# navigate (manual walk)
# ---------------------------------------------------------------------------

class TestNavigate:
    """Manual directional walking."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_simple_walk(self, emu: EmulatorClient):
        """Walk a short path — position changes by expected amount."""
        from renegade_mcp.navigation import navigate_manual
        from renegade_mcp.map_state import read_player_state
        _, x_before, y_before, _ = read_player_state(emu)
        result = navigate_manual(emu, "d2 r3")
        _, x_after, y_after, _ = read_player_state(emu)
        assert result["steps"] == 5, f"Expected 5 steps, got {result['steps']}"
        assert x_after == x_before + 3, f"Expected x+3, got {x_after} (was {x_before})"
        assert y_after == y_before + 2, f"Expected y+2, got {y_after} (was {y_before})"

    @retry_on_rng("test_eterna_city_overworld")
    def test_walk_into_wall(self, emu: EmulatorClient):
        """Walking into a wall returns error with blocked step info."""
        from renegade_mcp.navigation import navigate_manual
        # Walk north a lot — should detect wall before moving
        result = navigate_manual(emu, "u20")
        # Path validation catches walls before movement
        assert "error" in result, f"Expected error for wall collision, got: {list(result.keys())}"
        assert result.get("blocked_step", 0) > 0, (
            f"Expected blocked_step > 0, got: {result.get('blocked_step')}"
        )

    @retry_on_rng("test_eterna_city_overworld")
    def test_walk_triggers_warp(self, emu: EmulatorClient):
        """Walking into the Pokemon Center door triggers a map transition."""
        from renegade_mcp.navigation import navigate_manual
        # From (305, 530) facing down, walk up into the PC door
        result = navigate_manual(emu, "u1")
        # Should detect warp — start and final map IDs differ
        assert "start" in result and "final" in result, (
            f"Expected start/final position dicts, got: {list(result.keys())}"
        )
        assert result["start"]["map_id"] != result["final"]["map_id"], (
            f"Expected map transition, but stayed on map {result['start']['map_id']}"
        )

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_flee_encounters(self, emu: EmulatorClient):
        """flee_encounters auto-flees wild battles during walk."""
        from renegade_mcp.navigation import navigate_manual
        from renegade_mcp.map_state import read_player_state
        _, _, _, _ = read_player_state(emu)
        # Walk a long path through grass — may trigger encounters
        result = navigate_manual(emu, "d5 u5 d5 u5", flee_encounters=True)
        # Should complete the full walk
        assert "final" in result, f"Expected final position, got: {list(result.keys())}"
        assert result["steps"] > 0


class TestBug044StartPreservedAcrossFleeLoop:
    """BUG-044 start-preservation: when `navigate_to(flee_encounters=True)`
    retries after a wild encounter, the returned `start` field must reflect
    the player's position at the original call, not the post-retry
    intermediate position. Exposed by slope overshoot: the slope helper
    drifts the player past the target, the retry re-invokes
    `_navigate_to_impl` from the overshoot tile, and the final result's
    `start` used to leak that intermediate tile.
    """

    def test_start_preserved_after_flee_retry(self, emu: EmulatorClient):
        """Bike slope + flee encounters: returned start == player's initial
        position, not the intermediate tile the retry-loop re-BFS'd from."""
        load_state(emu, "bug_bike_slope_turn_into_approach")
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.nav_constants import _read_position
        _, initial_x, initial_y = _read_position(emu)
        # Target that crosses the slope — slope overshoot + wild encounters
        # forces multiple _navigate_to_impl iterations.
        result = navigate_to(emu, 7, 25, flee_encounters=True)
        assert "start" in result
        assert (result["start"]["x"], result["start"]["y"]) == (initial_x, initial_y), (
            f"start {result['start']} should equal initial position "
            f"({initial_x}, {initial_y}) regardless of how many flee retries happened"
        )


# ---------------------------------------------------------------------------
# navigate_to (BFS pathfind)
# ---------------------------------------------------------------------------

class TestNavigateTo:
    """BFS pathfinding navigation."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_nearby_tile(self, emu: EmulatorClient):
        """Navigate to nearby reachable tile — arrives at target."""
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import read_player_state
        _, start_x, start_y, _ = read_player_state(emu)
        target_y = start_y + 3
        result = navigate_to(emu, start_x, target_y)
        assert "final" in result, f"Expected final position, got: {list(result.keys())}"
        assert result["final"]["y"] == target_y, (
            f"Expected to arrive at y={target_y}, got y={result['final']['y']}"
        )

    @retry_on_rng("test_eterna_city_overworld")
    def test_navigate_to_warp(self, emu: EmulatorClient):
        """Navigate to a door — triggers warp or arrives at door tile."""
        from renegade_mcp.navigation import navigate_to
        # Navigate to the mart door at (310, 539)
        result = navigate_to(emu, 310, 539)
        assert result.get("door_entered") or result.get("new_map") or (
            "final" in result and result["final"]["x"] == 310
        ), f"Expected warp or arrival at door, got: {result.get('final')}"

    @retry_on_rng("test_eterna_city_overworld")
    def test_unreachable_tile_diagnostics(self, emu: EmulatorClient):
        """Unreachable tile returns diagnostics with diagram."""
        from renegade_mcp.navigation import navigate_to
        # Navigate to a tile inside a building (unreachable from outside)
        result = navigate_to(emu, 295, 518)
        # Should return failure diagnostics
        assert "error" in result or "diagram" in result, (
            f"Expected error or diagram for unreachable tile, got: {list(result.keys())}"
        )

    def test_sign_blocking(self, emu: EmulatorClient):
        """BFS avoids sign activation tile — arrives without triggering sign."""
        load_state(emu, "debug_signpost_blocking_navigate")
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 355, 531)
        assert "error" not in result, f"Navigation should succeed past sign, got error: {result.get('error')}"
        assert "final" in result, f"Expected final position, got: {list(result.keys())}"
        assert result["final"]["x"] == 355, f"Should arrive at x=355, got {result['final']['x']}"

    @retry_on_rng("debug_coronet218_3d_path_blocked")
    def test_3d_elevation(self, emu: EmulatorClient):
        """3D elevation pathfinding in multi-chunk Mt. Coronet — reaches warp."""
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 29, 35, flee_encounters=True)
        assert "error" not in result, f"Navigation failed: {result.get('error')}"
        assert "final" in result, f"Expected final position, got: {list(result.keys())}"
        # Warp at (29, 35) leads to Route 211
        assert result.get("door_entered") or result["final"]["map_id"] == 366, (
            f"Expected warp to Route 211, got: {result['final']}"
        )

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_flee_encounters_navigation(self, emu: EmulatorClient):
        """flee_encounters auto-flees during BFS navigation — arrives at target."""
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import read_player_state
        _, x, y, _ = read_player_state(emu)
        target_x = x + 3
        result = navigate_to(emu, target_x, y, flee_encounters=True)
        assert "final" in result, f"Expected final position, got: {list(result.keys())}"
        assert result["final"]["x"] == target_x, (
            f"Expected arrival at x={target_x}, got {result['final']['x']}"
        )

    @retry_on_rng("test_eterna_city_overworld")
    def test_position_dict_has_map_info(self, emu: EmulatorClient):
        """Position dicts include map name and coordinate info."""
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import read_player_state
        _, x, y, _ = read_player_state(emu)
        result = navigate_to(emu, x + 2, y)
        assert "final" in result, "Expected final position dict"
        final = result["final"]
        assert "x" in final, "Position dict missing x"
        assert "y" in final, "Position dict missing y"
        assert "map" in final or "map_id" in final, "Position dict missing map info"

    def test_short_path_indoor(self, emu: EmulatorClient):
        """Short path inside Pokemon Center — arrives at target."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.navigation import navigate_to
        # Target (8,7) — open floor tile, no NPCs. (10,6) was blocked by Idol NPC.
        result = navigate_to(emu, 8, 7)
        assert "final" in result, f"Expected final position, got: {list(result.keys())}"
        assert result["final"]["x"] == 8 and result["final"]["y"] == 7, (
            f"Expected arrival at (8,7), got ({result['final']['x']},{result['final']['y']})"
        )


class TestBikeRampBfsEdges:
    """BFS adds a jump edge across bike-ramp tiles (0xD7 east, 0xD8 west).

    The ramp tile is hard-blocked on foot; on a bicycle in fast gear,
    stepping INTO the ramp in the matching direction with enough momentum
    launches the player 5 tiles from the approach tile — ramp tile + 4
    (`MOVEMENT_ACTION_JUMP_FARTHER_EAST`, pokeplatinum
    src/unk_0205F180.c:613-629 + src/unk_020655F4.c:994, empirically
    verified in scripts/spike_ramp_poll_release.py: release button at
    ramp tile and idle 32+ frames → player lands at ramp+4). BFS
    represents the jump as a single directional edge from the approach
    tile (ramp - 1) to the landing tile (ramp + 4), skipping the ramp
    tile itself and whatever walls sit in the intermediate tiles.

    The engine requires momentum to fire the jump. Empirically 0-2
    approach tiles fail, 3+ succeed; we use BIKE_RAMP_RUNWAY_TILES=4 for
    cold-start safety margin. BFS admits the edge only when the
    straight-line approach in the ramp direction is long enough.
    """

    SAVE_STATE = "session31_wayward_cave_bike_ramps"

    def test_ramp_landing_helper_east(self):
        """_bike_ramp_landing returns the approach+5 landing when the ramp
        faces east, the landing is passable, and momentum is sufficient."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        # 9-wide row with approach at (3, 0), ramp at (4, 0), landing at (8, 0).
        # Tiles behind approach (0..2) are passable → geometric runway check
        # succeeds even without an explicit momentum arg.
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 4]
        landing = _bike_ramp_landing(grid, 3, 0, "right", 1, 0, width=9, height=1)
        assert landing == (8, 0)

    def test_ramp_landing_wrong_direction(self):
        """Ramp only triggers in its facing direction — approaching a
        ramp_E from the east (moving left) must not produce a jump."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 4]
        # Stepping left from (5, 0): neighbor (4, 0) is ramp_E but facing
        # east doesn't match the westward approach direction.
        landing = _bike_ramp_landing(grid, 5, 0, "left", -1, 0, width=9, height=1)
        assert landing is None

    def test_ramp_landing_blocked_landing(self):
        """If the landing tile is impassable, the ramp edge does not fire."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        # Approach passable, ramp, then walls — landing at (8, 0) blocked.
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(False, 0x00)] * 4]
        landing = _bike_ramp_landing(grid, 3, 0, "right", 1, 0, width=9, height=1)
        assert landing is None

    def test_ramp_landing_insufficient_runway(self):
        """Too-short straight-line approach must reject the ramp edge.

        With only 2 passable tiles behind the approach tile, the BFS cannot
        supply enough momentum for the jump to fire. Matches spike finding
        that 0-2 approach tiles fail on-device.
        """
        from renegade_mcp.pathfinding import _bike_ramp_landing
        # Only 2 passable tiles before approach (wall at col 0). Approach at
        # (3, 0), ramp at (4, 0), landing at (8, 0).
        grid = [[(False, 0x00)] + [(True, 0x08)] * 3 + [(False, 0xD7)]
                + [(True, 0x08)] * 4]
        landing = _bike_ramp_landing(grid, 3, 0, "right", 1, 0, width=9, height=1)
        assert landing is None

    def test_ramp_landing_momentum_override(self):
        """Explicit `momentum` arg from a momentum-aware BFS bypasses the
        geometric fallback — a landing after a prior ramp can chain even
        when the intermediate runway is too short geometrically."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        from renegade_mcp.nav_constants import BIKE_RAMP_RUNWAY_TILES
        # Short geometric runway (1 tile) but momentum=RUNWAY-1 supplied.
        # Approach at (2, 0), ramp at (3, 0), landing = 2 + 5 = (7, 0).
        grid = [[(False, 0x00)] * 2 + [(True, 0x08), (False, 0xD7)]
                + [(True, 0x08)] * 4]
        landing = _bike_ramp_landing(
            grid, 2, 0, "right", 1, 0, width=8, height=1,
            momentum=BIKE_RAMP_RUNWAY_TILES - 1,
        )
        assert landing == (7, 0)

    def test_2d_bfs_crosses_ramp_in_wayward_cave(self, emu: EmulatorClient):
        """From the west-chamber corridor, the 2D BFS must reach the landing
        tile (14, 17) past the east ramp at (10, 17). Fast-gear jump lands
        4 tiles past the ramp (5 from approach); (14, 17) is the first
        passable landing on row 17 in Wayward Cave B1F."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.pathfinding import (
            _bfs_reachable, _build_multi_chunk_terrain,
        )
        map_id, px, py = _read_position(emu)
        ti, ox, oy, w, h = _build_multi_chunk_terrain(
            emu, map_id, px, py, 43, 38,
        )
        reach = _bfs_reachable(ti, set(), px - ox, py - oy, w, h)
        assert (14 - ox, 17 - oy) in reach, (
            "2D BFS must reach ramp landing (14, 17) from the player "
            "corridor via the ramp_E at (10, 17); got "
            f"{len(reach)} tiles, ramp edge missing."
        )

    def test_2d_bfs_rejects_wrong_direction_approach(self, emu: EmulatorClient):
        """A ramp_E at (10, 17) must NOT be usable from the east side
        (going left / west) — that direction doesn't trigger the jump."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.pathfinding import (
            _bfs_reachable, _build_multi_chunk_terrain, _bike_ramp_landing,
        )
        map_id, px, py = _read_position(emu)
        ti, ox, oy, w, h = _build_multi_chunk_terrain(
            emu, map_id, px, py, 43, 38,
        )
        # (11, 17) reachable east-to-west attempt via the ramp_E — helper
        # must refuse the wrong-facing approach regardless of passability.
        landing = _bike_ramp_landing(
            ti, 11 - ox, 17 - oy, "left", -1, 0, w, h,
        )
        assert landing is None, (
            "ramp_E must not fire when approached from the east "
            f"(direction='left'); got landing {landing}"
        )

    def test_2d_bfs_chains_ramps_via_momentum_carry(self):
        """Momentum-aware BFS admits a second ramp whose intermediate
        runway is geometrically too short, because the prior ramp's
        landing carries full momentum into the next approach.

        Layout (single row, east-facing ramps at cols 6 and 11):

            0 1 2 3 4 5 R 7 8 9 10 R 12 13 14 15
                       ^           ^
                       ramp1       ramp2

        Cols 7-9 (mid-jump of ramp1) and 12-14 (mid-jump of ramp2) are
        walls, so the 3 tiles behind ramp2's approach (col 10) contain
        all walls — the geometric fallback would reject ramp2. Only
        momentum carry-through from landing (10, 0) admits the chain to
        landing (15, 0). With BIKE_RAMP_JUMP_TILES=5, ramp1's landing
        is exactly ramp2's approach (both col 10), so no intermediate
        walk step is needed.
        """
        from renegade_mcp.pathfinding import _bfs_reachable, _bfs_pathfind
        row: list[tuple[bool, int]] = []
        for i in range(16):
            if i in (6, 11):
                row.append((False, 0xD7))        # east ramp
            elif i in (7, 8, 9, 12, 13, 14):
                row.append((False, 0x00))        # mid-jump walls
            else:
                row.append((True, 0x08))         # passable
        grid = [row]

        reach = _bfs_reachable(grid, set(), 0, 0, width=16, height=1)
        assert (10, 0) in reach, "ramp1 landing (10, 0) must be reachable"
        assert (15, 0) in reach, (
            "ramp2 landing (15, 0) must be reachable via momentum carry "
            f"from ramp1 — got reach={sorted(reach)}"
        )

        path = _bfs_pathfind(grid, set(), 0, 0, 15, 0, width=16, height=1)
        assert path is not None, "path to (15, 0) must exist via chained ramps"
        # 5 walks + ramp1 + ramp2 = 7 edges (ramp1 lands exactly on ramp2's
        # approach tile, so no intermediate walk edge is needed).
        assert len(path) == 7, (
            f"Expected 7-edge chained path (5 walk + ramp + ramp), "
            f"got {len(path)}: {path}"
        )
        assert path.count("right") == 7

    def test_2d_bfs_turn_resets_momentum_before_ramp(self):
        """A ramp requires momentum in its facing direction. A BFS path
        that turns into the approach tile has momentum=1 (just the turn
        step) and cannot fire the ramp. Verifies the turn-reset rule
        doesn't regress now that the geometric fallback is disabled for
        momentum-aware callers.

        Layout:

          row 0:  ........ramp. (approach from 3 tiles of east runway)
          row 1:  ........ <- alt approach: player must come from below
          row 2:  ........

        The only reachable path to the ramp approach forces an up-turn
        onto the approach tile, leaving just 1 tile of east momentum.
        """
        from renegade_mcp.pathfinding import _bfs_reachable
        # 11-wide, 3-tall grid. Walls block horizontal travel on row 0
        # except for the final approach tile + ramp + landing.
        width, height = 11, 3
        grid = [[(False, 0x00)] * width for _ in range(height)]
        # Fill row 2 fully passable (travel lane).
        for x in range(width):
            grid[2][x] = (True, 0x08)
        # Fill column 4 passable (vertical channel up to the approach).
        for y in range(height):
            grid[y][4] = (True, 0x08)
        # Row 0: approach at x=4, ramp at x=5, landing at x=9 (= approach+5).
        grid[0][4] = (True, 0x08)
        grid[0][5] = (False, 0xD7)
        grid[0][6] = (False, 0x00)
        grid[0][7] = (False, 0x00)
        grid[0][8] = (False, 0x00)
        grid[0][9] = (True, 0x08)

        reach = _bfs_reachable(grid, set(), 0, 2, width=width, height=height)
        assert (4, 0) in reach, "approach tile (4, 0) must be reachable"
        assert (9, 0) not in reach, (
            "Landing (9, 0) must NOT be reachable — only 1 tile of east "
            "momentum after turning up onto approach. "
            f"Got reach={sorted(reach)}"
        )

    def test_ramp_edges_near_jump_from_zero_momentum(self):
        """Stationary/turn approach at momentum=0 admits a NEAR-jump edge
        landing 2 tiles past the approach (ramp + 1), with post-momentum=1
        so chained far-jumps can't immediately follow.
        """
        from renegade_mcp.pathfinding import _bike_ramp_edges
        # 9-wide row: passable 0..3, ramp at 4, passable 5..8.
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 4]
        edges = _bike_ramp_edges(
            grid, 3, 0, "right", 1, 0, width=9, height=1, momentum=0,
        )
        # Exactly one edge: the near-jump, landing at approach+2 = (5, 0).
        assert edges == [(5, 0, 1)], (
            f"momentum=0 should emit only NEAR-jump edge (5, 0, 1); got {edges}"
        )

    def test_ramp_edges_mid_range_momentum_emits_no_edge(self):
        """Momentum=2 is in the dead zone — neither near nor far jumps
        are emitted. BFS intentionally skips this regime; puzzles that
        need it would require fresh empirical data.
        """
        from renegade_mcp.pathfinding import _bike_ramp_edges
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 4]
        edges = _bike_ramp_edges(
            grid, 3, 0, "right", 1, 0, width=9, height=1, momentum=2,
        )
        assert edges == [], (
            f"Mid-range momentum=2 should emit no edges; got {edges}"
        )

    def test_ramp_edges_far_jump_at_full_runway(self):
        """Momentum=RUNWAY-1 admits the far-jump edge; near-jump is not
        emitted when far qualifies (they're selected by momentum range,
        not both simultaneously).
        """
        from renegade_mcp.pathfinding import _bike_ramp_edges
        from renegade_mcp.nav_constants import BIKE_RAMP_RUNWAY_TILES
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 4]
        edges = _bike_ramp_edges(
            grid, 3, 0, "right", 1, 0, width=9, height=1,
            momentum=BIKE_RAMP_RUNWAY_TILES - 1,
        )
        # Exactly one edge: the far-jump at (8, 0), post-momentum=RUNWAY.
        assert edges == [(8, 0, BIKE_RAMP_RUNWAY_TILES)], (
            f"momentum={BIKE_RAMP_RUNWAY_TILES - 1} should emit only "
            f"FAR-jump edge (8, 0, {BIKE_RAMP_RUNWAY_TILES}); got {edges}"
        )

    def test_2d_bfs_near_jump_landing_reachable(self):
        """BFS must now admit near-jump landings — the ramp tile after a
        turn (momentum=0) lands the player 1 tile past, not 4.

        Layout (2D grid, approach reached via turn):

          row 0:  ##.R###   (ramp at col 3, walls block col 4/5/6)
          row 1:  .......  (travel lane)

        The player reaches approach (3, 0) via up-turn from (3, 1),
        so momentum at approach = 1 (just the turn step).  Actually —
        the turn step SETS momentum=1 (not 0) because the "up" direction
        is fresh.  We want to test the momentum=0 case; use a stationary
        start at the approach.
        """
        from renegade_mcp.pathfinding import _bfs_reachable
        # Simpler layout for near-jump: player at approach tile (3, 0)
        # with no prior same-direction steps.  Ramp at (4, 0), near-jump
        # lands at (5, 0), far-jump landing (8, 0) is behind a wall.
        grid = [[
            (True, 0x08), (True, 0x08), (True, 0x08),
            (True, 0x08),       # approach (3, 0)
            (False, 0xD7),      # ramp (4, 0)
            (True, 0x08),       # near landing (5, 0)
            (False, 0x00),      # wall (6, 0)
            (False, 0x00),      # wall (7, 0)
            (False, 0x00),      # far landing blocked (8, 0)
        ]]
        reach = _bfs_reachable(grid, set(), 3, 0, width=9, height=1)
        assert (5, 0) in reach, (
            f"Near-jump landing (5, 0) must be reachable from stationary "
            f"approach with momentum=0; got reach={sorted(reach)}"
        )
        assert (8, 0) not in reach, (
            f"Far-jump landing (8, 0) must not be reachable (blocked + "
            f"insufficient momentum); got reach={sorted(reach)}"
        )

    def test_2d_bfs_reaches_wayward_east_chamber_via_ramp_chain(
        self, emu: EmulatorClient,
    ):
        """BUG-043 closure (phase 3): chained-ramp momentum carry-through
        unblocks the Wayward Cave B1F east chamber.

        From (7, 22), phase-1 BFS reached (14, 17) — the first ramp's
        landing — but could not proceed because the next ramp's
        approach has only a 1-tile geometric runway behind it. With
        momentum-aware BFS, the landing's carried momentum (m=RUNWAY in
        the ramp direction) admits the second ramp and surfaces the
        Pokéball at (31, 16).

        Some east-chamber POIs ((22, 9), (33, 8), warp:0 at (43, 38))
        remain out of reach via ramps alone — they gate on additional
        ramps, an NPC, or a puzzle unrelated to this fix.
        """
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.pathfinding import (
            _bfs_reachable, _build_multi_chunk_terrain,
        )
        map_id, px, py = _read_position(emu)
        ti, ox, oy, w, h = _build_multi_chunk_terrain(
            emu, map_id, px, py, 43, 38,
            extra_targets=[(22, 9), (31, 16), (33, 8)],
        )
        reach = _bfs_reachable(ti, set(), px - ox, py - oy, w, h)
        assert (14 - ox, 17 - oy) in reach, (
            "Regression: phase-1 ramp edge to (14, 17) must still be "
            "admitted by the momentum-aware BFS."
        )
        assert (31 - ox, 16 - oy) in reach, (
            "Chain-aware BFS must reach the east-chamber Pokéball at "
            "(31, 16) via chained ramps from (14, 17)'s landing "
            "momentum. Regressing to 251 reachable tiles (phase-1 only) "
            "would fail this assertion."
        )


class TestBikeRampSegmentExecution:
    """Session-38 follow-up to BUG-043: end-to-end ramp chain execution.

    The momentum-aware BFS (session 35) + poll-release primitive (session
    36) unblocked the east-chamber plan. But executing the plan from the
    live ``bug_bike_ramps_repel`` save still failed: per-tile step_holds on
    the bike carried momentum across direction changes, so the
    ``up x5 → left → right x9`` plan slipped diagonally at the up→left
    turn (bike finished the pending up-step during the left press, landing
    at (6, 16) instead of (6, 17)).

    Fix: the executor now dismounts for any step that isn't within a
    ramp/slope runway + chain, and executes the runway+chain as ONE
    sustained direction hold (no per-tile release) with the button
    released at the last ramp tile so the jump animation settles the
    player cleanly on the landing.

    This test covers the end-to-end path: start on bike at (7, 22), walk
    up+left on foot (no slip), mount for the right-segment, sustain
    through 4 chained ramps, land at the Pokéball interaction tile
    (31, 17).
    """

    SAVE_STATE = "bug_bike_ramps_repel"

    def test_navigate_reaches_east_chamber_pokeball(self, emu: EmulatorClient):
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.navigation import navigate_to
        _, start_x, start_y = _read_position(emu)
        assert (start_x, start_y) == (7, 22), "save state must start at (7, 22)"

        result = navigate_to(emu, target_x=31, target_y=17, flee_encounters=True)
        _, end_x, end_y = _read_position(emu)
        assert (end_x, end_y) == (31, 17), (
            f"expected final position (31, 17); got ({end_x}, {end_y}).  "
            f"Result: {result}"
        )
        # The final position must match — repaths are tolerated (cold-mount
        # state can require a retry before the sustained segment lands
        # cleanly). The invariant is reaching the target, not the path
        # efficiency.

    def test_on_foot_during_non_ramp_walking(self, emu: EmulatorClient):
        """Confirm the new dismount-for-walking behavior: after the initial
        `up` phase, the player should be off the bicycle (bike momentum
        can't slip non-runway steps).
        """
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.addresses import addr
        from renegade_mcp.navigation import navigate_to
        # Navigate to the tile before the runway — no ramp segment.
        navigate_to(emu, target_x=6, target_y=17, flee_encounters=True)
        cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
        assert cycling is False, (
            "After navigating to a non-ramp target, the player must be on "
            "foot — bike momentum across direction changes caused the "
            "up→left slip that motivated this fix."
        )

    def test_poi_pickup_reaches_east_chamber_pokeball(self, emu: EmulatorClient):
        """Regression: interact_with (the POI dispatcher for items) calls
        _execute_path directly without pre-populating obstacle_tiles with
        the path's ramp/slope entries. Before the fix, _step_needs_bike
        saw an empty obstacle map, never mounted, and the player charged
        at the ramp on foot until MAX_REPATHS gave up. _execute_path now
        scans the path itself from repath_ctx['terrain_info'] so any
        caller gets the ramp lookahead.
        """
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.interaction import interact_with
        from renegade_mcp.nav_constants import _read_position

        result = interact_with(emu, object_index=2, flee_encounters=True)
        assert "error" not in result, f"interact_with failed: {result}"
        assert not result.get("stopped_early"), (
            f"nav stopped early: blocked_at={result.get('blocked_at')}.  "
            f"This indicates the ramp mount didn't fire (pre-fix symptom: "
            f"player charged the ramp on foot).  Full result: {result}"
        )
        _, end_x, end_y = _read_position(emu)
        assert (end_x, end_y) == (31, 17), (
            f"expected final position (31, 17); got ({end_x}, {end_y})"
        )


class TestBikeBridgeTraversal:
    """Wayward Cave bike-only suspension bridges (behaviors 0x76–0x7D).

    On-foot stepping onto a ``bike_bridge_*`` body tile is blocked by the
    engine; the player must be on the bicycle. The engine also refuses
    ``use_item("Bicycle")`` while standing on a body tile, so mid-bridge
    dismount is impossible — the bike stays on until the player exits
    onto a non-body tile.

    The executor auto-mounts before stepping onto a body tile, stays on
    bike across the whole span, and auto-dismounts on the first non-body
    step. Bike momentum on open terrain produces a few tiles of fast-gear
    coast after the button release; the overshoot-retry wrapper
    (``_nav_impl_with_overshoot_retry``) absorbs that by re-BFS-ing on
    foot from the coast-settled position.

    Save state: ``bug_bike_bridge_unknown`` — player on foot at (22, 13),
    standing on a ``bridge_start`` tile directly east of the south bridge
    body (behaviors 0x7A/0x7B at x=16–21).
    """

    SAVE_STATE = "bug_bike_bridge_unknown"

    def test_navigate_west_across_bridge(self, emu: EmulatorClient):
        """Cross the south bridge east→west and land on target (14, 13).

        The west trip uses slow-gear mounts so bike coasting is minimal;
        the executor should reach target in one pass without retries.
        """
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.navigation import navigate_to

        _, sx, sy = _read_position(emu)
        assert (sx, sy) == (22, 13), "save state must start at (22, 13)"

        result = navigate_to(emu, target_x=14, target_y=13, flee_encounters=True)
        _, ex, ey = _read_position(emu)
        assert (ex, ey) == (14, 13), (
            f"expected (14, 13); got ({ex}, {ey}).  Result: {result}"
        )
        assert not result.get("stopped_early"), (
            f"unexpected stopped_early: {result}"
        )

    def test_on_foot_stepping_onto_bridge_body_is_blocked_without_bike(
        self, emu: EmulatorClient,
    ):
        """Without the bicycle auto-mount, the player bonks on the bridge.

        Sanity-check: manual walk into the first body tile with no
        auto-mount produces zero displacement. Confirms the engine's
        on-foot rejection is the invariant the executor relies on.
        """
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.addresses import addr
        from renegade_mcp.nav_constants import _read_position, step_hold, HOLD_FRAMES

        _, sx, sy = _read_position(emu)
        assert (sx, sy) == (22, 13)
        cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
        assert cycling is False, "save state must be on foot"

        # Manual step_hold west — onto (21, 13) bike_bridge_EW body.
        step_hold(emu, "left", HOLD_FRAMES)
        _, ex, ey = _read_position(emu)
        assert (ex, ey) == (22, 13), (
            f"on-foot step onto bridge body should be blocked; "
            f"player moved to ({ex}, {ey})"
        )

    def test_dismounts_after_bridge_exit(self, emu: EmulatorClient):
        """After crossing the bridge, the player ends off-bike.

        Bike bridges share the "dismount for non-segment walking" rule
        with ramps: once the last body tile is behind us, the executor
        auto-dismounts so subsequent walking has no momentum carryover.
        """
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.addresses import addr
        from renegade_mcp.navigation import navigate_to

        navigate_to(emu, target_x=14, target_y=13, flee_encounters=True)
        cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
        assert cycling is False, (
            "Player must be off-bike after bridge crossing so that "
            "subsequent on-foot walks don't inherit bike momentum."
        )


class TestBikeSlopeBfsEdges:
    """BUG-045: BFS must require an uphill runway before a bike slope tile.

    Slopes (0xD9 top, 0xDA bottom) are N-S only in Gen 4 Platinum. Climbing
    means stepping `up` onto a slope tile from the approach tile south of it;
    the engine rejects ascents that arrive at the approach tile via a turn.
    BFS must match: refuse ``up`` entries into slope tiles unless the state
    carries ``BIKE_SLOPE_RUNWAY_TILES`` of consecutive up-momentum (approach
    tile included). Downward entries (auto-slide) are ungated.
    """

    SAVE_STATE = "bug_bike_slope_turn_into_approach"

    def test_slope_entry_blocked_without_momentum(self):
        """Turn-into-approach: last step was perpendicular, so approach
        momentum = 0 and the slope rejects the edge."""
        from renegade_mcp.pathfinding import _bike_slope_entry_blocked
        # Neighbor (1, 0) is a slope_bottom (0xDA); we're stepping up into it
        # from (1, 1) after turning (momentum=0 means last direction was not up).
        grid = [
            [(True, 0x08), (True, 0xDA)],
            [(True, 0x08), (True, 0x08)],
        ]
        blocked = _bike_slope_entry_blocked(
            grid, x=1, y=1, direction="up", dx=0, dy=-1, momentum=0,
        )
        assert blocked is True

    def test_slope_entry_admitted_with_full_runway(self):
        """Straight south-approach with RUNWAY-1 prior up-steps admits."""
        from renegade_mcp.pathfinding import _bike_slope_entry_blocked
        from renegade_mcp.nav_constants import BIKE_SLOPE_RUNWAY_TILES
        grid = [
            [(True, 0x08), (True, 0xDA)],
            [(True, 0x08), (True, 0x08)],
        ]
        # momentum = RUNWAY - 1 (approach tile counts, so total = RUNWAY)
        blocked = _bike_slope_entry_blocked(
            grid, x=1, y=1, direction="up", dx=0, dy=-1,
            momentum=BIKE_SLOPE_RUNWAY_TILES - 1,
        )
        assert blocked is False

    def test_slope_entry_ungated_for_descent(self):
        """Stepping DOWN onto a slope (auto-slide) must not be gated —
        momentum 0 is fine because gravity does the work."""
        from renegade_mcp.pathfinding import _bike_slope_entry_blocked
        # Slope_top (0xD9) at (1, 1); approach from (1, 0) going down.
        grid = [
            [(True, 0x08), (True, 0x08)],
            [(True, 0x08), (True, 0xD9)],
        ]
        blocked = _bike_slope_entry_blocked(
            grid, x=1, y=0, direction="down", dx=0, dy=1, momentum=0,
        )
        assert blocked is False

    def test_slope_entry_ungated_for_lateral(self):
        """Lateral approach to a slope tile is impossible in practice (slopes
        are walled E/W), but the gate must stay on the up-ascent axis only
        — lateral neighbors aren't the slope's "approach direction"."""
        from renegade_mcp.pathfinding import _bike_slope_entry_blocked
        grid = [[(True, 0x08), (True, 0xDA), (True, 0x08)]]
        blocked = _bike_slope_entry_blocked(
            grid, x=0, y=0, direction="right", dx=1, dy=0, momentum=0,
        )
        assert blocked is False

    def test_slope_entry_no_gate_on_non_slope(self):
        """Non-slope neighbor: gate returns False regardless of momentum."""
        from renegade_mcp.pathfinding import _bike_slope_entry_blocked
        grid = [[(True, 0x08), (True, 0x08)]]
        blocked = _bike_slope_entry_blocked(
            grid, x=0, y=0, direction="right", dx=1, dy=0, momentum=0,
        )
        assert blocked is False

    def test_2d_bfs_refuses_turn_into_slope_approach(self):
        r"""Synthetic grid: slope at (1, 1) [bottom] + (1, 0) [top]. A lateral
        corridor enters the approach at (1, 2) from the east, forcing the
        only BFS path to turn up with momentum=1. BFS must NOT admit the
        slope crossing from this configuration.

        Layout (width=4, height=5):
            0 1 2 3
          0 # # # #
          1 # / # #     ← slope_top (0xD9) at col 1
          2 # \ # #     ← slope_bottom (0xDA) at col 1, approach below
          3 . . . .     ← corridor; player starts at (3, 3)
          4 # # # #
        """
        from renegade_mcp.pathfinding import _bfs_reachable
        width, height = 4, 5
        grid = [[(False, 0x00)] * width for _ in range(height)]
        grid[1][1] = (True, 0xD9)  # slope_top
        grid[2][1] = (True, 0xDA)  # slope_bottom
        for x in range(width):
            grid[3][x] = (True, 0x08)  # corridor

        # Player starts at the east end (3, 3); approaches slope via
        # left, left, up into (1, 2). That's a turn (last_dir=left), so
        # the slope gate must reject the up step onto (1, 2)=0xDA.
        reach = _bfs_reachable(grid, set(), 3, 3, width=width, height=height)
        assert (1, 3) in reach, "approach tile (1, 3) must be reachable"
        assert (1, 2) not in reach, (
            "Slope_bottom (1, 2) must NOT be reachable — the only approach "
            f"turns in with momentum=1. Got reach={sorted(reach)}"
        )

    def test_2d_bfs_admits_slope_with_long_runway(self):
        r"""Same slope layout but with a vertical corridor south of the
        approach long enough to build RUNWAY tiles of up-momentum. BFS
        must admit the slope and reach tiles above it.

        Layout (width=3, height=8):
            0 1 2
          0 # . #
          1 # / #     ← slope_top
          2 # \ #     ← slope_bottom
          3 # . #     ← approach tile
          4 # . #     ← ↑ runway tiles
          5 # . #
          6 # . #
          7 # . #     ← player start (1, 7)
        """
        from renegade_mcp.pathfinding import _bfs_reachable
        from renegade_mcp.nav_constants import BIKE_SLOPE_RUNWAY_TILES
        assert BIKE_SLOPE_RUNWAY_TILES == 4, (
            "This test assumes RUNWAY=4; update layout/assertions if changed."
        )
        width, height = 3, 8
        grid = [[(False, 0x00)] * width for _ in range(height)]
        for y in range(height):
            grid[y][1] = (True, 0x08)
        grid[1][1] = (True, 0xD9)
        grid[2][1] = (True, 0xDA)
        grid[0][1] = (True, 0x08)

        reach = _bfs_reachable(grid, set(), 1, 7, width=width, height=height)
        assert (1, 2) in reach, (
            "Slope_bottom must be reachable via the long runway — "
            f"got reach={sorted(reach)}"
        )
        assert (1, 0) in reach, (
            "Post-slope tile (1, 0) must be reachable after crossing "
            f"the slope; got reach={sorted(reach)}"
        )

    def test_2d_bfs_admits_descent_without_runway(self):
        """Descending a slope has no runway requirement — start above the
        slope and walk south; BFS must admit the down crossing.
        """
        from renegade_mcp.pathfinding import _bfs_reachable
        width, height = 3, 5
        grid = [[(False, 0x00)] * width for _ in range(height)]
        grid[0][1] = (True, 0x08)  # player start above slope
        grid[1][1] = (True, 0xD9)  # slope_top
        grid[2][1] = (True, 0xDA)  # slope_bottom
        grid[3][1] = (True, 0x08)  # tile below slope
        grid[4][1] = (True, 0x08)

        reach = _bfs_reachable(grid, set(), 1, 0, width=width, height=height)
        assert (1, 2) in reach, "slope_bottom must be reachable going down"
        assert (1, 4) in reach, "tile below slope must be reachable"

    def test_wayward_cave_3d_bfs_reroutes_south_before_slope(
        self, emu: EmulatorClient,
    ):
        """BUG-045 integration on the repro save. From (8, 28) just east of
        the slope approach, BFS must pick a south-then-up path rather than
        the buggy left+up turn. The returned path starts with a `down`
        step (routing south to build runway) rather than a `left` (the
        turn-into-approach the BFS previously admitted)."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import read_player_height
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.pathfinding import (
            _bfs_pathfind_3d, _build_multi_chunk_elevation,
            _build_multi_chunk_terrain, _height_to_level,
        )
        map_id, px, py = _read_position(emu)
        # Target (7, 25): first cave_floor tile NORTH of the slope top.
        # Crossing the slope requires a level transition (L0 → L2 via ramp),
        # so the test drives _bfs_pathfind_3d, which orchestrates transitions.
        terrain_info, ox, oy, w, h = _build_multi_chunk_terrain(
            emu, map_id, px, py, 7, 25,
        )
        elevation = _build_multi_chunk_elevation(
            emu, map_id, terrain_info, ox, oy, w, h,
        )
        assert elevation is not None, "Wayward Cave must have BDHC elevation data"
        level = _height_to_level(
            read_player_height(emu), elevation,
            tile_x=px - ox, tile_y=py - oy,
        )
        assert level is not None

        path = _bfs_pathfind_3d(
            terrain_info, set(), elevation,
            px - ox, py - oy, 7 - ox, 25 - oy,
            level, width=w, height=h,
        )
        assert path is not None, (
            "3D BFS must still find a path to (7, 25) — south-approach is "
            "admissible with the slope gate."
        )
        # First step must NOT be `left` (the buggy turn-into-approach).
        # South approaches start with `down` or `left` to a vertical lane;
        # the specific first step depends on BFS tie-breaking, but the
        # critical invariant is: if the path crosses (7, 27)=slope_bottom,
        # the step INTO it must arrive with 3 prior consecutive `up` steps.
        deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        cx, cy = px - ox, py - oy
        last_dir: str | None = None
        momentum = 0
        slope_global = (7, 27)
        crossed_slope = False
        for step in path:
            dx, dy = deltas[step]
            nx, ny = cx + dx, cy + dy
            if (nx + ox, ny + oy) == slope_global and step == "up":
                # Must have RUNWAY - 1 prior same-direction steps.
                approach_m = momentum if last_dir == step else 0
                assert approach_m >= 3, (
                    f"Slope entry had insufficient up-momentum: "
                    f"approach_m={approach_m}, path={path}"
                )
                crossed_slope = True
            if last_dir == step:
                momentum += 1
            else:
                momentum = 1
            last_dir = step
            cx, cy = nx, ny
        assert crossed_slope, (
            "Path must cross the slope at (7, 27) to reach (7, 25); "
            f"got path={path}"
        )


class TestUnderBridgePathfind3d:
    """Regression: companion to TestBug038UnderBridgeReachability (view_map).

    After BUG-040 made view_map's ``_bfs_reachable_3d`` consider ramp AND
    flat plates independently on multi-plate tiles, ``navigate_to``'s
    ``_bfs_pathfind_level`` still used the old early-return logic — it
    checked the ramp plate first and returned without consulting the flat
    plate beneath. On Route 206 under the Cycling Road bridge, every
    ground-level tile that happens to also carry a bridge-ramp plate
    looked impassable to the level-1 BFS, so the east Wayward Cave warp
    (warp:7 at 299, 611) was correctly marked reachable by ``view_map``
    but unreachable by ``navigate_to``. Fix: port the permissive
    ramp/flat-independent check from ``_flood_fill_level`` into
    ``_bfs_pathfind_level`` (and mirror it in ``_validate_path_elevation``).
    """

    SAVE_STATE = "session30_route206_under_bridge"

    def _setup_3d_inputs(self, emu: EmulatorClient, goal_x: int, goal_y: int):
        """Build the same terrain+elevation tuple _navigate_to_impl uses."""
        from renegade_mcp.map_state import read_player_height
        from renegade_mcp.nav_constants import _read_position
        from renegade_mcp.pathfinding import (
            _build_multi_chunk_elevation,
            _build_multi_chunk_terrain,
            _height_to_level,
        )
        map_id, px, py = _read_position(emu)
        terrain_info, ox, oy, w, h = _build_multi_chunk_terrain(
            emu, map_id, px, py, goal_x, goal_y,
        )
        elevation = _build_multi_chunk_elevation(
            emu, map_id, terrain_info, ox, oy, w, h,
        )
        assert elevation is not None, "Route 206 must have BDHC elevation data"
        level = _height_to_level(
            read_player_height(emu), elevation,
            tile_x=px - ox, tile_y=py - oy,
        )
        assert level is not None, "Player must resolve to a single level"
        return (terrain_info, elevation, level, ox, oy, w, h, px, py)

    def test_under_bridge_to_wayward_warp_reachable(self, emu: EmulatorClient):
        """3D pathfind from under-bridge (310, 608) to warp:7 (299, 611) —
        the ground-level Wayward Cave entrance — must return a path on
        the player's level."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.pathfinding import _bfs_pathfind_3d
        terrain_info, elev, level, ox, oy, w, h, px, py = self._setup_3d_inputs(
            emu, 299, 611,
        )
        path = _bfs_pathfind_3d(
            terrain_info, set(), elev,
            px - ox, py - oy, 299 - ox, 611 - oy,
            level, width=w, height=h,
        )
        assert path is not None, (
            "_bfs_pathfind_3d must find a ground-level path to the east "
            "Wayward Cave warp (view_map reports it reachable)."
        )
        # Ground-level route hugs the east wall — should be short.
        assert len(path) < 40, f"path unexpectedly long: {len(path)} steps"

    def test_under_bridge_bridge_cyclist_unreachable(self, emu: EmulatorClient):
        """Counter-check: obj:4 Cyclist on the bridge at (304, 631) h=112
        must NOT be reachable from the ground player. Regression guard so
        the permissive ``_tile_on_level`` rewrite doesn't accidentally
        grant a ground→bridge path."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.pathfinding import _bfs_pathfind_3d
        terrain_info, elev, level, ox, oy, w, h, px, py = self._setup_3d_inputs(
            emu, 304, 631,
        )
        path = _bfs_pathfind_3d(
            terrain_info, set(), elev,
            px - ox, py - oy, 304 - ox, 631 - oy,
            level, width=w, height=h,
        )
        assert path is None, (
            f"Bridge Cyclist at (304, 631) must not be reachable from "
            f"ground; got path of length {len(path) if path else 0}"
        )


class TestLedgeDirections:
    """Pin ``LEDGE_DIRECTIONS`` to the pokeplatinum decomp encoding.

    Regression guard against the Apr 2026 discovery that the mapping was
    inverted: we had 0x3B (``JUMP_SOUTH`` per
    ``ref/pokeplatinum/include/constants/field/map_tile_behaviors.h`` line
    70) labeled as "right" / east-crossing, etc. The decomp's
    ``src/unk_0205F180.c:1772-1793`` switches on direction to pick which
    ``IsJump{North,South,West,East}`` check fires — so the crossing
    direction literally equals the ledge's name-direction.

    Swapping this pin is a real behavior change: any production code using
    the old mapping will route against the actual game. Update in lock-
    step with decomp changes.
    """

    def test_mapping_matches_decomp(self):
        from renegade_mcp.nav_constants import LEDGE_DIRECTIONS
        assert LEDGE_DIRECTIONS == {
            0x38: "right",  # JUMP_EAST
            0x39: "left",   # JUMP_WEST
            0x3A: "up",     # JUMP_NORTH
            0x3B: "down",   # JUMP_SOUTH
        }

    def test_bfs_crosses_south_ledge_only_moving_south(self):
        """A 0x3B JUMP_SOUTH ledge must accept south-direction steps and
        reject every other direction. Without the fix the ledge accepted
        east-direction steps (the old "right" mapping) — which let BFS
        chain east across ledge rows that are actually one-way south
        gates, creating phantom paths."""
        from renegade_mcp.pathfinding import _bfs_reachable
        # Column with player above a JUMP_SOUTH ledge at (0, 1); floor at (0, 2).
        grid = [
            [(True, 0x08)],    # (0, 0) floor — player
            [(True, 0x3B)],    # (0, 1) JUMP_SOUTH ledge — passable for south step
            [(True, 0x08)],    # (0, 2) floor past ledge
        ]
        reach = _bfs_reachable(grid, set(), 0, 0, width=1, height=3)
        assert (0, 1) in reach, "south step onto JUMP_SOUTH ledge must be allowed"
        assert (0, 2) in reach, "tile past the ledge must be reachable"

    def test_bfs_rejects_ledge_entry_from_wrong_direction(self):
        """Approaching a JUMP_SOUTH ledge from the south (moving north)
        must be rejected. In the game the ledge's `is_blocked` bit stops
        the step; BFS enforces the same via LEDGE_DIRECTIONS."""
        from renegade_mcp.pathfinding import _bfs_reachable
        # Player south of the ledge; floor tile north past the ledge.
        grid = [
            [(True, 0x08)],    # (0, 0) floor
            [(True, 0x3B)],    # (0, 1) JUMP_SOUTH ledge
            [(True, 0x08)],    # (0, 2) floor — player
        ]
        reach = _bfs_reachable(grid, set(), 0, 2, width=1, height=3)
        # Player should NOT be able to move north through the ledge.
        assert (0, 1) not in reach, (
            "north-direction step onto JUMP_SOUTH ledge must be rejected"
        )
        assert (0, 0) not in reach


# ---------------------------------------------------------------------------
# interact_with
# ---------------------------------------------------------------------------

class TestInteractWith:
    """NPC and object interaction."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_interact_npc_by_index(self, emu: EmulatorClient):
        """Interact with NPC by object_index — returns dialogue content."""
        from renegade_mcp.navigation import interact_with
        # Object index 5 = Grunt M (nearest NPC from test_eterna_city_overworld)
        result = interact_with(emu, object_index=5)
        assert "dialogue" in result or "conversation" in result, (
            f"Expected dialogue from NPC interaction, got: {list(result.keys())}"
        )

    @retry_on_rng("test_eterna_city_overworld")
    def test_interact_tile_by_coords(self, emu: EmulatorClient):
        """Interact with a sign by (x,y) — returns dialogue or sign overlay."""
        from renegade_mcp.navigation import interact_with
        # Interact with sign at (307, 540)
        result = interact_with(emu, x=307, y=540)
        assert "dialogue" in result or "sign_overlay" in result or "conversation" in result, (
            f"Expected dialogue or sign_overlay, got: {list(result.keys())}"
        )

    def test_sign_overlay(self, emu: EmulatorClient):
        """Sign interaction returns sign_overlay flag."""
        load_state(emu, "debug_signpost_blocking_navigate")
        from renegade_mcp.navigation import interact_with
        result = interact_with(emu, object_index=0)
        assert "error" not in result, f"Sign interaction should not error: {result.get('error')}"
        # Sign posts return sign_overlay or regular dialogue
        assert result.get("sign_overlay") or "dialogue" in result or "conversation" in result, (
            f"Expected sign_overlay or dialogue, got: {list(result.keys())}"
        )

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_flee_encounters_during_walk(self, emu: EmulatorClient):
        """flee_encounters works during walk to distant target."""
        from renegade_mcp.navigation import interact_with
        from renegade_mcp.map_state import view_map
        vmap = view_map(emu)
        non_warps = [e for e in vmap["interactibles"] if e["kind"] != "warp"]
        assert len(non_warps) > 0, "Expected non-warp interactibles on the map"
        obj = non_warps[-1]  # farthest
        result = interact_with(
            emu,
            object_index=obj["preview"]["object_index"],
            flee_encounters=True,
        )
        assert "error" not in result, f"Interaction should succeed: {result.get('error')}"

    @retry_on_rng("test_eterna_city_overworld")
    def test_flee_encounters_completes_interaction(self, emu: EmulatorClient):
        """flee_encounters=True still completes the interaction when no encounter."""
        from renegade_mcp.navigation import interact_with
        # Grunt M at object_index=5 — walk + interact on city overworld (no encounters)
        result = interact_with(emu, object_index=5, flee_encounters=True)
        assert "error" not in result, f"Should not error: {result.get('error')}"
        assert "dialogue" in result, (
            f"Should complete interaction with dialogue, got keys: {list(result.keys())}"
        )
        assert result["dialogue"]["status"] == "completed", (
            f"Dialogue should be completed, got: {result['dialogue'].get('status')}"
        )

    def test_flee_encounters_during_face_target(self, emu: EmulatorClient):
        """Regression: wild encounters triggered during the face-target phase
        (after BFS completed but before the A-press interaction) must honor
        flee_encounters. Repro: bug_flee_encounters_ignores_wild_double —
        player at (17, 37) walking `right x3` to reach Hiker Lorenzo
        (obj:15). With Mira following, stepping onto the grass at (20, 37)
        triggers a tag-partner double (Luxray + Mira's Kadabra vs wild
        Geodude + Baltoy). Before the fix the encounter fired the
        facing_seized branch, which returned the battle to the caller
        without ever calling the flee helper. The fix restores the flee
        path and lets the Hiker interaction run to completion (trainer
        battles still surface as expected — just not wild ones)."""
        from renegade_mcp.navigation import navigate_to
        load_state(emu, "bug_flee_encounters_ignores_wild_double")
        result = navigate_to(emu, poi="obj:15", flee_encounters=True)
        assert "error" not in result, f"Should not error: {result.get('error')}"
        # The wild double MUST be fled — not returned as an unresolved encounter.
        flee_log = result.get("flee_log") or []
        wild_flees = [e for e in flee_log if e.get("type") == "wild" and e.get("fled")]
        assert wild_flees, (
            f"Expected at least one fled wild encounter, got flee_log={flee_log}; "
            f"result keys: {list(result.keys())}"
        )
        assert result.get("encounters_fled", 0) >= 1
        # Interaction with Hiker Lorenzo ran — either dialogue completed or
        # his trainer battle is now surfaced (can't flee trainers).
        encounter = result.get("encounter")
        if encounter is not None:
            # Must be the Hiker's trainer battle, not a lingering wild one
            log_text = "\n".join(
                (e.get("text", "") for e in encounter.get("battle_log", []))
            ).lower()
            assert "hiker" in log_text or "trainer" in log_text, (
                f"Remaining encounter should be the trainer battle, not the "
                f"wild double; got: {log_text[:200]!r}"
            )

    def test_cutscene_trigger(self, emu: EmulatorClient):
        """Pokeball interaction triggers Cynthia cutscene dialogue."""
        load_state(emu, "debug_pokeball_cutscene_interrupt")
        from renegade_mcp.navigation import interact_with
        result = interact_with(emu, object_index=21)
        # Cutscene dialogue may be top-level or nested under encounter
        has_dialogue = (
            "dialogue" in result
            or "conversation" in result
            or (result.get("encounter", {}).get("encounter") == "dialogue")
        )
        assert has_dialogue, (
            f"Expected cutscene dialogue, got: {list(result.keys())}"
        )


# ---------------------------------------------------------------------------
# seek_encounter
# ---------------------------------------------------------------------------

class TestSeekEncounter:
    """Wild encounter seeking."""

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_grass_encounter(self, emu: EmulatorClient):
        """Pacing in grass triggers a wild encounter."""
        from renegade_mcp.navigation import seek_encounter
        result = seek_encounter(emu)
        assert result.get("result") == "encounter", (
            f"Expected encounter, got: {result.get('result')}"
        )

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_encounter_has_battle_state(self, emu: EmulatorClient):
        """Encounter result includes battle state with species and level."""
        from renegade_mcp.navigation import seek_encounter
        result = seek_encounter(emu)
        assert result["result"] == "encounter", f"Expected encounter, got: {result.get('result')}"
        enc = result["encounter"]
        assert "battle_state" in enc, "Encounter missing battle_state"
        assert len(enc["battle_state"]) >= 2, "battle_state should have player + enemy"
        enemy = next(b for b in enc["battle_state"] if b["side"] == "enemy")
        assert "species" in enemy, "Enemy missing species"
        assert "level" in enemy, "Enemy missing level"

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_encounter_at_action_prompt(self, emu: EmulatorClient):
        """Encounter stops at action prompt — ready for battle_turn."""
        from renegade_mcp.navigation import seek_encounter
        result = seek_encounter(emu)
        assert result["result"] == "encounter", f"Expected encounter, got: {result.get('result')}"
        assert result["encounter"].get("prompt_ready") is True, (
            "Encounter should be at action prompt (prompt_ready=True)"
        )

    def test_cave_encounter(self, emu: EmulatorClient):
        """cave=true for non-grass encounters in Mt. Coronet."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.navigation import seek_encounter
        result = seek_encounter(emu, cave=True)
        assert "result" in result, f"Missing 'result' key in response"
        assert result["result"] in ("encounter", "no_encounter"), (
            f"Expected encounter or no_encounter, got: {result['result']}"
        )
