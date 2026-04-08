"""Tests for MOVE_BLOCKED detection and auto_grind backup_move handling.

Uses save state: bug_auto_grind_torment_loop
  - Machop Lv22 vs Croagunk Lv16 on Route 205
  - Machop is Tormented, at action prompt
  - Knock Off (slot 3) was the last attempted move, so Torment blocks it
  - Moves: Low Kick (0), Brick Break (1), Return (2), Knock Off (3)

These tests are deterministic — no RNG since the battle is already in progress
and the Torment state is fixed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import (
    do_load_state as load_state,
    assert_log_contains,
    assert_final_state,
)

STATE = "bug_auto_grind_torment_loop"


# ---------------------------------------------------------------------------
# battle_turn MOVE_BLOCKED detection
# ---------------------------------------------------------------------------

class TestMoveBlocked:
    """battle_turn returns MOVE_BLOCKED when Torment rejects a move."""

    def test_torment_blocked_move_returns_move_blocked(self, emu: EmulatorClient):
        """Knock Off (slot 3) is Tormented — returns MOVE_BLOCKED."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)
        assert_final_state(result, "MOVE_BLOCKED")
        assert_log_contains(result, "can't use the same move")

    def test_unblocked_move_succeeds(self, emu: EmulatorClient):
        """Return (slot 2) is NOT Tormented — turn executes normally."""
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=2)
        assert result["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED"), (
            f"Expected successful turn, got: {result['final_state']}"
        )
        assert_log_contains(result, "used")
        assert_log_contains(result, "Return")


# ---------------------------------------------------------------------------
# auto_grind with backup_move
# ---------------------------------------------------------------------------

class TestAutoGrindMoveBlocked:
    """auto_grind handles Torment via backup_move parameter."""

    def test_no_backup_returns_move_blocked(self, emu: EmulatorClient):
        """Without backup_move, auto_grind stops immediately with move_blocked."""
        load_state(emu, STATE)
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=3, iterations=1)
        assert result["stop_reason"] == "move_blocked", (
            f"Expected move_blocked stop, got: {result['stop_reason']}"
        )
        assert "backup_move" in result["stop_detail"].lower(), (
            "Stop detail should mention backup_move"
        )

    def test_backup_move_completes_battle(self, emu: EmulatorClient):
        """With backup_move, auto_grind alternates moves and wins the battle."""
        load_state(emu, STATE)
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=3, backup_move=2, iterations=1)
        assert result["stop_reason"] == "iterations", (
            f"Expected iterations stop (battle won), got: {result['stop_reason']}\n"
            f"Detail: {result.get('stop_detail', '')}"
        )
        assert result["battles_fought"] == 1

    def test_backup_move_turn_limit_safety(self, emu: EmulatorClient):
        """If both moves are the same slot, Torment blocks both — hits turn_limit."""
        load_state(emu, STATE)
        from renegade_mcp.auto_grind import auto_grind
        # backup_move=3 is the same as move_index=3 — both blocked by Torment
        result = auto_grind(emu, move_index=3, backup_move=3, iterations=1)
        # Should hit turn_limit (safety valve) or move_blocked (both blocked)
        assert result["stop_reason"] in ("turn_limit", "move_blocked"), (
            f"Expected turn_limit or move_blocked, got: {result['stop_reason']}"
        )
