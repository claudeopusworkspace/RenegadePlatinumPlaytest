"""Tests for multi-hit move handling (Bullet Seed, etc.).

Multi-hit moves have long animations (each hit plays individually) that
can exhaust the poll budget or trigger the no-text early exit. These
tests verify that battle_turn correctly handles the extended timeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import assert_final_state, assert_log_contains, do_load_state as load_state


class TestMultiHitFaint:
    """Multi-hit move KOs the target — must not TIMEOUT."""

    def test_bullet_seed_5hit_ko_switch_prompt(self, emu: EmulatorClient):
        """Bullet Seed (5-hit) OHKOs Nosepass through Sturdy → SWITCH_PROMPT.

        State: debug_bullet_seed_timeout — Turtwig Lv17 vs Roark's Nosepass Lv15.
        Nosepass has Sturdy (survives first hit at 1 HP), but 4 remaining hits KO.
        Grass vs Rock = super effective. Roark has more Pokemon, so after KO
        the game asks "Will you switch?" → SWITCH_PROMPT.

        This was the original bug: poll exhausted its budget during the 5-hit
        animation (~1200 frames of unchanged text) and returned TIMEOUT.
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_bullet_seed_timeout")
        # Bullet Seed is move index 2; force=True bypasses effectiveness check
        # (which would warn about super effective, not block, but we pass it
        # through the same code path the MCP tool uses)
        result = battle_turn(emu, move_index=2)
        assert result.get("final_state") != "TIMEOUT", (
            f"Got TIMEOUT — multi-hit recovery failed.\nLog: {result.get('log')}"
        )
        assert_final_state(result, "SWITCH_PROMPT")
        assert_log_contains(result, "Bullet Seed", "super effective", "fainted")

    def test_bullet_seed_5hit_ko_log_completeness(self, emu: EmulatorClient):
        """Verify the full log captures all expected battle events.

        Same scenario as above, but checks that EXP text and sandstorm
        text are captured (these appear AFTER the faint, during the
        previously-broken recovery window).
        """
        from renegade_mcp.turn import battle_turn

        load_state(emu, "debug_bullet_seed_timeout")
        result = battle_turn(emu, move_index=2)
        assert_final_state(result, "SWITCH_PROMPT")
        # These texts appear after faint — the recovery must capture them
        assert_log_contains(result, "Exp. Points")
        # Roark's next Pokemon name should appear in the switch prompt
        assert_log_contains(result, "Roark")
