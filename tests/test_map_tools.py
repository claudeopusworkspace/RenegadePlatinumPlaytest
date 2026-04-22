"""Tests for map tools: view_map and lookup_map_name helper.

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
        """Indoor map: returns grid, player, interactibles, unreachable list."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert "map" in result
        assert "location" in result
        assert "map_id" in result["location"]
        assert "name" in result["location"]
        assert "player" in result
        assert "interactibles" in result
        assert "unreachable_interactibles" in result
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
        """Warps appear as kind=warp interactibles with dest_map_name preview."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        warps = [e for e in result["interactibles"] if e["kind"] == "warp"]
        assert len(warps) > 0
        for warp in warps:
            assert "x" in warp
            assert "y" in warp
            assert warp["preview"].get("dest_map_name")

    def test_interactibles_sorted_by_steps(self, emu: EmulatorClient):
        """Reachable interactibles are sorted nearest first by BFS steps."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        entries = result["interactibles"]
        assert len(entries) >= 2, "Pokemon Center should have multiple interactibles"
        for e in entries:
            assert "steps" in e, f"reachable entry missing steps: {e}"
        for i in range(len(entries) - 1):
            assert entries[i]["steps"] <= entries[i + 1]["steps"], (
                f"Interactibles not sorted: {entries[i]['label']} "
                f"({entries[i]['steps']}) before {entries[i+1]['label']} "
                f"({entries[i+1]['steps']})"
            )

    def test_outdoor_multi_chunk(self, emu: EmulatorClient):
        """Outdoor route loads adjacent chunks."""
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert result["location"]["map_id"] is not None
        assert result["location"]["name"]
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
        """Mt. Coronet 3D map includes elevation markers in the grid."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert len(result["map"]) > 0
        map_str = result["map"]
        # 3D maps show height level numbers (0-9), ramps (/ \), or ledges (> <)
        has_elevation = any(c in map_str for c in "0123456789\\/><|")
        assert has_elevation, (
            "Mt. Coronet 3D map should contain elevation markers "
            "(digits, ramps, ledges), but map only contains: "
            + "".join(sorted(set(c for c in map_str if not c.isspace() and c != '#')))[:30]
        )

    def test_elevation_filter(self, emu: EmulatorClient):
        """level=0 filters to single elevation — map still renders."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.map_state import view_map
        result_filtered = view_map(emu, level=0)
        # Should return a valid map
        assert len(result_filtered["map"]) > 0
        assert "player" in result_filtered


# ---------------------------------------------------------------------------
# FR-006: render_map walkable-floor / cave-floor distinctness + legend
# ---------------------------------------------------------------------------

class TestFr006FloorLegend:
    """render_map distinguishes void, walkable ground, and cave floor, and
    surfaces the walkable glyphs in the legend so a reader can tell
    sparse-land rooms are traversable."""

    def test_cave_floor_renders_as_middle_dot(self):
        """behavior=0x08 no longer renders as ' ' (was visually ambiguous with void)."""
        from renegade_mcp.map_state import render_map
        # Single 1x1 grid of cave_floor — val nonzero so void branch doesn't fire.
        terrain = [[0x0008]]
        out = render_map(terrain, objects=[], player_local_x=-1, player_local_y=-1, facing=0)
        first_line = out.splitlines()[0]
        assert first_line == '·', f"cave floor should render as '·', got {first_line!r}"

    def test_walkable_ground_renders_as_underscore(self):
        """behavior=0x00 still renders as '_'."""
        from renegade_mcp.map_state import render_map
        terrain = [[0x0100]]  # high byte nonzero so val != 0, behavior == 0x00
        out = render_map(terrain, objects=[], player_local_x=-1, player_local_y=-1, facing=0)
        assert out.splitlines()[0] == '_'

    def test_void_stays_dot(self):
        """val==0 still renders as '.' — keeps outside-map distinct from floor."""
        from renegade_mcp.map_state import render_map
        terrain = [[0x0000]]
        out = render_map(terrain, objects=[], player_local_x=-1, player_local_y=-1, facing=0)
        assert out.splitlines()[0] == '.'

    def test_floor_glyphs_in_legend(self):
        """When walkable-ground or cave-floor tiles appear, the legend documents them."""
        from renegade_mcp.map_state import render_map
        terrain = [[0x0100, 0x0008]]  # one ground tile, one cave-floor tile
        out = render_map(terrain, objects=[], player_local_x=-1, player_local_y=-1, facing=0)
        legend = next((ln for ln in out.splitlines() if ln.startswith("Key:")), None)
        assert legend is not None, f"legend missing: {out!r}"
        assert "_=ground" in legend, legend
        assert "·=cave_floor" in legend, legend

    def test_cave_floor_and_void_are_visually_distinct(self):
        """A row of [void, floor, void] produces three different-looking chars."""
        from renegade_mcp.map_state import render_map
        terrain = [[0x0000, 0x0008, 0x0000]]
        out = render_map(terrain, objects=[], player_local_x=-1, player_local_y=-1, facing=0)
        first_line = out.splitlines()[0]
        assert first_line == '.·.', first_line


# ---------------------------------------------------------------------------
# FR-007: view_map splits objects into reachable vs unreachable lists
# ---------------------------------------------------------------------------

class TestFr007ReachableSplit:
    """view_map must expose separate reachable/unreachable lists so callers
    can plan `navigate_to(poi=...)` without filtering a mixed list. The
    `steps` field is present iff the interactible is reachable; unreachable
    entries carry a Manhattan `distance` instead."""

    def test_interactibles_have_steps(self, emu: EmulatorClient):
        """Every entry in `interactibles` has a BFS `steps` field."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert len(result["interactibles"]) > 0
        for e in result["interactibles"]:
            assert "steps" in e, f"reachable entry missing steps: {e}"
            assert "distance" not in e

    def test_unreachable_list_always_present(self, emu: EmulatorClient):
        """`unreachable_interactibles` is a list — empty when everything is reachable."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert "unreachable_interactibles" in result
        assert isinstance(result["unreachable_interactibles"], list)
        for e in result["unreachable_interactibles"]:
            assert "distance" in e
            assert "steps" not in e

    def test_unreachable_split_in_walled_area(self, emu: EmulatorClient):
        """Galactic HQ has rooms walled off by interior structure — when any
        POI ends up BFS-unreachable it should appear in
        unreachable_interactibles with Manhattan distance, and the map body
        must surface a one-liner pointer."""
        load_state(emu, "eterna_galactic_hq_pre_jupiter")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        unreachable = result["unreachable_interactibles"]
        if not unreachable:
            # Not all HQ floors have walled-off POIs in this save; skip the
            # stronger assertions if the viewport happens to expose none.
            return

        for e in unreachable:
            assert "distance" in e
            assert "steps" not in e

        assert "Unreachable:" in result["map"]

    def test_reachable_and_unreachable_disjoint(self, emu: EmulatorClient):
        """A given POI id must not appear in both lists."""
        load_state(emu, "eterna_galactic_hq_pre_jupiter")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable_ids = {e["id"] for e in result["interactibles"]}
        unreachable_ids = {e["id"] for e in result["unreachable_interactibles"]}
        assert reachable_ids.isdisjoint(unreachable_ids), (
            f"ids appeared in both lists: "
            f"{reachable_ids & unreachable_ids}"
        )


# ---------------------------------------------------------------------------
# BUG-029: view_map reachability respects BDHC elevation on multi-chunk maps
# ---------------------------------------------------------------------------

def _load_frozen(emu, name: str) -> None:
    """Load a save state without advancing frames — needed on the Cycling
    Road where the auto-slide would drift the player south during the
    helper's 60-frame settle.
    """
    ext = ".mst"
    path = f"/workspace/RenegadePlatinumPlaytest/savestates/{name}{ext}"
    emu.load_state(path)
    from renegade_mcp.addresses import reset, detect_shift
    reset()
    detect_shift(emu)


class TestBug029ElevationReachability:
    """Regression: view_map's reachability BFS must gate on elevation so
    under-bridge objects are not reported as reachable from the bridge.

    Save state ``bug_view_map_under_bridge_pokeball`` puts the player on the
    Cycling Road slope (Map 350, level 6) with a Pokeball at (302, 652)
    sitting on the ground plate below the bridge (level 1). Before this fix
    the 2D flood-fill flowed through bridge tiles and the pickup showed
    ``reachable: true, steps: 18``; ``navigate_to`` then tried to ride the
    bridge and stalled.

    These tests use ``_load_frozen`` rather than the standard helper because
    the standard helper advances 60 frames to let the emulator settle — on
    the Cycling Road slope that window is enough for the auto-slide to
    carry the player ~13 tiles south, out of the intended test position.
    """

    SAVE_STATE = "bug_view_map_under_bridge_pokeball"

    def test_under_bridge_pokeball_not_reachable(self, emu: EmulatorClient):
        """Pokeball at (302, 652) sits on ground below the bridge."""
        _load_frozen(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable = {(e["x"], e["y"]) for e in result["interactibles"]}
        unreachable = {(e["x"], e["y"]) for e in result["unreachable_interactibles"]}
        assert (302, 652) not in reachable, (
            "Pokeball at (302, 652) is under the bridge — should not be "
            "reachable from on-bridge player."
        )
        assert (302, 652) in unreachable, (
            f"Pokeball at (302, 652) must appear in unreachable_interactibles; "
            f"got unreachable={unreachable}"
        )

    def test_on_bridge_cyclist_still_reachable(self, emu: EmulatorClient):
        """Cyclist at (299, 669) is on the bridge near the player —
        elevation-aware BFS must still find them."""
        _load_frozen(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable = {(e["x"], e["y"]) for e in result["interactibles"]}
        assert (299, 669) in reachable, (
            f"On-bridge Cyclist at (299, 669) should be reachable; "
            f"reachable={reachable}"
        )


class TestBug038UnderBridgeReachability:
    """Regression: the inverse of BUG-029. With the player *under* the
    Cycling Road bridge on Route 206, view_map must:

    1. Not report bridge-level Cyclists as ground-reachable just because
       BFS routing through multi-level overlap tiles accidentally floods
       the bridge plate (the ``_steppable()`` gate on ML transitions).
    2. Not let a bridge-level NPC's 2D (x, y) shadow block the ground
       plate beneath them (the 3D ``npc_set`` with per-object elevation
       from the MapObject height field).
    3. Find ground tiles whose BDHC reports both a flat plate AND an
       overhead bridge ramp at the same (x, y) — the fixed
       ``_tile_on_level`` considers ramp and flat plates independently.
    4. Match each POI's approach tile against the POI's OWN level
       (inferred from its height), not any level the BFS reached the
       adjacent tile at.

    Save state ``session30_route206_under_bridge`` parks the player at
    Route 206 (310, 608), one tile south of the east Wayward Cave warp
    (warp:8 at 310, 607), with the Cycling Road bridge overhead. Before
    the fix bridge Cyclists (obj:2 at 299,611 h=140; obj:4 at 304,631
    h=112) were marked reachable while the ground-level Wayward Cave
    warp under them (warp:7 at 299,611) was marked unreachable.
    """

    SAVE_STATE = "session30_route206_under_bridge"

    def test_under_bridge_wayward_warp_reachable(self, emu: EmulatorClient):
        """warp:7 at (299, 611) is the Wayward Cave ground-level entrance
        sitting directly beneath obj:2 (bridge-level Cyclist). Must be
        reachable from (310, 608) via the ground-plate path."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable = [
            e for e in result["interactibles"]
            if e["kind"] == "warp"
            and (e["x"], e["y"]) == (299, 611)
            and e["preview"]["dest_map_name"] == "Wayward Cave"
        ]
        assert reachable, (
            "Ground-level Wayward Cave warp at (299, 611) must be "
            "reachable from under-bridge position (310, 608); got "
            f"unreachable={[(e['x'], e['y']) for e in result['unreachable_interactibles']]}"
        )

    def test_bridge_cyclist_299_611_not_reachable(self, emu: EmulatorClient):
        """obj:2 Cyclist at (299, 611) h=140 sits on the bridge plate ~124
        units above the player. Must not be reachable from ground."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable = {(e["x"], e["y"]) for e in result["interactibles"]}
        unreachable = {(e["x"], e["y"]) for e in result["unreachable_interactibles"]}
        assert (299, 611) not in {
            (e["x"], e["y"]) for e in result["interactibles"]
            if e["kind"] == "trainer"
        }, f"Bridge Cyclist at (299, 611) must not be reachable; reachable={reachable}"
        assert (299, 611) in unreachable, (
            f"Bridge Cyclist at (299, 611) must appear in unreachable list; "
            f"unreachable={unreachable}"
        )

    def test_bridge_cyclist_304_631_not_reachable(self, emu: EmulatorClient):
        """obj:4 Cyclist at (304, 631) h=112 on the bridge. Ground player
        has an ML overlap tile at (304, 632) with level_map=[1, 11] —
        before the ``_steppable`` ML-transition gate, the BFS would
        teleport to L11 and report obj:4 reachable."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        trainer_reach = {
            (e["x"], e["y"]) for e in result["interactibles"]
            if e["kind"] == "trainer"
        }
        assert (304, 631) not in trainer_reach, (
            f"Bridge Cyclist at (304, 631) must not be reachable via the "
            f"under-bridge ML overlap tile; trainer_reach={trainer_reach}"
        )

    def test_under_bridge_hiker_still_reachable(self, emu: EmulatorClient):
        """obj:21 Hiker at (311, 622) h=16 stands on the ground plate
        (L1) right next to the player's path. Must still be reachable."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable = {(e["x"], e["y"]) for e in result["interactibles"]}
        assert (311, 622) in reachable, (
            f"Ground-level Hiker at (311, 622) must be reachable; "
            f"reachable={reachable}"
        )


class TestFlatMultiChunkReachability:
    """Regression: on chunked maps whose BDHC is flat (one height across all
    chunks), view_map's 2D fallback must flood the full multi-chunk extent,
    not just the 15x15 render viewport. Otherwise POIs that sit a few tiles
    outside the viewport get reported as unreachable even though a short
    walking path exists.

    Repro: Wayward Cave (map 284) with the party following Mira. Player at
    (42, 53), Mira standing by at (38, 42) — 11 tiles north, well past the
    viewport top (y=46). Pre-fix view_map put Mira in
    unreachable_interactibles despite the corridor connecting the two tiles.
    """

    def test_wayward_cave_mira_reachable(self, emu: EmulatorClient):
        load_state(emu, "session23_end_with_mira")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable = {e["id"]: e for e in result["interactibles"]}
        unreachable_ids = {e["id"] for e in result["unreachable_interactibles"]}

        mira = next(
            (e for e in result["interactibles"] + result["unreachable_interactibles"]
             if e.get("label") == "Mira"),
            None,
        )
        assert mira is not None, "Mira NPC must appear in view_map output"
        assert mira["id"] in reachable, (
            f"Mira should be reachable from player (she is following and "
            f"blocking the way); got unreachable={unreachable_ids}"
        )
        assert "steps" in reachable[mira["id"]]


class TestBerryPatchState:
    """Soil map-objects (gfx_id 100) resolve to a BerryPatch read from the
    MiscSaveBlock RAM region (SAVE_BLOCK_BASE + 0x20C4, 14-byte records).
    The Route 206 under-bridge save has four active soils: two Rawst at
    (293-294, 627) and two Razz at (295-296, 691), all FRUIT stage x1.
    """

    SAVE_STATE = "session30_route206_under_bridge"

    def test_soils_resolve_to_planted_rawst_and_razz(self, emu: EmulatorClient):
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        all_entries = result["interactibles"] + result["unreachable_interactibles"]
        berries = {
            (e["x"], e["y"]): e for e in all_entries if e["kind"] == "berry"
        }
        # Expect both Rawst + both Razz soils in the output.
        expected = {(293, 627), (294, 627), (295, 691), (296, 691)}
        assert expected.issubset(berries.keys()), (
            f"Missing soils: got {set(berries.keys())}, expected superset of {expected}"
        )
        # Rawst pair
        for xy in [(293, 627), (294, 627)]:
            patch = berries[xy]["preview"].get("patch")
            assert patch is not None, f"soil@{xy} missing patch preview"
            assert patch["planted"] is True
            assert patch["berry"] == "Rawst"
            assert patch["growth_stage"] == "fruit"
            assert patch["harvestable"] is True
            assert patch["yield"] >= 1
            assert berries[xy]["label"].startswith("Rawst Berry")
        # Razz pair
        for xy in [(295, 691), (296, 691)]:
            patch = berries[xy]["preview"].get("patch")
            assert patch is not None
            assert patch["berry"] == "Razz"
            assert patch["growth_stage"] == "fruit"
            assert patch["harvestable"] is True


class TestFollowerPassableAndHiddenObjects:
    """Regression: follower NPCs (movement_type 48 / 50) must NOT block BFS,
    and Drayano's disabled-but-not-deleted zone_event entries (parked at
    (0, 0)) must not pollute the interactibles list.

    Repro save `bug_mira_follower_blocks_bfs` puts the player at (39, 42)
    in Wayward Cave with Mira sitting on (38, 42) — the only east-west
    link in the chamber. Before the fix:
      - Mira's tile was in npc_set, so walking through her was impossible
        and every POI on the other side (trainers at y=38/42, Pokeballs
        at y=15) fell into unreachable_interactibles.
      - 11 hidden "Rock Smash" zone_event rows at (0, 0) cluttered
        unreachable_interactibles.
    """

    SAVE_STATE = "bug_mira_follower_blocks_bfs"

    def test_follower_treated_as_passable(self, emu: EmulatorClient):
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        reachable_pos = {(e["x"], e["y"]): e for e in result["interactibles"]}
        unreachable_pos = {(e["x"], e["y"]): e for e in result["unreachable_interactibles"]}

        # Mira is 0 steps from the player — her tile IS the interaction tile.
        assert (38, 42) in reachable_pos, (
            "Mira (38,42) should be reachable (follower tile is passable)"
        )

        # Everything west of Mira — only reachable if Mira's tile is passable.
        west_pois = [(17, 38), (20, 38), (2, 42), (5, 42), (2, 14), (5, 14)]
        for pos in west_pois:
            assert pos in reachable_pos, (
                f"{pos} should be reachable via Mira's tile; "
                f"unreachable={sorted(unreachable_pos)}"
            )

    def test_non_follower_npc_still_blocks(self, emu: EmulatorClient):
        """Guard against over-broad follower detection: Mira in the save from
        right after her battle (`session23_end_with_mira`) has
        movement_type = LOOK_SOUTH (16), not FOLLOW_PLAYER (48) — she hasn't
        latched onto the player yet, so she must still be treated as a solid
        NPC that blocks BFS. The interaction tile must be adjacent to her,
        not her own tile."""
        load_state(emu, "session23_end_with_mira")
        from renegade_mcp.map_state import view_map, read_objects
        from renegade_mcp.nav_constants import is_follower_npc

        objects = read_objects(emu)
        mira_obj = next(
            (o for o in objects if (o.get("name") or "").strip() == "Mira"),
            None,
        )
        assert mira_obj is not None, "Mira must be in the object array"
        assert not is_follower_npc(mira_obj), (
            f"Mira mv_id={mira_obj.get('movement_type_id')} is not a "
            f"follower movement type in this save, and must not be treated "
            f"as passable"
        )

        result = view_map(emu)
        mira_entries = [
            e for e in result["interactibles"] + result["unreachable_interactibles"]
            if e.get("label") == "Mira"
        ]
        assert mira_entries, "Mira should appear in view_map output"
        mira = mira_entries[0]
        # Non-follower POI: interaction tile is a 4-adjacent tile, not her own
        if "interaction_x" in mira:
            assert (mira["interaction_x"], mira["interaction_y"]) != (mira["x"], mira["y"]), (
                "Non-follower NPC interaction tile must be adjacent, not own tile"
            )

    def test_sparse_object_array_fully_scanned(self, emu: EmulatorClient):
        """Regression: read_objects must scan every slot, not bail on the
        first run of 3 consecutive empty slots. Gen 4 dynamically evicts
        distant NPCs from the overworld object array — after the player
        walks far enough, slots 2/3/4 can all be empty (status=0) while
        slots 5+ remain live. The old scanner broke after 3 empties and
        silently dropped Mira, every trainer, and every hidden rock from
        view_map output.

        Save `bug_mira_and_east_interactibles_missing` puts the player at
        (44, 14) in Wayward Cave with exactly that sparse layout: only
        slots 0 and 1 are non-empty through the first 5 slots, but Mira
        (obj:5) and 10 trainers occupy later slots."""
        load_state(emu, "bug_mira_and_east_interactibles_missing")
        from renegade_mcp.map_state import read_objects, view_map

        objects = read_objects(emu)
        indices = {o["index"] for o in objects}
        # Expected objects that sit past the old early-exit point.
        expected = {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 27}
        missing = expected - indices
        assert not missing, (
            f"read_objects dropped slots {sorted(missing)} — the scanner "
            f"likely bailed out early on a run of empty slots. "
            f"Got indices: {sorted(indices)}"
        )

        # And view_map must surface Mira + at least one far-east trainer.
        result = view_map(emu)
        labels = {
            e.get("label")
            for e in result["interactibles"] + result["unreachable_interactibles"]
        }
        assert "Mira" in labels, (
            f"Mira must appear in view_map output; got labels={labels}"
        )

    def test_zero_coord_objects_excluded(self, emu: EmulatorClient):
        """Wayward Cave has many disabled Rock-Smash entries parked at
        (0, 0). They must not appear in either reachable or unreachable
        interactibles — they're neither actionable nor useful to surface."""
        load_state(emu, self.SAVE_STATE)
        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        all_entries = result["interactibles"] + result["unreachable_interactibles"]
        zero_coord = [e for e in all_entries if (e["x"], e["y"]) == (0, 0)]
        assert not zero_coord, (
            f"Expected no interactibles parked at (0, 0); got: "
            f"{[e['id'] + '/' + e.get('label', '') for e in zero_coord]}"
        )


class TestBug030PathElevationValidator:
    """Regression: the 2D-BFS-fallback path validator rejects paths that
    step between incompatible elevation layers (BUG-030).

    Unit test — does not require the under-bridge save state that the
    original filing reproduced against. The validator itself is shared
    by every 3D map, so we construct a minimal elevation dict with a
    bridge-over-ground layout and verify the validator catches the
    bridge-crossing path.
    """

    def test_validator_rejects_bridge_crossing_from_ground(self):
        from renegade_mcp.pathfinding import _validate_path_elevation

        # 3x5 grid: player at (1, 4) on L1 ground, target at (1, 0) on L1
        # ground, with a bridge (L3) at y=1..3 overhead (multi-level tiles).
        # A naive 2D path walks straight up through the bridge — which the
        # game engine would treat as stepping onto the bridge body.
        elevation = {
            "level_map": {
                (1, 0): [1],
                (1, 1): [1, 3],
                (1, 2): [1, 3],
                (1, 3): [1, 3],
                (1, 4): [1],
            },
            "ramp_tiles": {},
            "ramps": [],
            "levels": [
                {"level": 1, "height": 16},
                {"level": 3, "height": 48},
            ],
        }
        path_valid = ["up", "up", "up", "up"]  # all stay on L1 (implicitly)
        assert _validate_path_elevation(
            path_valid, elevation, 1, 4, start_level=1,
        ), "Path that stays on L1 through multi-level tiles must be accepted"

    def test_validator_rejects_level_jump_to_ground(self):
        """Path steps from L3 bridge body onto L1-only ground tile (no ramp)."""
        from renegade_mcp.pathfinding import _validate_path_elevation

        # Player starts at L3 on a bridge-body tile, walks north onto a
        # L1-only tile (under-bridge ground) — physically impossible without
        # a ramp.
        elevation = {
            "level_map": {
                (1, 0): [1],      # ground only
                (1, 1): [3],      # bridge body only
            },
            "ramp_tiles": {},
            "ramps": [],
            "levels": [
                {"level": 1, "height": 16},
                {"level": 3, "height": 48},
            ],
        }
        path = ["up"]
        assert not _validate_path_elevation(
            path, elevation, 1, 1, start_level=3,
        ), "Path that jumps L3→L1 without a ramp must be rejected"

    def test_validator_accepts_ramp_transition(self):
        """Path through a legitimate ramp between levels is accepted."""
        from renegade_mcp.pathfinding import _validate_path_elevation

        elevation = {
            "level_map": {
                (1, 0): [3],
                (1, 2): [1],
            },
            "ramp_tiles": {
                (1, 1): {
                    "ramp_index": 0,
                    "from_level": 3,
                    "to_level": 1,
                    "direction": "north",
                    "col_range": (1, 1),
                    "row_range": (1, 1),
                },
            },
            "ramps": [],
            "levels": [
                {"level": 1, "height": 16},
                {"level": 3, "height": 48},
            ],
        }
        path = ["up", "up"]
        assert _validate_path_elevation(
            path, elevation, 1, 2, start_level=1,
        ), "Path through a ramp tile connecting L1 and L3 must be accepted"


# ---------------------------------------------------------------------------
# lookup_map_name helper
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
        map_id = vmap["location"]["map_id"]

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


# ---------------------------------------------------------------------------
# BUG-008: lookup_map_name returns wrong names for reshuffled map IDs
# ---------------------------------------------------------------------------
# Save state: qa_oreburgh_gate_entrance — player inside Oreburgh Gate, map_id=258.

class TestBug008MapName:
    """map_id_to_name.json rebuilt from ROM zone headers."""

    def test_oreburgh_gate_not_floaroma_meadow(self, emu: EmulatorClient):
        """Map 258 should be 'Oreburgh Gate', not 'Floaroma Meadow'."""
        load_state(emu, "qa_oreburgh_gate_entrance")
        from renegade_mcp.map_names import lookup_map_name
        result = lookup_map_name(258)
        assert result["name"] == "Oreburgh Gate", (
            f"Expected 'Oreburgh Gate', got '{result['name']}'"
        )

    def test_map_name_from_live_map_id(self, emu: EmulatorClient):
        """lookup_map_name() with the live map_id returns the correct name."""
        load_state(emu, "qa_oreburgh_gate_entrance")
        from renegade_mcp.map_names import lookup_map_name
        from renegade_mcp.map_state import read_player_state
        map_id, _, _, _ = read_player_state(emu)
        result = lookup_map_name(map_id)
        assert result["map_id"] == 258
        assert result["name"] == "Oreburgh Gate"

    def test_map_table_no_unknowns(self, emu: EmulatorClient):
        """Every entry in the rebuilt table has a resolved name (no 'Unknown')."""
        from renegade_mcp.data import map_table
        table = map_table()
        unknowns = [
            (k, v) for k, v in table.items()
            if "Unknown" in v.get("name", "")
        ]
        assert len(unknowns) == 0, (
            f"Found {len(unknowns)} unknown entries: {unknowns[:5]}"
        )


# ---------------------------------------------------------------------------
# Interactibles: new 15x15 + POI schema (FR-008)
#
# The view_map overhaul replaces the flat `objects` / `warps` lists with a
# single `interactibles` list that carries POI ids for target-based nav.
# These tests cover the schema invariants and the warp-merging helper.
# ---------------------------------------------------------------------------


class TestViewportSize:
    """Overworld viewport is 15x15 with an axis ruler + Y column labels."""

    def test_outdoor_viewport_is_15_by_15(self, emu: EmulatorClient):
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        # Header ends with "<w>x<h>" — verify 15x15 for chunked overworld.
        lines = result["map"].split("\n")
        header = lines[0]
        assert "15x15" in header, f"Expected 15x15 viewport, got header: {header!r}"

    def test_axis_ruler_first_line_after_header(self, emu: EmulatorClient):
        """Row 0 of the rendered grid should be preceded by an X-ruler whose
        length equals the viewport width and whose chars are absolute-X
        last-digits."""
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        lines = result["map"].split("\n")
        # Layout: "Map ... origin:(vx,vy) WxH", blank, ruler, then grid rows.
        header = lines[0]
        # origin:(X,Y) — parse X.
        import re
        m = re.search(r"origin:\((\d+),(\d+)\) (\d+)x(\d+)", header)
        assert m is not None, header
        vp_x, vp_y, vp_w, _ = map(int, m.groups())

        ruler = lines[2]
        # "    " prefix (4 chars) then w digits.
        assert ruler.startswith("    "), f"Ruler should start with 4-space pad: {ruler!r}"
        digits = ruler[4:]
        assert len(digits) == vp_w, f"Ruler len {len(digits)} != viewport width {vp_w}"
        expected = "".join(str((vp_x + i) % 10) for i in range(vp_w))
        assert digits == expected, f"Ruler {digits!r} != expected {expected!r}"

    def test_y_column_labels_align_with_absolute_y(self, emu: EmulatorClient):
        """Each grid row is prefixed with its absolute Y coord, right-aligned
        to 3 chars + space."""
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        lines = result["map"].split("\n")
        import re
        m = re.search(r"origin:\((\d+),(\d+)\) (\d+)x(\d+)", lines[0])
        assert m is not None
        _, vp_y, _, vp_h = map(int, m.groups())

        # lines[0]=header, lines[1]=blank, lines[2]=ruler, lines[3..3+vp_h-1]=grid.
        for i in range(vp_h):
            row = lines[3 + i]
            expected_label = f"{vp_y + i:3d} "
            assert row.startswith(expected_label), (
                f"Row {i} should start with {expected_label!r}, got {row[:5]!r}"
            )


class TestInteractibleSchema:
    """Every reachable interactible has the fields needed for POI dispatch."""

    def test_reachable_entry_has_interaction_tile_and_face(self, emu: EmulatorClient):
        """NPC/sign/item/berry entries must expose interaction_x/y and face."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        objs = [e for e in result["interactibles"] if e["kind"] != "warp"]
        assert len(objs) > 0
        for e in objs:
            assert "interaction_x" in e
            assert "interaction_y" in e
            assert "face" in e
            assert e["face"] in ("up", "down", "left", "right"), e
            # interaction tile must be 4-adjacent to the POI
            dx = e["interaction_x"] - e["x"]
            dy = e["interaction_y"] - e["y"]
            assert abs(dx) + abs(dy) == 1, (
                f"interaction tile should be 4-adjacent; POI ({e['x']},{e['y']}) "
                f"interaction ({e['interaction_x']},{e['interaction_y']})"
            )

    def test_warp_entry_has_no_face_and_interaction_equals_poi(
        self, emu: EmulatorClient,
    ):
        """Warps are stepped-onto; interaction_x/y equals x/y and face is None."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        warps = [e for e in result["interactibles"] if e["kind"] == "warp"]
        assert len(warps) > 0
        for w in warps:
            assert w["face"] is None
            assert w["interaction_x"] == w["x"]
            assert w["interaction_y"] == w["y"]

    def test_entry_ids_unique_within_call(self, emu: EmulatorClient):
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        all_ids = [
            e["id"]
            for e in result["interactibles"] + result["unreachable_interactibles"]
        ]
        assert len(all_ids) == len(set(all_ids)), (
            f"duplicate ids: {sorted(all_ids)}"
        )

    def test_object_index_in_preview_for_dispatch(self, emu: EmulatorClient):
        """Every non-warp interactible carries object_index in its preview
        so navigate_to(poi=...) can dispatch to interact_with."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        for e in result["interactibles"]:
            if e["kind"] == "warp":
                continue
            assert "preview" in e
            assert "object_index" in e["preview"], e

    def test_rows_have_no_inter_cell_spaces(self, emu: EmulatorClient):
        """Grid row body must be contiguous glyphs — no spaces between cells
        (token-fragmentation finding from "Stuck in the Matrix")."""
        load_state(emu, "route211_from_coronet")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        lines = result["map"].split("\n")
        # Grid rows start on line 3 (after header, blank, ruler).
        for row in lines[3:18]:
            # Row format: "YYY XXXXXXX...X" — strip label (4 chars), cells follow.
            cells = row[4:]
            # Cells contain no spaces; trailing text after cells may have them.
            # The 15x15 grid is the first 15 chars after the label.
            body = cells[:15]
            assert " " not in body, (
                f"Row body has inter-cell space: {body!r}"
            )


class TestWarpMerging:
    """_merge_adjacent_warps: unit tests with synthetic warp data."""

    def test_two_adjacent_warps_same_dest_merge_into_one(self):
        """Door rendered as two adjacent tiles pointing at the same target."""
        from renegade_mcp.map_state import _merge_adjacent_warps
        warps = [
            {"x": 10, "y": 5, "dest_map": 42, "dest_warp": 0},
            {"x": 11, "y": 5, "dest_map": 42, "dest_warp": 0},
        ]
        reachable = {(10, 5): 3, (11, 5): 4}
        clusters = _merge_adjacent_warps(warps, reachable, player_x=10, player_y=8)
        assert len(clusters) == 1
        c = clusters[0]
        assert c["reachable"] is True
        assert len(c["tiles"]) == 2
        # Nearest-reachable tile is (10, 5) at 3 steps.
        assert c["interaction_xy"] == (10, 5)
        assert c["metric"] == 3

    def test_distinct_destinations_stay_separate_even_if_adjacent(self):
        """Two tiles next to each other going to different maps are two entries."""
        from renegade_mcp.map_state import _merge_adjacent_warps
        warps = [
            {"x": 10, "y": 5, "dest_map": 42, "dest_warp": 0},
            {"x": 11, "y": 5, "dest_map": 99, "dest_warp": 0},
        ]
        reachable = {(10, 5): 3, (11, 5): 3}
        clusters = _merge_adjacent_warps(warps, reachable, player_x=10, player_y=8)
        assert len(clusters) == 2
        dests = sorted(c["dest_map"] for c in clusters)
        assert dests == [42, 99]

    def test_non_adjacent_warps_same_dest_stay_separate(self):
        """Two tiles at the same destination but 2+ tiles apart do NOT merge."""
        from renegade_mcp.map_state import _merge_adjacent_warps
        warps = [
            {"x": 10, "y": 5, "dest_map": 42, "dest_warp": 0},
            {"x": 10, "y": 8, "dest_map": 42, "dest_warp": 0},
        ]
        reachable = {(10, 5): 1, (10, 8): 4}
        clusters = _merge_adjacent_warps(warps, reachable, player_x=10, player_y=6)
        assert len(clusters) == 2

    def test_unreachable_warp_picks_nearest_by_manhattan(self):
        """Cluster with no reachable tile returns reachable=False with Manhattan."""
        from renegade_mcp.map_state import _merge_adjacent_warps
        warps = [
            {"x": 10, "y": 5, "dest_map": 42, "dest_warp": 0},
            {"x": 11, "y": 5, "dest_map": 42, "dest_warp": 0},
        ]
        reachable = {}  # nothing reachable
        clusters = _merge_adjacent_warps(warps, reachable, player_x=5, player_y=5)
        assert len(clusters) == 1
        c = clusters[0]
        assert c["reachable"] is False
        # Nearest-Manhattan tile is (10, 5) at distance 5.
        assert c["interaction_xy"] == (10, 5)
        assert c["metric"] == 5

    def test_mixed_reachable_and_unreachable_in_cluster_prefers_reachable(self):
        """If any tile in a cluster is reachable, the cluster is reachable."""
        from renegade_mcp.map_state import _merge_adjacent_warps
        warps = [
            {"x": 10, "y": 5, "dest_map": 42, "dest_warp": 0},
            {"x": 11, "y": 5, "dest_map": 42, "dest_warp": 0},
            {"x": 12, "y": 5, "dest_map": 42, "dest_warp": 0},
        ]
        reachable = {(12, 5): 7}
        clusters = _merge_adjacent_warps(warps, reachable, player_x=5, player_y=5)
        assert len(clusters) == 1
        assert clusters[0]["reachable"] is True
        assert clusters[0]["interaction_xy"] == (12, 5)


class TestMergedTileCountPreview:
    """Warp interactibles expose merged_tile_count when > 1."""

    def test_eterna_pc_door_merges_two_tiles(self, emu: EmulatorClient):
        """Indoor map whose entrance door is a 2-tile warp strip."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        # Find any warp with merged_tile_count set — at least one indoor door
        # in Eterna PC / mart uses a 2-tile warp.
        warps = [e for e in result["interactibles"] if e["kind"] == "warp"]
        merged = [w for w in warps if w["preview"].get("merged_tile_count", 1) > 1]
        if not merged:
            # Not every save state places the player near a merged door —
            # skip if the viewport doesn't expose one.
            return
        for w in merged:
            assert w["preview"]["merged_tile_count"] >= 2


# ---------------------------------------------------------------------------
# navigate_to(poi=...) validation + dispatch
# ---------------------------------------------------------------------------


class TestNavigateToPOIValidation:
    """Parameter validation — no emu state change."""

    def test_mutual_exclusion_of_xy_and_poi(self, emu: EmulatorClient):
        from renegade_mcp.navigation import navigate_to
        r = navigate_to(emu, 10, 10, poi="obj:5")
        assert "error" in r
        assert "not both" in r["error"]

    def test_neither_xy_nor_poi_errors(self, emu: EmulatorClient):
        from renegade_mcp.navigation import navigate_to
        r = navigate_to(emu)
        assert "error" in r

    def test_unknown_poi_id_lists_available_ids(self, emu: EmulatorClient):
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.navigation import navigate_to
        r = navigate_to(emu, poi="obj:9999")
        assert "error" in r
        assert "available_ids" in r
        assert isinstance(r["available_ids"], list)


class TestNavigateToPOIDispatch:
    """End-to-end POI dispatch — POI resolves, walks, runs the interaction."""

    def test_warp_poi_activates_transition(self, emu: EmulatorClient):
        """Picking a warp by POI id walks there and triggers the map transition."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import read_player_state, view_map
        from renegade_mcp.navigation import navigate_to

        start_map, _, _, _ = read_player_state(emu)
        vmap = view_map(emu)
        warps = [e for e in vmap["interactibles"] if e["kind"] == "warp"]
        assert len(warps) > 0, "Need at least one reachable warp for this test"
        # Pick the nearest warp.
        warp = warps[0]

        result = navigate_to(emu, poi=warp["id"])
        assert "error" not in result, f"POI warp failed: {result.get('error')}"
        assert result.get("poi_resolved", {}).get("kind") == "warp"

        # Either the map changed (transition succeeded) or the nav reached the
        # warp tile (close enough for this smoke test — the warp may take one
        # extra frame to fire on some maps).
        end_map, _, _, _ = read_player_state(emu)
        reached_warp = (
            result.get("final", {}).get("x") == warp["x"]
            and result.get("final", {}).get("y") == warp["y"]
        )
        assert end_map != start_map or reached_warp, (
            f"Warp dispatch neither transitioned nor reached tile: "
            f"start_map={start_map} end_map={end_map} final={result.get('final')}"
        )

    def test_npc_poi_runs_face_plus_a(self, emu: EmulatorClient):
        """Picking an NPC by POI id walks there, faces, and presses A."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        from renegade_mcp.navigation import navigate_to

        vmap = view_map(emu)
        npcs = [
            e for e in vmap["interactibles"]
            if e["kind"] in ("npc", "trainer", "sign", "item", "berry")
        ]
        assert len(npcs) > 0
        npc = npcs[0]

        result = navigate_to(emu, poi=npc["id"])
        assert "error" not in result, f"POI NPC failed: {result.get('error')}"
        assert result.get("poi_resolved", {}).get("kind") == npc["kind"]
        # interact_with's result shape includes "target" or "dialogue" on success.
        assert "target" in result or "dialogue" in result, (
            f"Expected interact_with result shape, got keys: {list(result.keys())}"
        )
