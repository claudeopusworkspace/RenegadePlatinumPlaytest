"""Phase 2: square-path turn spike.

Given Phase 1's theory (momentum is a global scalar that persists through
turns, gear stays FAST, tick boundary switching is free), Phase 2 tests the
theory at **steady-state 4f/tile** cadence by driving closed loops.

Primitives:
  * Frame-by-frame loop: advance 1 frame with the active direction held,
    read (x, y), detect tile commit. On commit, tick++. When tick count
    equals the requested side length, swap to the next direction for the
    next frame. No frame ever has empty buttons.

Invariants we assert on every run:
  * Player never leaves ARENA_X x ARENA_Y.
  * Player returns to start after each full lap.
  * No overshoot: after requested N ticks along axis A, the player never
    ticks along axis A again until the next scheduled A-segment.
  * Gear byte never drops below 1.

Tests:
  A. CW 2x2 (right x2, down x2, left x2, up x2), 3 laps, cold start.
  B. CCW 2x2 (down x2, right x2, up x2, left x2), 3 laps, cold start.
  C. CW 2x2 primed — accelerate east 4 tiles first (exit arena E is OK;
     save description says 7 E clear), then return and run 3 laps.

Failure modes to surface:
  * If steady-state cadence tightens the turn window below what a single
    advance_frames(1, buttons=[...]) call can react to, a tick will fire
    mid-transition and we'll see an overshoot or mis-axis tick.
  * If momentum drops on a turn, per-tile deltas will jump back to 12 after
    a direction change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "spike_bike_snake_phase2.jsonl"

ARENA_X = (302, 306)
ARENA_Y = (540, 544)


def read_pos(emu: EmulatorClient) -> tuple[int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def read_gear(emu: EmulatorClient) -> int:
    return emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")


def reset(emu: EmulatorClient) -> None:
    do_load_state(emu, SAVE)
    emu.advance_frames(4)


def axis_of(direction: str) -> str:
    return "x" if direction in ("left", "right") else "y"


def expected_sign(direction: str) -> int:
    return {"right": +1, "left": -1, "down": +1, "up": -1}[direction]


def drive_path(emu: EmulatorClient, segments: list[tuple[str, int]],
               log_fh, tag: str,
               arena_check: bool = True,
               max_frames_per_tick: int = 30) -> dict:
    """Drive a sequence of (direction, tile_count) segments frame-by-frame.

    Returns a dict with: tick_log, total_frames, overshoots, gear_min,
    start_pos, end_pos.
    """
    start = read_pos(emu)
    x, y = start
    tick_log: list[tuple] = []  # (abs_frame, seg_i, direction, x, y, delta_from_last_tick)
    overshoots: list[str] = []
    gear_min = read_gear(emu)

    abs_frame = 0
    last_tick_frame = 0

    for seg_i, (direction, want_ticks) in enumerate(segments):
        axis = axis_of(direction)
        sign = expected_sign(direction)
        ticks_in_seg = 0
        frames_in_seg = 0
        while ticks_in_seg < want_ticks:
            emu.advance_frames(1, buttons=[direction])
            abs_frame += 1
            frames_in_seg += 1
            nx, ny = read_pos(emu)
            gear = read_gear(emu)
            gear_min = min(gear_min, gear)
            log_fh.write(json.dumps({
                "tag": tag, "abs_frame": abs_frame, "seg": seg_i,
                "dir": direction, "x": nx, "y": ny, "gear": gear,
            }) + "\n")
            if (nx, ny) != (x, y):
                # Something ticked. Check it moved the expected direction.
                dx = nx - x
                dy = ny - y
                moved_sign_x = (dx > 0) - (dx < 0)
                moved_sign_y = (dy > 0) - (dy < 0)
                if axis == "x":
                    if moved_sign_x != sign or moved_sign_y != 0:
                        overshoots.append(
                            f"seg{seg_i} dir={direction} expected x{sign:+} only, "
                            f"got dx={dx} dy={dy} at frame {abs_frame}"
                        )
                else:
                    if moved_sign_y != sign or moved_sign_x != 0:
                        overshoots.append(
                            f"seg{seg_i} dir={direction} expected y{sign:+} only, "
                            f"got dx={dx} dy={dy} at frame {abs_frame}"
                        )
                delta = abs_frame - last_tick_frame
                last_tick_frame = abs_frame
                tick_log.append((abs_frame, seg_i, direction, nx, ny, delta))
                ticks_in_seg += 1
                x, y = nx, ny
                if arena_check and not (
                    ARENA_X[0] <= x <= ARENA_X[1] and ARENA_Y[0] <= y <= ARENA_Y[1]
                ):
                    overshoots.append(
                        f"LEFT ARENA at ({x},{y}) seg{seg_i} frame {abs_frame}"
                    )
            if frames_in_seg > max_frames_per_tick * want_ticks:
                overshoots.append(
                    f"seg{seg_i} dir={direction} TIMEOUT: {frames_in_seg}f "
                    f"for {want_ticks} ticks (got {ticks_in_seg})"
                )
                break

    return {
        "tick_log": tick_log,
        "total_frames": abs_frame,
        "overshoots": overshoots,
        "gear_min": gear_min,
        "start_pos": start,
        "end_pos": read_pos(emu),
    }


def print_result(label: str, result: dict, expected_end: tuple[int, int]) -> None:
    tick_log = result["tick_log"]
    deltas = [t[5] for t in tick_log]
    steady_deltas = deltas[4:] if len(deltas) > 4 else []
    print(f"\n--- {label} ---")
    print(f"  start={result['start_pos']}  end={result['end_pos']}  "
          f"expected_end={expected_end}")
    print(f"  total_frames={result['total_frames']}  ticks={len(tick_log)}  "
          f"gear_min={result['gear_min']}")
    print(f"  per-tick deltas: {deltas}")
    if steady_deltas:
        print(f"  steady-state deltas (post-accel, tile 5+): {steady_deltas}  "
              f"min={min(steady_deltas)} max={max(steady_deltas)}")
    if result["overshoots"]:
        print(f"  ** OVERSHOOTS ({len(result['overshoots'])}): **")
        for o in result["overshoots"]:
            print(f"    - {o}")
    else:
        print("  overshoots: NONE")
    ok = (result["end_pos"] == expected_end and not result["overshoots"]
          and result["gear_min"] == 1)
    print(f"  PASS" if ok else "  FAIL")


def test_cw_square_cold(emu: EmulatorClient, log_fh) -> None:
    print("\n=== TEST A: CW 2x2 square, 3 laps, cold start ===")
    reset(emu)
    segs = [("right", 2), ("down", 2), ("left", 2), ("up", 2)] * 3
    res = drive_path(emu, segs, log_fh, tag="A_cw_cold")
    print_result("CW 2x2 x3 laps (cold)", res, expected_end=(304, 542))


def test_ccw_square_cold(emu: EmulatorClient, log_fh) -> None:
    print("\n=== TEST B: CCW 2x2 square, 3 laps, cold start ===")
    reset(emu)
    segs = [("down", 2), ("right", 2), ("up", 2), ("left", 2)] * 3
    res = drive_path(emu, segs, log_fh, tag="B_ccw_cold")
    print_result("CCW 2x2 x3 laps (cold)", res, expected_end=(304, 542))


def test_cw_square_primed(emu: EmulatorClient, log_fh) -> None:
    """Accelerate east 5 tiles (exits arena), come back, run CW 2x2 x3 laps.

    The prime run leaves arena but that's OK — save description: 7 E clear.
    After priming we return to (304, 542) still at full speed via LEFT hold,
    then start the CW square.
    """
    print("\n=== TEST C: prime east then CW 2x2 x3 laps ===")
    reset(emu)
    # Prime: right 5 (to x=309), left 5 (back to 304). Arena check disabled
    # for prime phase since we intentionally exit.
    prime = [("right", 5), ("left", 5)]
    res_prime = drive_path(emu, prime, log_fh, tag="C_prime", arena_check=False)
    print(f"  [prime] end={res_prime['end_pos']} frames={res_prime['total_frames']}  "
          f"deltas={[t[5] for t in res_prime['tick_log']]}")

    # Continuous hold: after left x5, we are at (304, 542) and we now pivot
    # directly into the CW square. The drive_path helper starts with the
    # requested direction — there is a one-frame "change" between the prime's
    # final left-press and the square's first right-press, but that change
    # is in an advance_frames call (no gap frame).
    segs = [("right", 2), ("down", 2), ("left", 2), ("up", 2)] * 3
    res = drive_path(emu, segs, log_fh, tag="C_cw_primed")
    print_result("CW 2x2 x3 laps (primed)", res, expected_end=(304, 542))


def test_ccw_square_primed(emu: EmulatorClient, log_fh) -> None:
    print("\n=== TEST D: prime south then CCW 2x2 x3 laps ===")
    reset(emu)
    prime = [("down", 5), ("up", 5)]
    res_prime = drive_path(emu, prime, log_fh, tag="D_prime", arena_check=False)
    print(f"  [prime] end={res_prime['end_pos']} frames={res_prime['total_frames']}  "
          f"deltas={[t[5] for t in res_prime['tick_log']]}")

    segs = [("down", 2), ("right", 2), ("up", 2), ("left", 2)] * 3
    res = drive_path(emu, segs, log_fh, tag="D_ccw_primed")
    print_result("CCW 2x2 x3 laps (primed)", res, expected_end=(304, 542))


def main() -> None:
    emu = get_client()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("w") as log_fh:
        test_cw_square_cold(emu, log_fh)
        test_ccw_square_cold(emu, log_fh)
        test_cw_square_primed(emu, log_fh)
        test_ccw_square_primed(emu, log_fh)
    print(f"\nJSONL trace -> {LOG_PATH}")


if __name__ == "__main__":
    main()
