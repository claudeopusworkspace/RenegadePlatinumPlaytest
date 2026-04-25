"""Spike: drive the BUG-048 east-chamber path via drive_bike_subsegments.

Loads ``bug_bike_ramps_repel`` (player at (7, 22)) and drives the
post-fix BFS plan as ONE continuous fast-bike hold:

  Sub-segment 1: ("up",    7, 17)  — 5 tiles north, accel ramp
  Sub-segment 2: ("right", 26, 17) — 3 walk + 4 chained FAR ramps,
                                     release at last ramp tile

After settle_frames=36, the engine should land the player at (30, 17)
(ramp4's natural FAR landing). One per-tile walk then takes us to
(31, 17), the Pokéball interaction tile.

If this works end-to-end, the executor rewrite is a wiring exercise
on top of this primitive — all the engine work is done by the bridge
+ final_buttons handoff.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.nav_constants import (  # noqa: E402
    BIKE_HOLD_FRAMES, _read_position, drive_bike_subsegments, step_hold,
)
from renegade_mcp.use_item import _set_bike_gear  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "bug_bike_ramps_repel"


def main():
    emu = get_client()
    do_load_state(emu, SAVE)
    emu.advance_frames(60)  # let the load settle a bit
    _, sx, sy = _read_position(emu)
    print(f"start=({sx},{sy})  expected (7, 22)")
    assert (sx, sy) == (7, 22)

    # The BUG-048 plan needs FAST gear for FAR ramp jumps.
    # _set_bike_gear(0) means "fast" in decomp semantics (the helper
    # inverts internally to byte=1). It's a no-op if already fast.
    _set_bike_gear(emu, 0)
    emu.advance_frames(30)

    # Test 1: drive all the way to goal (31, 17). Goal is a walk tile
    # past ramp4's landing.
    subsegments = [
        ("up",    7,  17),
        ("right", 31, 17),
    ]
    print(f"\nTest 1 sub-segments: {subsegments}")
    results = drive_bike_subsegments(emu, subsegments, settle_frames=0)
    _, ax, ay = _read_position(emu)
    print(f"  POST-CALLS pos=({ax},{ay})  [expected (31, 17)]")
    emu.advance_frames(60)
    _, fx, fy = _read_position(emu)
    print(f"  POST-60f-idle pos=({fx},{fy})")

    # Test 2: target is ramp4's landing (30, 17). Watch fires mid-jump.
    do_load_state(emu, SAVE)
    emu.advance_frames(60)
    _set_bike_gear(emu, 0)
    emu.advance_frames(30)
    subsegments2 = [
        ("up",    7,  17),
        ("right", 30, 17),
    ]
    print(f"\nTest 2 sub-segments: {subsegments2}  [target = ramp4 landing]")
    results = drive_bike_subsegments(emu, subsegments2, settle_frames=0)
    _, ax, ay = _read_position(emu)
    print(f"  POST-CALLS pos=({ax},{ay})  [expected (30, 17)]")
    emu.advance_frames(60)
    _, fx, fy = _read_position(emu)
    print(f"  POST-60f-idle pos=({fx},{fy})")

    # Test 3: target is a ramp tile itself (26, 17 = ramp4) — does the
    # engine still fire the jump if we release at the ramp entry?
    do_load_state(emu, SAVE)
    emu.advance_frames(60)
    _set_bike_gear(emu, 0)
    emu.advance_frames(30)
    subsegments3 = [
        ("up",    7,  17),
        ("right", 26, 17),
    ]
    print(f"\nTest 3 sub-segments: {subsegments3}  [target = ramp4 entry]")
    results = drive_bike_subsegments(emu, subsegments3, settle_frames=0)
    _, ax, ay = _read_position(emu)
    print(f"  POST-CALLS pos=({ax},{ay})  [expected (26, 17)]")
    emu.advance_frames(60)
    _, fx, fy = _read_position(emu)
    print(f"  POST-60f-idle pos=({fx},{fy})")
    for i, r in enumerate(results):
        print(f"  [{i}] triggered={r.get('triggered')!s:<5s} "
              f"f_elapsed={r.get('frames_elapsed')}")



if __name__ == "__main__":
    main()
