"""Empirical spike: bike-ramp runway + landing distance on fast gear.

Uses `session31_wayward_cave_bike_ramps` (Wayward Cave B1F, player on-bike in
west chamber). Row 17 has an east-facing ramp chain. We want:

  - the minimum **runway length** (straight-line tiles held in the ramp
    direction before the ramp tile) needed for the engine to trigger the jump;
  - the **landing tile** relative to the ramp;
  - whether chained ramps auto-chain when momentum is preserved.

Approach: for each requested X_start, fresh-load the state, `navigate_to`
(X_start, 17), release for 90 frames (drain fast-bike momentum from nav),
then hold right indefinitely and sample position every 2 frames. Record
actual starting tile (nav may land short/long — we take whatever tile the
player settled on), final tile, and intermediate trajectory samples.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.navigation import navigate_to as _navigate_to  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from helpers import do_load_state  # noqa: E402


SAVE = "session31_wayward_cave_bike_ramps"
TARGET_ROW = 17
SAMPLE_INTERVAL = 2
MAX_HOLD_FRAMES = 300
SETTLE_FRAMES_AFTER_NAV = 90


def read_pos(emu: EmulatorClient) -> tuple[int, int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    m = emu.read_memory(base, size="long")
    x = emu.read_memory(base + 8, size="long")
    y = emu.read_memory(base + 12, size="long")
    return m, x, y


def force_fast_gear(emu: EmulatorClient) -> None:
    """Spike-only: force bike gear byte to 0 (fast)."""
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")


def run_trial(emu: EmulatorClient, start_x: int) -> dict:
    """Fresh-load, nav to (4,17), step right to (start_x,17), settle, hold right.

    nav_to(4, 17) is the only stable target on row 17 from this save (the bike
    overshoots on closer targets). We use explicit per-tile right-steps with
    release-settle between them to reach `start_x`. This keeps the runway
    measurement deterministic without memory-write hacks that the engine reverts.
    """
    do_load_state(emu, SAVE, redetect_shift=True)
    force_fast_gear(emu)

    try:
        _navigate_to(emu, target_x=4, target_y=TARGET_ROW, flee_encounters=True)
    except Exception as e:
        return {"start_x": start_x, "error": f"nav: {e}"}
    emu.advance_frames(SETTLE_FRAMES_AFTER_NAV)
    force_fast_gear(emu)

    base = addresses.addr("PLAYER_POS_BASE")
    _, cur_x, cur_y = read_pos(emu)
    if (cur_x, cur_y) != (4, TARGET_ROW):
        return {"start_x": start_x, "actual_start": (cur_x, cur_y),
                "error": f"nav didn't reach (4,17), got ({cur_x},{cur_y})"}

    # Step right one tile at a time with momentum-draining gaps between presses.
    # 12 frames covers the cold-start first tile; 90f settle afterwards drains
    # any residual sub-tile pixel drift so the next press starts from rest.
    for _ in range(start_x - 4):
        res = emu.advance_frames_until(
            max_frames=30,
            conditions=[{"type": "changed", "address": base + 8, "size": "long"}],
            poll_interval=1,
            buttons=["right"],
        )
        if not res.get("triggered"):
            return {"start_x": start_x, "error": "stuck stepping right"}
        emu.advance_frames(90)  # drain momentum between tiles
        force_fast_gear(emu)

    _, actual_start_x, actual_start_y = read_pos(emu)
    if (actual_start_x, actual_start_y) != (start_x, TARGET_ROW):
        return {
            "start_x": start_x,
            "actual_start": (actual_start_x, actual_start_y),
            "error": "didn't land on requested start tile",
        }

    trajectory: list[tuple[int, int, int]] = [(actual_start_x, actual_start_y, 0)]
    frames_elapsed = 0
    stall_frames = 0
    last_pos = (actual_start_x, actual_start_y)
    while frames_elapsed < MAX_HOLD_FRAMES:
        emu.advance_frames(SAMPLE_INTERVAL, buttons=["right"])
        frames_elapsed += SAMPLE_INTERVAL
        x = emu.read_memory(base + 8, size="long")
        y = emu.read_memory(base + 12, size="long")
        if (x, y) != last_pos:
            trajectory.append((x, y, frames_elapsed))
            last_pos = (x, y)
            stall_frames = 0
        else:
            stall_frames += SAMPLE_INTERVAL
            if stall_frames >= 60:
                break

    emu.advance_frames(60)  # final settle
    _, final_x, final_y = read_pos(emu)
    return {
        "start_x": start_x,
        "actual_start": (actual_start_x, actual_start_y),
        "trajectory": trajectory,
        "final": (final_x, final_y),
    }


def fmt_trial(r: dict) -> None:
    if "error" in r:
        print(f"  start=({r.get('start_x', '?')},17): ERROR {r['error']}")
        return
    start = r["actual_start"]
    final = r["final"]
    traj = r["trajectory"]
    ramp_fired = final[0] - start[0] > 1  # moved more than "one tile east"
    print(f"  start={start} final={final} | {len(traj)} samples | runway={start[0]-4+1}t to ramp@(10,17) | ramp_fired={ramp_fired}")
    for i, (x, y, f) in enumerate(traj):
        if i == 0:
            print(f"    s    ({x:>3},{y:>3}) @ f={f:>4}")
            continue
        px, py, pf = traj[i - 1]
        dx = x - px
        dy = y - py
        df = f - pf
        big = "  <<< RAMP?" if abs(dx) + abs(dy) > 1 else ""
        print(f"    {i:>3}  ({x:>3},{y:>3}) @ f={f:>4}  "
              f"(Δx={dx:+}, Δy={dy:+}, Δf={df}){big}")


def main():
    emu = get_client()
    do_load_state(emu, SAVE, redetect_shift=True)
    m, x, y = read_pos(emu)
    print(f"Loaded {SAVE}: map={m} pos=({x},{y})")
    gear = emu.read_memory(BIKE_GEAR_STATE_ADDR, size="byte")
    on_bike = emu.read_memory(addresses.addr("CYCLING_GEAR_ADDR"), size="short")
    print(f"  initial on_bike={on_bike} bike_gear={gear} (0=fast, 1=slow)")

    print("\n=== Ramp runway sweep (ramp at x=10) ===")
    print("Fresh-load + nav to (4,17) + step-right to start + 90f settle + hold-right. ")
    print("runway = tiles between start and ramp (inclusive of approach tile).")
    for start_x in (9, 8, 7, 6, 5, 4):  # 1, 2, 3, 4, 5, 6 tiles of runway
        r = run_trial(emu, start_x)
        fmt_trial(r)


if __name__ == "__main__":
    main()
