"""Diagnostic: trace _bike_ramp_segment + drive on session31 → warp:0.

Loads session31_wayward_cave_bike_ramps, computes the FIRST BFS plan
to warp:0's interaction tile (43, 38), then runs `_execute_path` with
a wrapped `_bike_ramp_segment` that prints predicted vs actual landings
per call. Also samples player position at each loop iteration to log
where the executor really is when the planned step starts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

import renegade_mcp.navigation as nav  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.nav_constants import _read_position  # noqa: E402
from renegade_mcp.navigation import _navigate_to_impl  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "session31_wayward_cave_bike_ramps"


def main():
    emu = get_client()
    do_load_state(emu, SAVE)
    emu.advance_frames(60)
    _, sx, sy = _read_position(emu)
    print(f"start=({sx},{sy})")

    # Wrap _bike_ramp_segment to log every call (predicted) and we also
    # log post-drive position via wrapping drive_bike_subsegments.
    orig_seg = nav._bike_ramp_segment

    def wrapped_seg(directions, i, obstacle_tiles, cur_x, cur_y, **kw):
        # Trace the simulation by re-implementing inline — print every iter
        from renegade_mcp.nav_constants import _DIR_DELTAS, BIKE_RAMP_TYPES, BIKE_RAMP_RUNWAY_TILES, BIKE_RAMP_JUMP_TILES
        print(f"\n  [seg-trace] start i={i} pos=({cur_x},{cur_y})")
        fx, fy = cur_x, cur_y
        mom = 0
        j = i
        while j < len(directions):
            d = directions[j]
            dx, dy = _DIR_DELTAS.get(d, (0, 0))
            if dx == 0 and dy == 0:
                print(f"    [trace] j={j} {d} stop-zero")
                break
            nx, ny = fx + dx, fy + dy
            obs = obstacle_tiles.get((nx, ny))
            is_ramp = obs is not None and obs.get("type") in BIKE_RAMP_TYPES
            note = ""
            if is_ramp:
                from renegade_mcp.navigation import _bike_ramp_segment as _seg_fn  # noqa
                # Just log the same logic
                if mom + 1 >= BIKE_RAMP_RUNWAY_TILES:
                    fx_pre = fx
                    fx += dx * BIKE_RAMP_JUMP_TILES
                    fy += dy * BIKE_RAMP_JUMP_TILES
                    mom = BIKE_RAMP_RUNWAY_TILES
                    note = f"RAMP@{(nx,ny)} approach=({fx_pre},{fy}) jump=4 land=({fx},{fy})"
                else:
                    note = "RAMP-stall"
            else:
                fx, fy = nx, ny
                mom = min(mom + 1, BIKE_RAMP_RUNWAY_TILES)
                note = f"walk -> ({fx},{fy}) m={mom}"
            print(f"    [trace] j={j} {d:5s} {note}")
            if j > i + 30:
                print("    [trace] ...truncated")
                break
            j += 1
        result = orig_seg(directions, i, obstacle_tiles, cur_x, cur_y, **kw)
        if result is None:
            print(f"  [seg] i={i} pos=({cur_x},{cur_y}) -> None  d={directions[i] if i < len(directions) else '?'}")
        else:
            print(f"  [seg] i={i} pos=({cur_x},{cur_y}) -> last={result['last_ramp_idx']} land=({result['landing_x']},{result['landing_y']}) gear={result['segment_gear']} sub={result['subsegments']}")
        return result

    nav._bike_ramp_segment = wrapped_seg

    # Capture obstacle_tiles via wrapping _execute_path so we can dump it
    orig_exec = nav._execute_path

    def wrapped_exec(emu, directions, **kw):
        ot = kw.get("obstacle_tiles")
        if ot:
            print(f"\n--- obstacle_tiles (count={len(ot)}) ---")
            for k, v in sorted(ot.items()):
                print(f"  {k}: {v}")
            print()
        return orig_exec(emu, directions, **kw)

    nav._execute_path = wrapped_exec

    # Also instrument step_hold so we can see per-tile pre/post coords
    from renegade_mcp import nav_constants as nc
    orig_step_hold = nc.step_hold

    def wrapped_step_hold(emu, direction, hold_frames, **kw):
        _, bx, by = _read_position(emu)
        result = orig_step_hold(emu, direction, hold_frames, **kw)
        _, ax, ay = _read_position(emu)
        marker = "MOVE" if (ax, ay) != (bx, by) else "BLOCK"
        print(f"  [walk] {direction:5s} ({bx},{by}) -> ({ax},{ay}) [{marker}] hold={hold_frames}")
        return result

    nc.step_hold = wrapped_step_hold
    nav.step_hold = wrapped_step_hold

    # Also instrument drive_bike_subsegments
    orig_drive = nc.drive_bike_subsegments

    def wrapped_drive(emu, subsegments, settle_frames=0, **kw):
        _, bx, by = _read_position(emu)
        print(f"  [drive] start=({bx},{by})  subsegments={subsegments}")
        result = orig_drive(emu, subsegments, settle_frames=settle_frames, **kw)
        _, ax, ay = _read_position(emu)
        print(f"  [drive] end=({ax},{ay})  settle={settle_frames}")
        return result

    nc.drive_bike_subsegments = wrapped_drive
    nav.drive_bike_subsegments = wrapped_drive

    try:
        result = _navigate_to_impl(emu, 43, 38)
    finally:
        nav._bike_ramp_segment = orig_seg
        nc.step_hold = orig_step_hold
        nav.step_hold = orig_step_hold
        nc.drive_bike_subsegments = orig_drive
        nav.drive_bike_subsegments = orig_drive
        nav._execute_path = orig_exec

    _, fx, fy = _read_position(emu)
    print(f"\nfinal_pos=({fx},{fy}) result_summary:")
    for k in ("path", "steps", "final", "warp_failed", "stopped_early", "blocked_at",
              "blocked_reason", "repaths", "obstacles_cleared", "encounter"):
        if k in result:
            v = result[k]
            if k == "encounter":
                v = "[encounter elided]"
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
