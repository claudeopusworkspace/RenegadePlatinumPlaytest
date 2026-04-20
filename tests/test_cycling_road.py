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


# ---------------------------------------------------------------------------
# Bike slope traversal (Route 207)
# ---------------------------------------------------------------------------

class TestBikeSlopeConstants:
    """Bike slope constants and behaviors."""

    def test_slope_behaviors_defined(self, emu: EmulatorClient):
        """BIKE_SLOPE_BEHAVIORS contains both slope tiles."""
        from renegade_mcp.navigation import BIKE_SLOPE_BEHAVIORS
        assert 0xD9 in BIKE_SLOPE_BEHAVIORS  # bike_slope_top
        assert 0xDA in BIKE_SLOPE_BEHAVIORS  # bike_slope_bottom

    def test_slope_types_defined(self, emu: EmulatorClient):
        """BIKE_SLOPE_TYPES contains the bike_slope type string."""
        from renegade_mcp.navigation import BIKE_SLOPE_TYPES
        assert "bike_slope" in BIKE_SLOPE_TYPES

    def test_gear_address_valid(self, emu: EmulatorClient):
        """BIKE_GEAR_STATE_ADDR is in the expected ARM9 BSS range."""
        from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR
        assert 0x02100000 < BIKE_GEAR_STATE_ADDR < 0x02200000


class TestBikeSlopeTraversal:
    """Bike slope navigation on Route 207.

    Uses route207_at_bike_slope_bottom save state: (306, 720), on bicycle,
    one tile south of the bike slope bottom.  E4 save (8 badges).
    """

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_gear_toggle(self, emu: EmulatorClient):
        """Gear address reads correctly and toggles with B press."""
        from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR
        gear = emu.read_memory(BIKE_GEAR_STATE_ADDR, size="byte")
        assert gear == 1, f"Expected slow gear (1), got {gear}"
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(8)
        gear = emu.read_memory(BIKE_GEAR_STATE_ADDR, size="byte")
        assert gear == 0, f"Expected fast gear (0) after B press, got {gear}"

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_slope_in_path(self, emu: EmulatorClient):
        """navigate_to detects slope tiles in the BFS path."""
        from renegade_mcp.navigation import _navigate_to_impl
        result = _navigate_to_impl(emu, 306, 710)
        assert "obstacles_cleared" in result, "Expected obstacles_cleared in result"
        slopes = [o for o in result["obstacles_cleared"] if o["type"] == "bike_slope"]
        assert len(slopes) == 1, f"Expected 1 bike_slope obstacle, got {slopes}"
        assert slopes[0]["tiles"] == 2, f"Expected 2 slope tiles, got {slopes[0]['tiles']}"

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_traverse_reaches_target(self, emu: EmulatorClient):
        """navigate_to through slope reaches a target well past the slope."""
        from renegade_mcp.navigation import _navigate_to_impl
        result = _navigate_to_impl(emu, 306, 710)
        assert result["final"]["y"] == 710, (
            f"Expected y=710, got y={result['final']['y']}"
        )
        assert result["final"]["x"] == 306

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_traverse_no_drift(self, emu: EmulatorClient):
        """Position is stable after slope traversal (no post-nav drift)."""
        from renegade_mcp.navigation import _navigate_to_impl, _read_position
        _navigate_to_impl(emu, 306, 710)
        _, x1, y1 = _read_position(emu)
        # Advance 600 more frames — position should not change
        emu.advance_frames(600)
        _, x2, y2 = _read_position(emu)
        assert (x1, y1) == (x2, y2), (
            f"Position drifted from ({x1},{y1}) to ({x2},{y2}) after 600 frames"
        )

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_navigation_works_after_traverse(self, emu: EmulatorClient):
        """Normal navigation continues working after slope traversal."""
        from renegade_mcp.navigation import _navigate_to_impl
        _navigate_to_impl(emu, 306, 710)
        # Navigate further north — should work without errors
        result = _navigate_to_impl(emu, 306, 707)
        assert "error" not in result, f"Post-slope navigation failed: {result}"
        assert result["final"]["y"] <= 707, (
            f"Expected to reach y<=707, got y={result['final']['y']}"
        )

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_close_target_overshoots_gracefully(self, emu: EmulatorClient):
        """Navigating to a target just past the slope overshoots but reports correctly."""
        from renegade_mcp.navigation import _navigate_to_impl
        # Target y=718 is the slope top — bike momentum will carry past
        result = _navigate_to_impl(emu, 306, 718)
        # The player should be AT or PAST the target (lower y = further north)
        assert result["final"]["y"] <= 718, (
            f"Expected y <= 718 (at or past slope), got y={result['final']['y']}"
        )
        assert "obstacles_cleared" in result

    @retry_on_rng("route207_at_bike_slope_bottom")
    def test_auto_mounts_bike_when_walking(self, emu: EmulatorClient):
        """Walking player auto-mounts bicycle when slope is in the BFS path."""
        from renegade_mcp.addresses import addr
        from renegade_mcp.navigation import _navigate_to_impl
        from renegade_mcp.use_item import use_item

        # Dismount properly via the game's Bicycle key item
        cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling != 0, "Precondition: save state should start on bicycle"
        dismount = use_item(emu, "Bicycle")
        assert dismount.get("success"), f"Dismount failed: {dismount}"
        cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling == 0, "Precondition: player should be walking after dismount"

        # Navigate through the slope — should auto-mount and clear it
        result = _navigate_to_impl(emu, 306, 710)

        # Verify slope was traversed
        assert "obstacles_cleared" in result, (
            f"Expected obstacles_cleared, got: {result}"
        )
        slopes = [o for o in result["obstacles_cleared"] if o["type"] == "bike_slope"]
        assert len(slopes) == 1, f"Expected 1 bike_slope cleared, got {slopes}"

        # Verify player is now on bike and past the slope
        cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling != 0, "Player should be cycling after auto-mount"
        assert result["final"]["y"] <= 718, (
            f"Expected past the slope (y <= 718), got y={result['final']['y']}"
        )


# ---------------------------------------------------------------------------
# QA BUG-025: navigate_to silent failure on bike slope without bicycle
# ---------------------------------------------------------------------------

class TestQaBug025BikeSlopeAutoMount:
    """Regression: walking north into a slope from distance auto-mounts cleanly.

    The original bug: when navigate_to's BFS path crossed a bike slope and the
    player was on foot, stepping onto the slope tile briefly succeeded (position
    changed) before the game's slope physics slid the player back south. The
    post-step blocked check never caught this — the player oscillated between
    the slope-bottom tile and the ground tile to its south, burning all 15
    repaths before returning without any diagnostic.

    Fix: pre-step check in _execute_path intercepts slope targets, auto-mounts
    the bicycle, and then lets the existing blocked-branch traversal run
    (single-step entry IS blocked on a bike, so it fires correctly). The
    traverse helper was also made more robust: it now forces gear=1 via memory
    write and presses B unconditionally, since a fresh mount leaves gear=0 in
    a state where the first backup press gets absorbed by residual animation.
    """

    @retry_on_rng("bug_bike_slope_north_climb_fail")
    def test_walk_from_distance_auto_mounts(self, emu: EmulatorClient):
        """navigate_to from (299, 730) on foot to (305, 715) clears the slope."""
        from renegade_mcp.addresses import addr
        from renegade_mcp.navigation import _navigate_to_impl

        cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling == 0, "Precondition: save state should start on foot"

        result = _navigate_to_impl(emu, 305, 715)

        assert "obstacles_cleared" in result, (
            f"Expected slope to be cleared, got: {result}"
        )
        slopes = [o for o in result["obstacles_cleared"] if o["type"] == "bike_slope"]
        assert len(slopes) == 1, f"Expected 1 bike_slope cleared, got {slopes}"

        # Bike momentum may overshoot the exact target by a tile; what matters
        # is that the slope was crossed (y <= 717).
        assert result["final"]["y"] <= 717, (
            f"Expected to clear the slope (y <= 717), got {result['final']}"
        )

        cycling_after = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling_after != 0, "Player should be cycling after auto-mount"

    @retry_on_rng("bug_bike_slope_north_climb_fail")
    def test_no_bike_slope_blocked_reason_on_success(self, emu: EmulatorClient):
        """Successful slope climb must NOT return blocked_reason=bike_slope_requires_bicycle."""
        from renegade_mcp.navigation import _navigate_to_impl

        result = _navigate_to_impl(emu, 305, 715)
        assert result.get("blocked_reason") != "bike_slope_requires_bicycle", (
            f"Got spurious bike_slope_requires_bicycle when slope should have been "
            f"cleared: {result}"
        )


# ---------------------------------------------------------------------------
# BUG-031: bike-slope traversal fails on Wayward Cave ascent — must surface
# a clear error rather than silently stopping
# ---------------------------------------------------------------------------

class TestBug031BikeSlopeTraversalFailure:
    """Regression: when the fast-gear/run-up traversal doesn't clear a slope
    (observed on Wayward Cave's north-bound slopes despite the same function
    succeeding on Route 207 from an identical setup), navigate_to must return
    a structured blocked_reason instead of a vague "Possible obstacle" note.
    """

    @retry_on_rng("bug_wayward_cave_bike_slope_up")
    def test_clear_error_when_traversal_fails(self, emu: EmulatorClient):
        """navigate_to(7, 18) surfaces bike_slope_traversal_failed reason."""
        from renegade_mcp.navigation import _navigate_to_impl

        result = _navigate_to_impl(emu, 7, 18)
        assert result.get("stopped_early") is True, (
            f"Expected stopped_early=True, got: {result}"
        )
        assert result.get("blocked_reason") == "bike_slope_traversal_failed", (
            f"Expected blocked_reason=bike_slope_traversal_failed, got: "
            f"{result.get('blocked_reason')!r} in {result}"
        )
        assert "bike_slope_position" in result, (
            f"Expected bike_slope_position in result: {result}"
        )

    @retry_on_rng("bug_wayward_cave_bike_slope_up")
    def test_player_not_stranded_mid_slope(self, emu: EmulatorClient):
        """After a failed ascent, the player must end up on a normal passable
        tile (not wedged on the slope itself)."""
        from renegade_mcp.navigation import _navigate_to_impl, _read_position

        _navigate_to_impl(emu, 7, 18)
        _, fx, fy = _read_position(emu)
        # Slope is at (7, 26-27). Player should be south of it (greater y).
        assert fy >= 28, (
            f"Player ended up at ({fx},{fy}); expected to be south of the "
            f"slope (y >= 28)"
        )


# ---------------------------------------------------------------------------
# QA BUG-024: navigate_to wanders on side-warp clusters (Cycling Road gate)
# ---------------------------------------------------------------------------

class TestQaBug024SideWarpCluster:
    """Regression: reject absurdly long BFS paths near same-map warp clusters.

    At the end of Cycling Road, the player stands on a 0x6F (side_S WARP)
    tile inside a gate house.  The reciprocal 0x6E (WARP_NORTH) tile sits
    south of the gate, only 7 Manhattan tiles away — but there's no direct
    walkable route, so BFS finds a 93-step detour that loops all the way
    around the overworld.  navigate_to would then try to execute that crazy
    path, repath 7+ times, and exit far from the target with warp_failed.

    Fix: if the BFS path length exceeds max(manhattan * 5, manhattan + 30),
    refuse with a clear error.  When the player is on a directional warp
    tile, include a press_buttons suggestion so the caller knows the
    intended way through.
    """

    @retry_on_rng("route206_cyclingroad_end_nav_repro")
    def test_refuses_long_detour_to_warp_target(self, emu: EmulatorClient):
        """(302, 681) → (302, 688) through the gate house returns clean error.

        Post-BUG-030: navigate_to no longer falls back to 2D BFS on elevated
        maps, so the refusal now fires from the elevation path rather than
        the sanity-cap step-count check. Same outcome (clean error, no
        player movement, warp hint), different trigger point.
        """
        from renegade_mcp.navigation import _navigate_to_impl

        result = _navigate_to_impl(emu, 302, 688)
        assert "error" in result, f"Expected error, got: {result}"
        assert "No reasonable path" in result["error"], result["error"]
        assert result.get("manhattan") == 7

    @retry_on_rng("route206_cyclingroad_end_nav_repro")
    def test_hints_at_warp_direction_when_on_warp_tile(self, emu: EmulatorClient):
        """Error message tells caller which direction triggers the warp."""
        from renegade_mcp.navigation import _navigate_to_impl

        result = _navigate_to_impl(emu, 302, 688)
        assert "note" in result, f"Expected warp note, got: {result}"
        # Player is on a 0x6F (WARP_SOUTH) tile — hint should suggest 'down'.
        assert "down" in result["note"], result["note"]

    @retry_on_rng("route206_cyclingroad_end_nav_repro")
    def test_does_not_move_the_player(self, emu: EmulatorClient):
        """Refused navigation must not leave player wandering on the map."""
        from renegade_mcp.navigation import _read_position, _navigate_to_impl

        _, x_before, y_before = _read_position(emu)
        _navigate_to_impl(emu, 302, 688)
        _, x_after, y_after = _read_position(emu)
        assert (x_after, y_after) == (x_before, y_before), (
            f"Player moved from ({x_before},{y_before}) to ({x_after},{y_after}) "
            f"despite refused navigation."
        )


# ---------------------------------------------------------------------------
# QA BUG-023: egg-hatch "Oh?" misclassified as trainer/NPC dialogue
# ---------------------------------------------------------------------------

class TestQaBug023EggHatchClassification:
    """Regression: navigate_to distinguishes egg-hatch from NPC dialogue.

    Before this fix, walking on Cycling Road with an egg at hatch threshold
    returned `encounter.encounter == "dialogue"` with `text == "Oh?"` — the
    only way for a caller to know it was a hatch was to string-match "Oh?".

    Fix: nav_events._post_nav_check captures the party's egg slot *before*
    calling advance_dialogue (the egg flag flips during the ~60-second
    hatch animation).  If the dialogue text is "Oh?" and the party has
    an egg, returns encounter="egg_hatch" with hatching_slot=<index>.
    """

    @retry_on_rng("route206_pre_togepi_hatch")
    def test_egg_hatch_classified_distinctly(self, emu: EmulatorClient):
        """navigate_to returns encounter=egg_hatch, not dialogue."""
        from renegade_mcp.navigation import _navigate_to_impl

        result = _navigate_to_impl(emu, 304, 640)
        encounter = result.get("encounter", {})
        assert encounter.get("encounter") == "egg_hatch", (
            f"Expected encounter=egg_hatch, got: {encounter}"
        )

    @retry_on_rng("route206_pre_togepi_hatch")
    def test_egg_hatch_reports_hatching_slot(self, emu: EmulatorClient):
        """egg_hatch response identifies which party slot is hatching."""
        from renegade_mcp.navigation import _navigate_to_impl

        result = _navigate_to_impl(emu, 304, 640)
        encounter = result.get("encounter", {})
        assert encounter.get("hatching_slot") == 5, (
            f"Expected hatching_slot=5 (Togepi), got: {encounter}"
        )
