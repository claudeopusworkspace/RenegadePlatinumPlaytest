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
    launches the player 4 tiles in that direction — entry tile + 3 past
    the ramp (`MOVEMENT_ACTION_JUMP_FARTHER_EAST`, pokeplatinum
    src/unk_0205F180.c:613-629 + src/unk_020655F4.c:994, empirically
    verified in scripts/spike_ramp_runway.py). BFS represents the jump as
    a single directional edge from the approach tile (ramp - 1) to the
    landing tile (ramp + 3), skipping the ramp tile itself and whatever
    walls sit in the intermediate tiles.

    The engine requires momentum to fire the jump. Empirically 0-2
    approach tiles fail, 3+ succeed; we use BIKE_RAMP_RUNWAY_TILES=4 for
    cold-start safety margin. BFS admits the edge only when the
    straight-line approach in the ramp direction is long enough.
    """

    SAVE_STATE = "session31_wayward_cave_bike_ramps"

    def test_ramp_landing_helper_east(self):
        """_bike_ramp_landing returns the 4-tile-east landing when the ramp
        faces east, the landing is passable, and momentum is sufficient."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        # 8-wide row with approach at (3, 0), ramp at (4, 0), landing at (7, 0).
        # Tiles behind approach (0..2) are passable → geometric runway check
        # succeeds even without an explicit momentum arg.
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 3]
        landing = _bike_ramp_landing(grid, 3, 0, "right", 1, 0, width=8, height=1)
        assert landing == (7, 0)

    def test_ramp_landing_wrong_direction(self):
        """Ramp only triggers in its facing direction — approaching a
        ramp_E from the east (moving left) must not produce a jump."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(True, 0x08)] * 3]
        # Stepping left from (5, 0): neighbor (4, 0) is ramp_E but facing
        # east doesn't match the westward approach direction.
        landing = _bike_ramp_landing(grid, 5, 0, "left", -1, 0, width=8, height=1)
        assert landing is None

    def test_ramp_landing_blocked_landing(self):
        """If the landing tile is impassable, the ramp edge does not fire."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        # Approach passable, ramp, then walls — landing at (7, 0) blocked.
        grid = [[(True, 0x08)] * 4 + [(False, 0xD7)] + [(False, 0x00)] * 3]
        landing = _bike_ramp_landing(grid, 3, 0, "right", 1, 0, width=8, height=1)
        assert landing is None

    def test_ramp_landing_insufficient_runway(self):
        """Too-short straight-line approach must reject the ramp edge.

        With only 2 passable tiles behind the approach tile, the BFS cannot
        supply enough momentum for the jump to fire. Matches spike finding
        that 0-2 approach tiles fail on-device.
        """
        from renegade_mcp.pathfinding import _bike_ramp_landing
        # Only 2 passable tiles before approach (wall at col 0). Approach at
        # (3, 0), ramp at (4, 0), landing at (7, 0).
        grid = [[(False, 0x00)] + [(True, 0x08)] * 3 + [(False, 0xD7)]
                + [(True, 0x08)] * 3]
        landing = _bike_ramp_landing(grid, 3, 0, "right", 1, 0, width=8, height=1)
        assert landing is None

    def test_ramp_landing_momentum_override(self):
        """Explicit `momentum` arg from a momentum-aware BFS bypasses the
        geometric fallback — a landing after a prior ramp can chain even
        when the intermediate runway is too short geometrically."""
        from renegade_mcp.pathfinding import _bike_ramp_landing
        from renegade_mcp.nav_constants import BIKE_RAMP_RUNWAY_TILES
        # Short geometric runway (1 tile) but momentum=RUNWAY-1 supplied.
        grid = [[(False, 0x00)] * 2 + [(True, 0x08), (False, 0xD7)]
                + [(True, 0x08)] * 4]
        landing = _bike_ramp_landing(
            grid, 2, 0, "right", 1, 0, width=8, height=1,
            momentum=BIKE_RAMP_RUNWAY_TILES - 1,
        )
        assert landing == (6, 0)

    def test_2d_bfs_crosses_ramp_in_wayward_cave(self, emu: EmulatorClient):
        """From the west-chamber corridor, the 2D BFS must reach the landing
        tile (13, 17) past the east ramp at (10, 17). Fast-gear jump lands
        3 tiles past the ramp (4 from approach); (13, 17) is the first
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
        assert (13 - ox, 17 - oy) in reach, (
            "2D BFS must reach ramp landing (13, 17) from the player "
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
