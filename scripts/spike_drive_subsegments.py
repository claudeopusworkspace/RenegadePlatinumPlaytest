"""Spike: validate drive_bike_subsegments on a clean Eterna run.

Loads spike_eterna_open_bike_fast (Eterna City, fast bike, open arena)
and drives a 2-direction continuous-hold segment via the new helper.

Drive: ``up x3 → right x3`` from (304, 542) → (304, 539) → (307, 539).

The helper should:
  * Hold up until y reaches 539 (3 tiles north).
  * Trailing render frame presses RIGHT (final_buttons=[right]).
  * Hold right until x reaches 307 (3 tiles east).
  * Trailing render frame releases inputs.
  * Settle 36 frames; player should remain at (307, 539).

If the bridge handoff works as proved in Phase 6, no overshoot. If not,
we'll see overshoot at the up→right turn.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.nav_constants import _read_position, drive_bike_subsegments  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"


def main():
    emu = get_client()
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    _, sx, sy = _read_position(emu)
    print(f"start=({sx},{sy})")
    assert (sx, sy) == (304, 542)

    subsegments = [
        ("up",    304, 539),  # 3 tiles north
        ("right", 307, 539),  # 3 tiles east
    ]
    print(f"sub-segments: {subsegments}")
    results = drive_bike_subsegments(emu, subsegments)
    for i, r in enumerate(results):
        print(f"  [{i}] triggered={r.get('triggered')!s:<5s} "
              f"f_elapsed={r.get('frames_elapsed')}")

    _, ex, ey = _read_position(emu)
    print(f"end=({ex},{ey})  expected (307, 539)")
    print("PASS" if (ex, ey) == (307, 539) else f"FAIL drift=({ex - 307},{ey - 539})")


if __name__ == "__main__":
    main()
