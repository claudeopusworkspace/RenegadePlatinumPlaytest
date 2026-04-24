"""Regression tests for QA BUG-047.

BUG-047: ``navigate_to(x=25, y=6, flee_encounters=True)`` from Wayward Cave
B1F (16, 6) raised ``KeyError: 'move'`` when a Repel expired mid-bridge.

Root cause: ``obstacle_tiles`` stores both HM-clearable obstacles (with
``"move"`` / ``"badge"`` keys) and bike-ramp / slope / bridge tiles (without
them). When the Repel-wore-off dialogue blocked a step on the bike bridge,
the executor's step-was-blocked handler found a ``bike_bridge`` entry on
the next tile and routed it to the HM-clear branch. ``_clear_hm_obstacle``
pressed A (coincidentally dismissing the Repel dialogue), then the
"obstacle cleared" log path crashed at ``obs_info["move"]`` because bike
entries don't carry a move.

Fix (``renegade_mcp/navigation.py``):

- Narrow the HM-clear branch in ``_execute_path`` to only fire when
  ``obs_info["type"]`` is actually an HM-clearable type (SURF / ROCK_CLIMB
  / WATERFALL — a.k.a. ``AUTO_NAVIGATE_TYPES``). Bike ramp / bridge
  entries fall through to the generic slow-terrain retry, which
  naturally completes the step once the dialogue is dismissed.
- Extend ``navigate_to``'s ``flee_encounters`` loop to also retry after a
  mid-path dialogue-only encounter (Repel wore off, story trigger, etc.).
  ``_post_nav_check`` has already advanced/dismissed the dialogue, so a
  single call can now complete the full traversal. Accumulates steps and
  joins path segments across resume iterations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helpers import do_load_state as load_state

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


STATE = "bug_nav_repel_expired_move_keyerror"


class TestQaBug047NoKeyError:
    """The core safety invariant: no KeyError when a Repel expires mid-nav."""

    def test_navigate_returns_without_error(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=25, target_y=6, flee_encounters=True)

        assert "error" not in result, (
            f"BUG-047: navigate_to must not KeyError on repel-expiration. "
            f"Got: {result}"
        )

    def test_full_traversal_completes_single_call(self, emu: EmulatorClient) -> None:
        """Repel-wore-off dialogue is auto-dismissed and nav resumes to target."""
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=25, target_y=6, flee_encounters=True)

        final = result.get("final", {})
        assert final.get("x") == 25 and final.get("y") == 6, (
            f"navigate should reach target (25, 6) in a single call after "
            f"repel expiration. Got final={final}"
        )
        assert not result.get("stopped_early"), (
            f"post-fix expectation: dialogue-dismissed resumption means the "
            f"call completes without stopped_early. Got: {result}"
        )

    def test_steps_accumulated_across_resume(self, emu: EmulatorClient) -> None:
        """Steps should reflect the full 9-tile traversal, not just the last leg."""
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=25, target_y=6, flee_encounters=True)

        assert result.get("steps", 0) >= 9, (
            f"BUG-047 resume: expected total steps >= 9 for (16,6)→(25,6); "
            f"got {result.get('steps')}. Result: {result}"
        )

    def test_start_preserved_from_original_position(self, emu: EmulatorClient) -> None:
        """Start should reflect the caller's position, not the resume position."""
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=25, target_y=6, flee_encounters=True)

        start = result.get("start", {})
        assert start.get("x") == 16 and start.get("y") == 6, (
            f"start must preserve the original (16, 6) across resume, "
            f"not jump to the mid-repel position. Got start={start}"
        )
