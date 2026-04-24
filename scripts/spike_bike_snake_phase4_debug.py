"""Short debug: what does step_hold actually do at fast bike?

Runs two scripts:

  (1) 5 step_holds straight east — characterize per-tile frames_elapsed and
      whether position advances 1 tile per call.

  (2) Single 180 sequence: right, right, LEFT, LEFT, up, up — watch whether
      direction changes mid-run behave cleanly via step_hold (position
      updates as expected, no multi-tile jumps, no stalls).

Print everything per step; no progress threshold. Total ~11 calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.nav_constants import BIKE_HOLD_FRAMES, step_hold  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"


def read_pos(emu):
    base = addresses.addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def read_gear(emu):
    return emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")


def run_sequence(emu, label, steps):
    print(f"\n=== {label} ===")
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    g = read_gear(emu)
    print(f"  start pos=({x},{y}) gear={g}")
    for i, direction in enumerate(steps, 1):
        res = step_hold(emu, direction, BIKE_HOLD_FRAMES)
        nx, ny = read_pos(emu)
        g = read_gear(emu)
        print(f"  step {i:>2} dir={direction:<5s} "
              f"triggered={res.get('triggered', '?')!s:<5s} "
              f"f_elapsed={res.get('frames_elapsed', '?'):>2} "
              f"pos=({x},{y})->({nx},{ny}) gear={g}")
        x, y = nx, ny


def main():
    emu = get_client()
    run_sequence(emu, "A: 5x RIGHT (no turns)", ["right"] * 5)
    run_sequence(emu, "B: 2xRIGHT, 2xLEFT, 2xUP (with turns)",
                 ["right", "right", "left", "left", "up", "up"])


if __name__ == "__main__":
    main()
