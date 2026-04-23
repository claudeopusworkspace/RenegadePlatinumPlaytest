"""Empirical spike: does _traverse_bike_slope succeed from different approach tiles?

The production helper backs up 3 tiles itself before holding direction, so in
principle the approach momentum shouldn't matter. Woj observed that in-play
the helper stalls when entered via a turn. This spike runs the helper directly
from each approach position and reports whether the player crests the slope.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from renegade_mcp import addresses
from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR
from renegade_mcp.connection import get_client
from renegade_mcp.cycling_road import _traverse_bike_slope
from helpers import do_load_state

SAVE = "bug_bike_slope_turn_into_approach"


def read_pos(emu) -> tuple[int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    return (
        emu.read_memory(base + 8, size="long"),
        emu.read_memory(base + 12, size="long"),
    )


def step_dir(emu, direction: str, max_frames: int = 30) -> bool:
    base = addresses.addr("PLAYER_POS_BASE")
    axis = 8 if direction in ("left", "right") else 12
    res = emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[{"type": "changed", "address": base + axis, "size": "long"}],
        poll_interval=1,
        buttons=[direction],
    )
    return bool(res.get("triggered"))


def trial(emu, steps: list[str], expected_final_pos: tuple[int, int], label: str):
    """Load state, execute `steps` ([left/down/up/right]), then call _traverse_bike_slope."""
    do_load_state(emu, SAVE, redetect_shift=True)
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")
    emu.advance_frames(30)

    for s in steps:
        ok = step_dir(emu, s)
        if not ok:
            print(f"  [{label}] FAIL: couldn't {s}")
            return
        emu.advance_frames(30)
        emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")

    pre_x, pre_y = read_pos(emu)
    if (pre_x, pre_y) != expected_final_pos:
        print(f"  [{label}] pre-helper position drift: expected {expected_final_pos} "
              f"got ({pre_x},{pre_y})")
        return

    # Now call the helper: direction=up, old_x=pre_x, old_y=pre_y,
    # num_slope_tiles=2 (slope tiles are (7,26) and (7,27))
    fx, fy, moved = _traverse_bike_slope(
        emu, direction="up", old_x=pre_x, old_y=pre_y, num_slope_tiles=2
    )
    crossed = fy < 26
    print(f"  [{label:>30}] pre=({pre_x},{pre_y}) final=({fx},{fy}) "
          f"moved={moved} crossed_slope={'✔' if crossed else '✗'}")


def main():
    emu = get_client()
    print(f"=== Bike slope helper spike — {SAVE} ===")
    print("Slope at (7, 27)=bottom, (7, 26)=top. Helper backs up 3 tiles + "
          "holds direction for up to 600f.")
    print()

    # TURN-INTO-APPROACH: left from start, then call helper with direction=up
    trial(emu, ["left"], (7, 28), "TURN (left only)")

    # STRAIGHT: arrive at (7, 28) via at least 1 prior up step
    # To do this, step left then down N then up (N-1) to arrive "from below"
    trial(emu, ["left", "down", "up"], (7, 28), "STRAIGHT-1 (from (7,29))")
    trial(emu, ["left", "down", "down", "up", "up"], (7, 28), "STRAIGHT-2 (from (7,30))")
    trial(emu, ["left", "down", "down", "down", "up", "up", "up"], (7, 28),
          "STRAIGHT-3 (from (7,31))")


if __name__ == "__main__":
    main()
