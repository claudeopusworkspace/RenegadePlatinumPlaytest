"""Empirical spike: frame-by-frame PLAYER_POS_BASE+8 sampling during a bike-ramp jump.

Question: is the value at PLAYER_POS_BASE+8 tile-quantized (integer tile x,
either stepping 1/tile or jumping entry→landing in one write), or does it
interpolate through sub-tile / fx32 values during the jump animation?

If tile-quantized, `advance_frames_until(value == landing_x)` is safe.
If sub-tile, we need `>=` comparison or a /256 scale.

Approach: fresh-load `session31_wayward_cave_bike_ramps`, step to a runway-
sufficient start (x=5, y=17 — 5 tiles of runway before ramp at x=10), force
fast gear, then sample the raw long at PLAYER_POS_BASE+8 EVERY frame while
holding right through the ramp + landing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR  # noqa: E402
from renegade_mcp.navigation import navigate_to as _navigate_to  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "session31_wayward_cave_bike_ramps"
TARGET_ROW = 17
RAMP_X = 10
START_X = 5  # 5 tiles of runway (entry tile counts as 1)
SOCK = ".melonds_test_bridge.sock"


def main() -> None:
    emu = EmulatorClient(SOCK)
    do_load_state(emu, SAVE, redetect_shift=True)
    pos_base = addresses.addr("PLAYER_POS_BASE")
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")

    # Get to (4, 17) reliably via navigate_to, then step right to START_X with
    # settle gaps between presses so each tile is a cold-start press.
    _navigate_to(emu, target_x=4, target_y=TARGET_ROW, flee_encounters=True)
    emu.advance_frames(90)
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")

    for _ in range(START_X - 4):
        emu.advance_frames_until(
            max_frames=30,
            conditions=[{"type": "changed",
                         "address": pos_base + 8, "size": "long"}],
            poll_interval=1,
            buttons=["right"],
        )
        emu.advance_frames(90)
        emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")

    x = emu.read_memory(pos_base + 8, size="long")
    y = emu.read_memory(pos_base + 12, size="long")
    print(f"Pre-hold position: ({x}, {y})  (expected ({START_X}, {TARGET_ROW}))")
    assert (x, y) == (START_X, TARGET_ROW), "failed to reach start tile"

    # Now hold right and sample every single frame.
    print("\n=== Frame-by-frame PLAYER_POS_BASE+8 sampling (holding right) ===")
    print(f"{'frame':>5}  {'x':>6}  {'y':>6}  Δx    note")
    last_x = x
    unique_x = [x]
    for f in range(1, 181):
        emu.advance_frames(1, buttons=["right"])
        nx = emu.read_memory(pos_base + 8, size="long")
        ny = emu.read_memory(pos_base + 12, size="long")
        note = ""
        if nx != last_x:
            dx = nx - last_x
            if nx not in unique_x:
                unique_x.append(nx)
            # Detect ramp landing: jump >1 tile in a single frame is the
            # ramp animation; adjacent ±1 is regular bike step.
            if abs(dx) > 1:
                note = f"  <<< Δx={dx:+} (multi-tile, ramp?)"
            print(f"{f:>5}  {nx:>6}  {ny:>6}  {dx:+}{note}")
            last_x = nx

    print(f"\nDistinct x values observed (in order): {unique_x}")
    final_x = emu.read_memory(pos_base + 8, size="long")
    final_y = emu.read_memory(pos_base + 12, size="long")
    print(f"Final position: ({final_x}, {final_y})")


if __name__ == "__main__":
    main()
