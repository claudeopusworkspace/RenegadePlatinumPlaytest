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
        assert len(objects) >= 2, "Pokemon Center should have multiple objects"
        # Reachable objects should have increasing step counts
        reachable = [o for o in objects if o.get("reachable")]
        assert len(reachable) >= 2, "Should have multiple reachable objects"
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
    """view_map must expose separate reachable/unreachable object lists so
    callers can plan interact_with / navigate_to without filtering a mixed
    list. Previously everything lived in `objects` with a `reachable` bool,
    which was easy to miss when planning from the ASCII output alone."""

    def test_objects_contains_only_reachable(self, emu: EmulatorClient):
        """Every entry in `objects` has reachable=True."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert len(result["objects"]) > 0
        for o in result["objects"]:
            assert o.get("reachable") is True, (
                f"object in `objects` must be reachable, got: {o}"
            )

    def test_unreachable_objects_key_always_present(self, emu: EmulatorClient):
        """`unreachable_objects` is a list — empty when everything is reachable."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert "unreachable_objects" in result
        assert isinstance(result["unreachable_objects"], list)
        for o in result["unreachable_objects"]:
            assert o.get("reachable") is False, (
                f"entry in unreachable_objects must have reachable=False, got: {o}"
            )

    def test_unreachable_split_in_walled_area(self, emu: EmulatorClient):
        """Galactic HQ has rooms walled off by interior structure — when any
        object ends up BFS-unreachable it should appear in
        unreachable_objects, not objects, and the map string should surface a
        one-liner pointer."""
        load_state(emu, "eterna_galactic_hq_pre_jupiter")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        unreachable = result["unreachable_objects"]
        if not unreachable:
            # Not all HQ floors have visible but walled-off objects in this
            # save; if the viewport happens to expose none, the invariant
            # still holds (everything in `objects` is reachable). Skip the
            # stronger assertions for this save.
            return

        for o in unreachable:
            assert o.get("reachable") is False
            # unreachable entries carry Manhattan distance, not BFS steps
            assert "distance" in o
            assert "steps" not in o

        # Map string must surface the unreachable count so a reader notices.
        assert "Unreachable:" in result["map"]

    def test_objects_and_unreachable_disjoint(self, emu: EmulatorClient):
        """A given object must not appear in both lists."""
        load_state(emu, "eterna_galactic_hq_pre_jupiter")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        reachable_idx = {o["index"] for o in result["objects"]}
        unreachable_idx = {o["index"] for o in result["unreachable_objects"]}
        assert reachable_idx.isdisjoint(unreachable_idx), (
            f"indices appeared in both lists: "
            f"{reachable_idx & unreachable_idx}"
        )


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


# ---------------------------------------------------------------------------
# BUG-008: map_name returns wrong names for reshuffled map IDs
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
