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
        assert len(vmap["objects"]) > 0, "Expected objects on the map"
        obj = vmap["objects"][-1]  # farthest object
        result = interact_with(emu, object_index=obj["index"], flee_encounters=True)
        assert "error" not in result, f"Interaction should succeed: {result.get('error')}"

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
