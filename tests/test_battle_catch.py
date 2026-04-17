"""Tests for throw_ball and post-catch recovery.

Covers the core `throw_ball` tool plus the QA BUG-001 fixes in
`battle_tracker._format_log` (Gen 4 [FFFE] triplet handling) and
`catch._recover_from_catch` (formatted rebuild after a TIMEOUT→CAUGHT
fallback path).

Save states used:
  test_wild_battle_action — Prinplup vs wild Smoochum, action prompt (throw).
  bug_qa_throw_ball_state_mismatch — Post-catch state (Shinx already in party);
    used only for documentation — the unit tests exercise the _format_log /
    _recover_from_catch fix points directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import retry_on_rng


class TestThrowBall:
    """Catching Pokemon."""

    @retry_on_rng("test_wild_battle_action")
    def test_throw_ball_returns_valid_state(self, emu: EmulatorClient):
        """Throw a ball — returns CAUGHT, NOT_CAUGHT, or BATTLE_ENDED."""
        from renegade_mcp.catch import throw_ball
        result = throw_ball(emu)
        assert "final_state" in result, f"Missing final_state in: {list(result.keys())}"
        assert result["final_state"] in ("CAUGHT", "NOT_CAUGHT", "BATTLE_ENDED"), (
            f"Unexpected final_state: {result['final_state']}"
        )

    @retry_on_rng("test_wild_battle_action")
    def test_throw_ball_has_log(self, emu: EmulatorClient):
        """Catch attempt includes battle log entries."""
        from renegade_mcp.catch import throw_ball
        result = throw_ball(emu)
        assert "log" in result, f"Missing log in: {list(result.keys())}"
        assert len(result["log"]) > 0, "Log should not be empty after throw"


# ---------------------------------------------------------------------------
# QA BUG-001: throw_ball formatted shows "State: TIMEOUT" after CAUGHT
# ---------------------------------------------------------------------------

class TestQaBug001ThrowBallFormatted:
    """_format_log [FFFE] handling + _recover_from_catch formatted rebuild.

    The QA save state is post-catch (Shinx already in party), so the full
    throw_ball flow can't be re-run. Instead we unit-test the two fix points
    directly: _format_log must not empty lines starting with [FFFE]..., and
    _recover_from_catch must rebuild result["formatted"] with the CAUGHT state.
    """

    def test_format_log_strips_fffe_triplet_prefix(self):
        """Line starting with [FFFE][0202][XXXX][XXXX] keeps the trailing text."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "[FFFE][0202][0001][0003]Gotcha! Shinx was caught!", "stop": "AUTO_ADVANCE"}]
        out = _format_log(log, "CAUGHT")
        assert "Gotcha! Shinx was caught!" in out, (
            f"[FFFE]-prefixed text truncated; got: {out!r}"
        )
        assert "State: CAUGHT" in out

    def test_format_log_strips_fffe_0200_action_prompt(self):
        """WAIT_FOR_ACTION [FFFE][0200] marker is stripped without truncating line."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "What will [FFFE][0200]Luxray do?", "stop": "WAIT_FOR_ACTION"}]
        out = _format_log(log, "WAIT_FOR_ACTION")
        assert "What will" in out
        assert "Luxray do?" in out
        assert "[FFFE]" not in out
        assert "[0200]" not in out

    def test_format_log_inline_fffe_preserves_surrounding_text(self):
        """[FFFE] substitution mid-line drops the var tokens but keeps text."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "Shinx grew to Lv. [FFFE][0202][0001][0002]!", "stop": "AUTO_ADVANCE"}]
        out = _format_log(log, "BATTLE_ENDED")
        assert "Shinx grew to Lv." in out
        assert "[FFFE]" not in out
        # The trailing "!" after the triplet survives the substitution.
        assert "!" in out

    def test_format_log_no_fffe_is_unchanged(self):
        """Plain text without [FFFE] is formatted as-is."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "Shinx fainted!", "stop": "AUTO_ADVANCE"}]
        out = _format_log(log, "BATTLE_ENDED")
        assert "Shinx fainted!" in out

    def test_recover_from_catch_rebuilds_formatted(self):
        """_recover_from_catch overwrites the stale formatted tail from the tracker poll."""
        from unittest.mock import MagicMock
        from renegade_mcp import catch as catch_mod

        # Stub _is_battle_over so the recovery loop exits on the first iteration.
        original_over = catch_mod._is_battle_over
        catch_mod._is_battle_over = lambda emu: True
        try:
            fake_emu = MagicMock()
            # Tracker-style poll result with stale "State: TIMEOUT" in formatted.
            initial_formatted = (
                "=== Battle Log ===\n"
                "  \n"  # The [FFFE]-prefixed catch line was truncated to empty.
                "\nState: TIMEOUT"
            )
            result = {
                "log": [{"text": "[FFFE][0202][0001][0003]Gotcha! Shinx was caught!",
                         "stop": "AUTO_ADVANCE"}],
                "final_state": "TIMEOUT",
                "formatted": initial_formatted,
            }
            fixed = catch_mod._recover_from_catch(fake_emu, result)
        finally:
            catch_mod._is_battle_over = original_over

        assert fixed["final_state"] == "CAUGHT"
        assert "State: CAUGHT" in fixed["formatted"]
        assert "State: TIMEOUT" not in fixed["formatted"]
        # After the _format_log fix the "Gotcha!" line survives reformatting.
        assert "Gotcha! Shinx was caught!" in fixed["formatted"]
