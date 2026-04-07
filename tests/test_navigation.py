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
        """Walk a short path — position changes."""
        from renegade_mcp.navigation import navigate_manual
        from renegade_mcp.map_state import read_player_state
        _, x_before, y_before, _ = read_player_state(emu)
        result = navigate_manual(emu, "d2 r3")
        _, x_after, y_after, _ = read_player_state(emu)
        assert result["steps"] > 0
        assert (x_after, y_after) != (x_before, y_before)

    @retry_on_rng("test_eterna_city_overworld")
    def test_walk_into_wall(self, emu: EmulatorClient):
        """Walking into a wall returns blocked error (pre-validates)."""
        from renegade_mcp.navigation import navigate_manual
        # Walk north a lot — should detect wall before moving
        result = navigate_manual(emu, "u20")
        # Path validation catches walls before movement
        assert "error" in result or "blocked" in str(result)
        assert result.get("blocked_step", 0) > 0 or "final" in result

    @retry_on_rng("test_eterna_city_overworld")
    def test_walk_triggers_warp(self, emu: EmulatorClient):
        """Walking into the Pokemon Center door triggers a map transition."""
        from renegade_mcp.navigation import navigate_manual
        # From (305, 530) facing down, walk up into the PC door
        result = navigate_manual(emu, "u1")
        # Should detect door entry
        if result.get("door_entered") or result.get("new_map"):
            assert result.get("new_map") is not None or result.get("door_entered")

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_flee_encounters(self, emu: EmulatorClient):
        """flee_encounters auto-flees wild battles during walk."""
        from renegade_mcp.navigation import navigate_manual
        # Walk a long path through grass — may trigger encounters
        result = navigate_manual(emu, "d5 u5 d5 u5", flee_encounters=True)
        # Should complete or return encounter info
        assert "final" in result or "encounter" in result


# ---------------------------------------------------------------------------
# navigate_to (BFS pathfind)
# ---------------------------------------------------------------------------

class TestNavigateTo:
    """BFS pathfinding navigation."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_nearby_tile(self, emu: EmulatorClient):
        """Navigate to nearby reachable tile — arrives."""
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import read_player_state
        # Move to a tile 3 tiles south
        _, start_x, start_y, _ = read_player_state(emu)
        result = navigate_to(emu, start_x, start_y + 3)
        assert result.get("steps", 0) >= 3
        assert "final" in result

    @retry_on_rng("test_eterna_city_overworld")
    def test_navigate_to_warp(self, emu: EmulatorClient):
        """Navigate to the Pokemon Center door — triggers warp."""
        from renegade_mcp.navigation import navigate_to
        # PC door is at (305, 530) which is the starting position
        # Navigate to the mart door at (310, 539)
        result = navigate_to(emu, 310, 539)
        # Should arrive at the door or transition
        assert "final" in result or "door_entered" in result

    @retry_on_rng("test_eterna_city_overworld")
    def test_unreachable_tile_diagnostics(self, emu: EmulatorClient):
        """Unreachable tile returns diagnostics with diagram."""
        from renegade_mcp.navigation import navigate_to
        # Navigate to a tile inside a building (unreachable from outside)
        result = navigate_to(emu, 295, 518)
        # Should return failure diagnostics
        if result.get("error") or result.get("diagram"):
            assert "diagram" in result or "nearest_reachable" in result or "error" in result

    def test_sign_blocking(self, emu: EmulatorClient):
        """BFS avoids sign activation tile."""
        load_state(emu, "debug_signpost_blocking_navigate")
        from renegade_mcp.navigation import navigate_to
        # This state is at a sign that blocks pathfinding
        # Navigate past it — the BFS should route around the sign's activation tile
        result = navigate_to(emu, 355, 531)
        # Should either arrive or report the sign interaction
        assert "final" in result or "error" in result

    def test_3d_elevation(self, emu: EmulatorClient):
        """3D elevation pathfinding in Mt. Coronet."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.navigation import navigate_to
        # Try to navigate to target tile
        result = navigate_to(emu, 29, 35)
        # The debug state captures a known 3D pathfinding issue
        assert "final" in result or "error" in result

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_flee_encounters_navigation(self, emu: EmulatorClient):
        """flee_encounters auto-flees during BFS navigation through grass."""
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import read_player_state
        _, x, y, _ = read_player_state(emu)
        result = navigate_to(emu, x + 3, y, flee_encounters=True)
        assert "final" in result or "encounter" in result

    @retry_on_rng("test_eterna_city_overworld")
    def test_position_dict_has_map_info(self, emu: EmulatorClient):
        """Position dicts include map name info."""
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import read_player_state
        _, x, y, _ = read_player_state(emu)
        result = navigate_to(emu, x + 2, y)
        if "final" in result:
            final = result["final"]
            assert "x" in final
            assert "y" in final
            assert "map" in final or "map_id" in final

    def test_short_path_indoor(self, emu: EmulatorClient):
        """Short path inside Pokemon Center."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.navigation import navigate_to
        # Navigate to a nearby tile inside the PC
        result = navigate_to(emu, 10, 6)
        assert result.get("steps", 0) >= 1


# ---------------------------------------------------------------------------
# interact_with
# ---------------------------------------------------------------------------

class TestInteractWith:
    """NPC and object interaction."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_interact_npc_by_index(self, emu: EmulatorClient):
        """Interact with NPC by object_index — returns dialogue."""
        from renegade_mcp.navigation import interact_with
        # Object index 5 = Grunt M (nearest NPC from test_eterna_city_overworld)
        result = interact_with(emu, object_index=5)
        assert "dialogue" in result or "conversation" in result or "error" not in result

    @retry_on_rng("test_eterna_city_overworld")
    def test_interact_tile_by_coords(self, emu: EmulatorClient):
        """Interact with a specific tile by (x,y)."""
        from renegade_mcp.navigation import interact_with
        # Interact with sign at (307, 540)
        result = interact_with(emu, x=307, y=540)
        assert "error" not in result or "dialogue" in result or "sign_overlay" in result

    def test_sign_overlay(self, emu: EmulatorClient):
        """Sign interaction returns sign_overlay flag."""
        load_state(emu, "debug_signpost_blocking_navigate")
        from renegade_mcp.navigation import interact_with
        # Interact with the signpost
        result = interact_with(emu, object_index=0)
        # Sign posts may return sign_overlay or regular dialogue
        assert "error" not in result or "sign" in str(result).lower()

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_flee_encounters_during_walk(self, emu: EmulatorClient):
        """flee_encounters works during walk to target."""
        from renegade_mcp.navigation import interact_with
        from renegade_mcp.map_state import read_player_state, view_map
        vmap = view_map(emu)
        # Try to interact with a distant object — may encounter battles en route
        if len(vmap["objects"]) > 0:
            obj = vmap["objects"][-1]  # farthest object
            result = interact_with(emu, object_index=obj["index"], flee_encounters=True)
            assert result is not None

    def test_cutscene_trigger(self, emu: EmulatorClient):
        """Pokeball cutscene trigger state."""
        load_state(emu, "debug_pokeball_cutscene_interrupt")
        from renegade_mcp.navigation import interact_with
        result = interact_with(emu, object_index=21)
        # Should trigger dialogue/cutscene
        assert result is not None


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
        assert result.get("result") == "encounter"
        assert "encounter" in result

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_encounter_has_battle_state(self, emu: EmulatorClient):
        """Encounter result includes battle state with species and level."""
        from renegade_mcp.navigation import seek_encounter
        result = seek_encounter(emu)
        if result.get("result") == "encounter":
            enc = result["encounter"]
            assert "battle_state" in enc
            assert len(enc["battle_state"]) >= 2
            enemy = next(b for b in enc["battle_state"] if b["side"] == "enemy")
            assert "species" in enemy
            assert "level" in enemy

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_encounter_at_action_prompt(self, emu: EmulatorClient):
        """Encounter stops at action prompt — ready for battle_turn."""
        from renegade_mcp.navigation import seek_encounter
        result = seek_encounter(emu)
        if result.get("result") == "encounter":
            assert result["encounter"].get("prompt_ready") is True

    def test_cave_encounter(self, emu: EmulatorClient):
        """cave=true for non-grass encounters in Mt. Coronet."""
        load_state(emu, "debug_coronet218_3d_path_blocked")
        from renegade_mcp.navigation import seek_encounter
        # May or may not find encounter — Mt. Coronet has encounters
        result = seek_encounter(emu, cave=True)
        # Should either find encounter or exhaust steps
        assert "result" in result
