"""Empirical spike: bike-slope runway on fast gear.

Repro save `bug_bike_slope_turn_into_approach` — Wayward Cave B1F at (8, 28),
on bike. A south-facing bike slope at (7, 27)/(7, 26) blocks the east chamber.
View_map shows the straight south-approach corridor at x=7 from y=28 down to
y=33 (all passable cave_floor). Ledges `v` at y=22 preclude coming back down
the same corridor from the north.

Questions:
  1. Does a turn-into-approach (arrive at (7, 28) via left, then step up) ever
     succeed in crossing the slope?
  2. If not, how many tiles of straight-line north-momentum (consecutive `up`
     steps into (7, 28)) does the engine need before the slope fires?

Approach: for each N in {0, 1, 2, 3, 4}, fresh-load + teleport-navigate to
(7, 28+N), then hold `up` continuously and measure whether the player crests
the slope tiles at (7, 26)/(7, 27). N=0 = turn-into-approach (arrive via
left from (8, 28)); N≥1 = walk down N tiles from (7, 28), then hold up.

Output: final Y coord after 300 frames of held `up`, and whether the slope
fired (crossed both 0xD9 and 0xDA tiles).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient
from renegade_mcp import addresses
from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR
from renegade_mcp.connection import get_client
from helpers import do_load_state

SAVE = "bug_bike_slope_turn_into_approach"
SETTLE = 60
MAX_HOLD = 300


def read_pos(emu: EmulatorClient) -> tuple[int, int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    m = emu.read_memory(base, size="long")
    x = emu.read_memory(base + 8, size="long")
    y = emu.read_memory(base + 12, size="long")
    return m, x, y


def force_fast_gear(emu: EmulatorClient) -> None:
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")


def step_dir(emu: EmulatorClient, direction: str, max_frames: int = 30) -> bool:
    """Hold `direction` until position changes; return True if movement happened."""
    base = addresses.addr("PLAYER_POS_BASE")
    axis = 8 if direction in ("left", "right") else 12
    res = emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[{"type": "changed", "address": base + axis, "size": "long"}],
        poll_interval=1,
        buttons=[direction],
    )
    return bool(res.get("triggered"))


def run_trial(emu: EmulatorClient, approach_tiles: int, via_turn: bool) -> dict:
    """Fresh-load, position the player south of the slope approach, then hold up.

    approach_tiles: number of `up` steps the player takes before the approach
        tile (7, 28). 0 = arrive at (7, 28) from the side (via_turn=True) or
        start at (7, 28) with no prior momentum (via_turn=False).
    via_turn: when True, arrive at the approach tile (7, 28) via a left step
        from (8, 28). When False, arrive via `up` from (7, 28 + approach_tiles).
    """
    do_load_state(emu, SAVE, redetect_shift=True)
    force_fast_gear(emu)
    emu.advance_frames(SETTLE)

    # Trial 0 "via_turn": just step left then up from start (8, 28).
    if via_turn and approach_tiles == 0:
        if not step_dir(emu, "left"):
            return {"error": "couldn't step left from start"}
        emu.advance_frames(8)  # brief inter-step idle — not enough to drain gear
    else:
        # Walk down to (7, 28 + approach_tiles): first left to (7, 28), then
        # down N times. Release between steps so we start the up-hold with
        # no pre-accumulated momentum until the approach run begins.
        if not step_dir(emu, "left"):
            return {"error": "couldn't step left from start"}
        emu.advance_frames(30)  # drain
        force_fast_gear(emu)
        for _ in range(approach_tiles):
            if not step_dir(emu, "down"):
                return {"error": "couldn't step down"}
            emu.advance_frames(30)
            force_fast_gear(emu)

    _, sx, sy = read_pos(emu)

    # Hold up continuously for up to MAX_HOLD frames.
    base = addresses.addr("PLAYER_POS_BASE")
    trajectory: list[tuple[int, int, int]] = [(sx, sy, 0)]
    frames = 0
    stall = 0
    last = (sx, sy)
    while frames < MAX_HOLD:
        emu.advance_frames(2, buttons=["up"])
        frames += 2
        x = emu.read_memory(base + 8, size="long")
        y = emu.read_memory(base + 12, size="long")
        if (x, y) != last:
            trajectory.append((x, y, frames))
            last = (x, y)
            stall = 0
        else:
            stall += 2
            if stall >= 60:
                break

    emu.advance_frames(60)
    _, fx, fy = read_pos(emu)
    crossed_slope = fy < 26  # past both slope tiles
    return {
        "approach_tiles": approach_tiles,
        "via_turn": via_turn,
        "start": (sx, sy),
        "final": (fx, fy),
        "crossed_slope": crossed_slope,
        "trajectory": trajectory,
    }


def fmt_trial(r: dict) -> None:
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        return
    tag = "TURN" if r["via_turn"] else f"STRAIGHT-{r['approach_tiles']}"
    cross = "✔" if r["crossed_slope"] else "✗"
    print(f"  [{tag:>12}] start={r['start']} final={r['final']} "
          f"slope_crossed={cross} samples={len(r['trajectory'])}")
    for i, (x, y, f) in enumerate(r["trajectory"][:20]):
        if i == 0:
            print(f"      s    ({x:>3},{y:>3}) @ f={f:>4}")
            continue
        px, py, pf = r["trajectory"][i - 1]
        print(f"      {i:>3}  ({x:>3},{y:>3}) @ f={f:>4}  "
              f"(Δx={x-px:+}, Δy={y-py:+}, Δf={f-pf})")
    if len(r["trajectory"]) > 20:
        print(f"      ... ({len(r['trajectory']) - 20} more)")


def main():
    emu = get_client()
    print(f"=== Bike slope runway spike — {SAVE} ===")
    print("Slope at (7, 27)=bottom (0xDA), (7, 26)=top (0xD9). Player starts "
          "at (8, 28) on-bike fast gear.")
    print()

    trials = [
        (0, True),   # Turn-into-approach: just left, then up
        (0, False),  # Start at (7, 28), no prior momentum
        (1, False),  # 1 tile south of approach, walk up then continue
        (2, False),
        (3, False),
        (4, False),
    ]
    for approach, via_turn in trials:
        r = run_trial(emu, approach, via_turn)
        fmt_trial(r)


if __name__ == "__main__":
    main()
