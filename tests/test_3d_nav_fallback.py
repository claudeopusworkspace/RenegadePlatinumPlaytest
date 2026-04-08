"""Tests for 3D navigation fallback behavior.

Covers:
  - 3D BFS → 2D BFS fallback when 3D path fails (disconnected levels)
  - Dynamic block tracking during _execute_path (gym clock puzzles)
  - _try_repath falls through from 3D to 2D

Uses Eterna Gym (map 67) save states with different clock positions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestNavigateTo3DFallback:
    """navigate_to falls back to 2D BFS when 3D BFS fails."""

    def test_l0_to_exit_warp(self, emu: EmulatorClient):
        """Player on L0 can navigate to exit warp on L1 via 2D fallback.

        Bug: 3D BFS returned 'No 3D path found' because L0 has no ramp
        connections. Fix: falls through to 2D BFS which ignores elevation.
        """
        load_state(emu, "bug_navigate_to_no_3d_path_l0_to_exit")
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import get_map_state

        # Verify starting position: L0 in Eterna Gym
        state = get_map_state(emu)
        assert state["map_id"] == 67
        assert state["px"] == 3 and state["py"] == 20

        # Navigate to exit warp — should NOT return 'No 3D path found'
        result = navigate_to(emu, 11, 27, flee_encounters=True)
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

        # Player should have moved toward the exit (may be interrupted by
        # poison dialogue, but should not be stranded on L0)
        final = result.get("final", {})
        final_y = final.get("y", 0)
        assert final_y > 20, (
            f"Player should have moved past L0 (y=20), ended at y={final_y}"
        )

    def test_l0_to_exit_reaches_city(self, emu: EmulatorClient):
        """Player on L0 can exit the gym completely via repeated navigate_to.

        Uses flee_encounters to handle poison interruptions.
        """
        load_state(emu, "bug_navigate_to_no_3d_path_l0_to_exit")
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import get_map_state

        # Try up to 3 times (poison interrupts may break the first attempt)
        for _ in range(3):
            result = navigate_to(emu, 11, 27, flee_encounters=True)
            if result.get("door_entered"):
                break

        state = get_map_state(emu)
        assert state["map_id"] == 65, (
            f"Expected Eterna City (map 65), got map {state['map_id']}"
        )


class TestDynamicBlockTracking:
    """_execute_path tracks dynamically blocked tiles for repathing."""

    def test_clock_hand_dynamic_blocks(self, emu: EmulatorClient):
        """Navigate through rotated clock puzzle discovers blocked tiles.

        Bug: 3D BFS planned a path through disconnected L2 clock tiles.
        Player got stuck, repaths found the same bad tiles repeatedly.
        Fix: blocked tiles are tracked and excluded from subsequent repaths.
        """
        load_state(emu, "bug_navigate_to_clock_hand_passability")
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import get_map_state

        # Verify starting position
        state = get_map_state(emu)
        assert state["map_id"] == 67
        assert state["px"] == 2 and state["py"] == 8

        # Navigate to exit — should use repaths to discover blocked tiles
        # and eventually route around the clock area
        result = navigate_to(emu, 11, 27, flee_encounters=True)

        # Should have repaths > 0 (dynamic blocks discovered)
        repaths = result.get("repaths", 0)
        assert repaths > 0, "Expected repaths from dynamic block discovery"

        # Player should have moved significantly past the clock area
        final = result.get("final", {})
        final_y = final.get("y", 0)
        assert final_y > 14, (
            f"Player should have passed clock area (y>14), ended at y={final_y}"
        )

    def test_clock_hand_reaches_exit(self, emu: EmulatorClient):
        """Player navigates through clock puzzle and exits gym completely."""
        load_state(emu, "bug_navigate_to_clock_hand_passability")
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.map_state import get_map_state

        # Try up to 3 times (poison/dialogue may interrupt)
        for _ in range(3):
            result = navigate_to(emu, 11, 27, flee_encounters=True)
            if result.get("door_entered"):
                break

        state = get_map_state(emu)
        assert state["map_id"] == 65, (
            f"Expected Eterna City (map 65), got map {state['map_id']}"
        )
