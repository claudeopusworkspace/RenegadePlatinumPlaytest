"""Regression tests for BUG-049.

BUG-049: ``navigate_to(x=38, y=12)`` from Wayward Cave B1F (42, 6) ran the
bike-ramp chain segment correctly, landed exactly on the predicted (38, 12),
then drifted 3 tiles south to (38, 15) during the post-segment
``_set_bike_gear(emu, 1) + advance_frames(120)`` "drain" idle. The
``reached`` check tripped ``False``, and the executor fell through to
per-tile execution — which dutifully walked the *remaining 7 BFS-planned
directions* (computed assuming arrival at (38, 12)) from the wrong
starting point. Result: player ended at (35, 20), 3D BFS retry from there
failed (different elevation level), 2D fallback chose an 80-step long
loop around the chamber, bonked walls, and ate a wild encounter at
(12, 12).

Fix (``renegade_mcp/navigation.py`` ``_execute_path``): when the bike
segment overshoots (``reached=False``), the remaining directions are
stale relative to the actual position. Instead of falling through to
per-tile, call ``_try_repath`` from the post-segment position and
splice the new BFS plan into ``directions[:i]``. This keeps the executor
on a coherent plan regardless of where the bike-momentum drift lands the
player.

The fix is a band-aid for the underlying drift (the gear-toggle-then-idle
"drain" doesn't actually drain bike momentum), but bike momentum on the
Pokemon Platinum engine is fundamentally awkward to model exactly, so a
post-hoc repath is a robust fallback regardless of the drift's mechanics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helpers import do_load_state as load_state

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


STATE = "bug048_wayward_b1f_east_chamber_via_chain_through"


class TestQaBug049BikeSegmentOvershootRepath:
    """The core invariant: bike-segment overshoot recovers via repath, not
    by walking stale directions from the wrong position."""

    def test_reaches_target_after_overshoot(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=38, target_y=12)

        final = result.get("final", {})
        assert final.get("x") == 38 and final.get("y") == 12, (
            f"BUG-049: navigate_to must reach (38, 12) even when the "
            f"bike-segment driver overshoots its planned landing. "
            f"Got final={final}, full result={result}"
        )

    def test_does_not_stop_early(self, emu: EmulatorClient) -> None:
        """Pre-fix: stopped_early=True with blocked_at=(12, 12) after the
        2D-fallback long-loop bonked walls. Post-fix: clean completion."""
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=38, target_y=12)

        assert not result.get("stopped_early"), (
            f"BUG-049: post-fix expectation is clean completion (no "
            f"stopped_early). Got: {result}"
        )

    def test_no_wild_encounter_on_path(self, emu: EmulatorClient) -> None:
        """Pre-fix: the long-loop fallback wandered into the western
        chamber at low Y and ate a Zubat. Post-fix: short repath stays
        within the planned region."""
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=38, target_y=12)

        assert "encounter" not in result, (
            f"BUG-049: short repath should not provoke a wild encounter. "
            f"Got: {result}"
        )

    def test_overshoot_recovery_keeps_repaths_low(self, emu: EmulatorClient) -> None:
        """Repath count stays at 0 or 1 — the executor must not chain
        repaths through the chamber.

        Pre-fix (BUG-049): segment over-claimed to (38, 12), drifted to
        (38, 15) on the post-segment "drain" idle, fell through to per-tile
        with stale directions, ended up at (35, 20) on a different
        elevation, 2D fallback long-looped to wall-bonks → many repaths.

        Post-BUG-049 fix: 1 repath — the band-aid recognises the overshoot,
        repaths from the actual post-segment position, and a short up-walk
        finishes the trip.

        Post session-51 segment-termination fix: 0 repaths — the segment
        now closes at (38, 8) (the last ramp's natural landing), so no
        post-segment drift past the predicted target can happen, and
        per-tile execution drives the trailing ``down x4`` cleanly. The
        band-aid stays in place for plans where the segment legitimately
        spans past a single ramp landing and the post-segment idle still
        coasts; this test scenario just no longer exercises that path.
        """
        load_state(emu, STATE)
        from renegade_mcp.navigation import navigate_to

        result = navigate_to(emu, target_x=38, target_y=12)

        repaths = result.get("repaths", 0)
        assert repaths <= 1, (
            f"BUG-049: expected at most 1 repath (segment overshoot "
            f"recovery, or 0 if the segment terminated cleanly). "
            f"Got repaths={repaths}, result={result}"
        )
