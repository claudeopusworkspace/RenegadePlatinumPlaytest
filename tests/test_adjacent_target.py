"""Tests for navigate_to adjacent_to_target behavior.

Uses save state: eterna_city_shiny_swinub_in_party
  - Player in Eterna City overworld

Navigates into the Pokemon Center (map 69) which has static NPCs
like Idol (10, 6) and Clefairy (11, 6) that can be targeted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


STATE = "eterna_city_shiny_swinub_in_party"


class TestAdjacentToTarget:
    """navigate_to stops adjacent to occupied tiles gracefully."""

    def _enter_pc(self, emu):
        """Navigate into Eterna City Pokemon Center."""
        from renegade_mcp.navigation import navigate_to
        result = navigate_to(emu, 305, 527, flee_encounters=True)
        # Should warp into the PC
        from renegade_mcp.map_state import get_map_state
        state = get_map_state(emu)
        assert state["map_id"] == 69, (
            f"Expected to be in PC (map 69), got map {state['map_id']}"
        )

    def test_static_npc_returns_adjacent(self, emu: EmulatorClient):
        """Navigating to a static NPC tile returns adjacent_to_target."""
        load_state(emu, STATE)
        self._enter_pc(emu)
        from renegade_mcp.navigation import navigate_to
        # Idol NPC sits at (10, 6) in the PC — static, reachable
        result = navigate_to(emu, 10, 6)
        assert result.get("adjacent_to_target") is True, (
            f"Expected adjacent_to_target, got: {result}"
        )
        assert result["target"]["x"] == 10
        assert result["target"]["y"] == 6
        assert "stopped_early" not in result

    def test_no_wasted_repaths(self, emu: EmulatorClient):
        """Adjacent stop should not burn repath attempts."""
        load_state(emu, STATE)
        self._enter_pc(emu)
        from renegade_mcp.navigation import navigate_to
        # Clefairy at (11, 6) — static NPC
        result = navigate_to(emu, 11, 6)
        assert result.get("adjacent_to_target") is True, (
            f"Expected adjacent_to_target, got: {result}"
        )
        # Should not have any repaths (the old behavior burned up to 5)
        assert result.get("repaths", 0) == 0, (
            f"Should not repath for adjacent target, got {result.get('repaths')} repaths"
        )

    def test_empty_tile_no_adjacent_flag(self, emu: EmulatorClient):
        """Navigating to an empty tile reaches it exactly (no adjacent flag)."""
        load_state(emu, STATE)
        self._enter_pc(emu)
        from renegade_mcp.navigation import navigate_to
        # Empty tile in the PC (center of the floor)
        result = navigate_to(emu, 8, 8)
        assert "adjacent_to_target" not in result, (
            f"Empty tile should not trigger adjacent_to_target: {result}"
        )
        assert result["final"]["x"] == 8
        assert result["final"]["y"] == 8
