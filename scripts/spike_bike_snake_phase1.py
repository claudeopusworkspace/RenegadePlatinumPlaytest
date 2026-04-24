"""Phase 1: Characterize fast-bike input timing for BUG-048 Gap 2.

Save: ``spike_eterna_open_bike_fast`` — Eterna City (304, 542), on bike in
fast gear. 5x5 walkable arena x in [302, 306], y in [540, 544].

Goal: pin down the exact input-sampling semantics of fast-gear cycling so we
can build a "turn on a dime" primitive. Questions answered here:

  (A) Steady-state frame-per-tile cadence at fast gear. Confirms / supersedes
      the ``12 -> 12 -> 8 -> 6 -> 4`` curve noted in reference_bike_coast.

  (B) What does a 180 actually cost? Hold right to a tile boundary, then hold
      left — measure frames until x ticks back. If momentum is preserved, the
      first leftward tile should cost ~steady_state_frames.

  (C) Input-sampling granularity. With x having just ticked up at frame F,
      switch to a perpendicular direction at F+k for k in 0..N. Classify the
      outcome per k: clean turn (no extra x movement) vs overshoot (x ticks
      once more before y starts moving).

  (D) Release vs direction-change behavior. If "no-button" for 1 frame costs
      the coast/decel, but "any direction held" does not, prove it: at the
      same phase, (i) release 1f then press perp, (ii) swap directly to perp.

Output: JSONL frame traces to ``logs/spike_bike_snake_phase1.jsonl`` plus a
human-readable summary to stdout.

Invariants we rely on:
  * PLAYER_POS_BASE + 8  = x (long)
  * PLAYER_POS_BASE + 12 = y (long)
  * BIKE_GEAR_STATE_ADDR byte: 1=FAST, 0=SLOW (inverted from decomp).
  * CYCLING_GEAR_ADDR short: 1=cycling.
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
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "spike_bike_snake_phase1.jsonl"

# Arena bounds (5x5 centered on start).
ARENA_X = (302, 306)
ARENA_Y = (540, 544)


def read_pos(emu: EmulatorClient) -> tuple[int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    x = emu.read_memory(base + 8, size="long")
    y = emu.read_memory(base + 12, size="long")
    return x, y


def read_gear(emu: EmulatorClient) -> tuple[int, int]:
    """Return (cycling, gear_byte). cycling=1 when on bike, gear 1=FAST / 0=SLOW."""
    cycling = emu.read_memory(addresses.addr("CYCLING_GEAR_ADDR"), size="short")
    gear = emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")
    return cycling, gear


def reset(emu: EmulatorClient) -> None:
    do_load_state(emu, SAVE)
    # A few settle frames post-load so the heap is live.
    emu.advance_frames(4)


def in_arena(x: int, y: int) -> bool:
    return ARENA_X[0] <= x <= ARENA_X[1] and ARENA_Y[0] <= y <= ARENA_Y[1]


def trace_hold(emu: EmulatorClient, direction: str, frames: int,
               log_fh, tag: str) -> list[tuple[int, int, int]]:
    """Hold one direction for N frames, reading (x,y) every frame.

    Returns list of (frame_index, x, y). Also writes one JSONL record per
    frame to ``log_fh``.
    """
    trace: list[tuple[int, int, int]] = []
    for i in range(frames):
        emu.advance_frames(1, buttons=[direction])
        x, y = read_pos(emu)
        trace.append((i + 1, x, y))
        log_fh.write(json.dumps({
            "tag": tag, "frame": i + 1, "btn": direction, "x": x, "y": y,
        }) + "\n")
    return trace


def ticks(trace: list[tuple[int, int, int]], axis: str) -> list[int]:
    """Return list of frame indices where the specified axis changed."""
    idx = 1 if axis == "x" else 2
    prev = trace[0][idx]
    out = []
    for f, x, y in trace[1:]:
        cur = (x, y)[idx - 1]
        if cur != prev:
            out.append(f)
            prev = cur
    # Include first frame's position change vs. pre-trace value — too noisy
    # to detect here, so caller should compare trace[0] to the known start.
    return out


def tick_deltas(tick_frames: list[int]) -> list[int]:
    return [b - a for a, b in zip(tick_frames, tick_frames[1:])]


def experiment_a_steady_state(emu: EmulatorClient, log_fh) -> None:
    """Hold RIGHT for 30 frames. Extract per-tile cadence."""
    print("\n=== EXP A: steady-state cadence, hold RIGHT 30f ===")
    reset(emu)
    sx, sy = read_pos(emu)
    cycling, gear = read_gear(emu)
    print(f"  start=({sx},{sy}) cycling={cycling} gear={gear} (1=FAST)")

    trace = trace_hold(emu, "right", 30, log_fh, tag="A_hold_right")
    tf = ticks(trace, "x")
    # Include frame-of-first-tick relative to start of hold
    if trace[0][1] != sx:
        tf = [1] + tf
    deltas = tick_deltas(tf)
    print(f"  x-tick frames (from hold start): {tf}")
    print(f"  per-tile deltas: {deltas}")
    print(f"  final pos: ({trace[-1][1]},{trace[-1][2]})")


def experiment_b_one_eighty(emu: EmulatorClient, log_fh) -> None:
    """Hold RIGHT until first x-tick, then hold LEFT. Measure first left-tick."""
    print("\n=== EXP B: 180 turn after 1 right-tick ===")
    reset(emu)
    sx, sy = read_pos(emu)

    # Hold right frame-by-frame until x increments.
    right_frames = 0
    while True:
        emu.advance_frames(1, buttons=["right"])
        right_frames += 1
        x, y = read_pos(emu)
        log_fh.write(json.dumps({
            "tag": "B_right_wait", "frame": right_frames, "btn": "right",
            "x": x, "y": y,
        }) + "\n")
        if x != sx or right_frames > 30:
            break
    print(f"  first right-tick at frame {right_frames}, pos=({x},{y})")

    # Now hold left frame-by-frame until x decrements below the tick landing
    pivot_x = x
    left_frames = 0
    while True:
        emu.advance_frames(1, buttons=["left"])
        left_frames += 1
        x, y = read_pos(emu)
        log_fh.write(json.dumps({
            "tag": "B_left_after_right", "frame": left_frames, "btn": "left",
            "x": x, "y": y,
        }) + "\n")
        if x < pivot_x or left_frames > 30:
            break
    print(f"  first left-tick at frame {left_frames} after swap, pos=({x},{y})")
    print("  (compare against EXP A first-tick: if equal, momentum preserved.)")


def experiment_c_turn_phase_scan(emu: EmulatorClient, log_fh) -> None:
    """After a right-tick, swap to UP at F+k frames. Classify outcome.

    For each k, the question is: once we swap buttons at F+k, does x tick
    one more time (overshoot) before y starts ticking (clean turn)?
    """
    print("\n=== EXP C: turn phase scan (right->up after first x-tick + k) ===")
    print(f"  {'k':>3} {'right_tick_f':>14} {'pivot_xy':>10} "
          f"{'overshoot_x':>12} {'first_y_tick_dF':>16} {'final_xy':>10}")

    for k in range(0, 8):
        reset(emu)
        sx, sy = read_pos(emu)

        # Drive until first right-tick.
        right_frames = 0
        while True:
            emu.advance_frames(1, buttons=["right"])
            right_frames += 1
            x, y = read_pos(emu)
            if x != sx or right_frames > 30:
                break
        pivot_x = x
        pivot_frame_global = right_frames

        # Hold right for k more frames (k==0 means switch immediately next frame).
        for _ in range(k):
            emu.advance_frames(1, buttons=["right"])

        # Now swap to up and trace 30 frames.
        overshoot_x: int | None = None
        first_y_tick_df: int | None = None
        last_x, last_y = read_pos(emu)
        for j in range(30):
            emu.advance_frames(1, buttons=["up"])
            x, y = read_pos(emu)
            log_fh.write(json.dumps({
                "tag": "C_turn", "k": k, "frame": j + 1, "btn": "up",
                "x": x, "y": y,
            }) + "\n")
            if x != last_x and overshoot_x is None:
                overshoot_x = x
            if y != sy and first_y_tick_df is None:
                first_y_tick_df = j + 1
                break  # enough — we have our answer
            last_x, last_y = x, y

        fx, fy = read_pos(emu)
        print(f"  {k:>3} {pivot_frame_global:>14} {f'({pivot_x},{sy})':>10} "
              f"{str(overshoot_x):>12} {str(first_y_tick_df):>16} "
              f"{f'({fx},{fy})':>10}")


def experiment_e_long_steady_state(emu: EmulatorClient, log_fh) -> None:
    """Hold RIGHT for as long as the arena allows — confirm/refute 12f/tile.

    Arena allows 2 tiles east from (304, 542) before hitting x=307 (still open
    per view_map; we'll just not push past x=306 to stay inside the 5x5 arena
    if we later want to reuse the save). For acceleration observation we can
    push further east (the save has 7 east tiles clear).
    """
    print("\n=== EXP E: long RIGHT hold (6 tiles) — acceleration check ===")
    reset(emu)
    sx, sy = read_pos(emu)
    # Go 6 tiles east — well past arena. We'll return to base position via
    # reset() at the end of this experiment; this one doesn't need arena
    # containment since we're only characterizing the curve.
    trace = trace_hold(emu, "right", 90, log_fh, tag="E_long_right")
    tick_frames: list[int] = []
    prev_x = sx
    for f, x, y in trace:
        if x != prev_x:
            tick_frames.append(f)
            prev_x = x
    deltas = [b - a for a, b in zip(tick_frames, tick_frames[1:])]
    print(f"  x-tick frames: {tick_frames}")
    print(f"  per-tile deltas: {deltas}")
    print(f"  final pos: ({trace[-1][1]},{trace[-1][2]})")


def experiment_f_gear_during_turns(emu: EmulatorClient, log_fh) -> None:
    """Trace the gear byte (BIKE_GEAR_STATE_ADDR) across a bunch of turns.

    If gear drops from 1 to 0 during a turn, we'd need to hold a direction
    long enough to re-promote before entering a ramp. If it stays at 1 the
    whole time, BUG-048 Gap 2 is just a BFS-model issue.
    """
    print("\n=== EXP F: gear byte across repeated turns ===")
    reset(emu)
    sx, sy = read_pos(emu)
    _, g0 = read_gear(emu)
    print(f"  start gear={g0} pos=({sx},{sy})")

    # Cycle: right, down, left, up (returns to start).
    dirs = ["right", "down", "left", "up"]
    cur_dir_idx = 0
    prev_pos = (sx, sy)
    # Drive the first tick in each direction; between ticks, read gear every frame.
    min_gear_seen = g0
    tick_count = 0
    for frame_i in range(200):
        emu.advance_frames(1, buttons=[dirs[cur_dir_idx]])
        x, y = read_pos(emu)
        _, gear = read_gear(emu)
        if gear < min_gear_seen:
            min_gear_seen = gear
        log_fh.write(json.dumps({
            "tag": "F_gear_turn", "frame": frame_i + 1, "btn": dirs[cur_dir_idx],
            "x": x, "y": y, "gear": gear,
        }) + "\n")
        if (x, y) != prev_pos:
            tick_count += 1
            # Turn every tile.
            cur_dir_idx = (cur_dir_idx + 1) % 4
            prev_pos = (x, y)
            if tick_count >= 8:
                break
    _, g_final = read_gear(emu)
    print(f"  tiles moved: {tick_count}  min_gear_seen={min_gear_seen}  "
          f"final_gear={g_final}  final_pos={read_pos(emu)}")


def experiment_g_accel_across_turn(emu: EmulatorClient, log_fh) -> None:
    """Build full momentum east, then turn south — do post-turn tiles stay at 4f?

    Answers the critical BUG-048 question: does the 4f/tile cadence survive a
    direction change, or does each turn restart the 12->8->7->4 accel ramp?

    Trace 20+ tiles: 6 east (well past accel ramp) then 6 south, watching
    per-tile deltas. If post-turn tiles are 4, momentum is direction-agnostic.
    If they're 12/8/7/4 again, momentum is per-direction.
    """
    print("\n=== EXP G: acceleration preserved across a turn? ===")
    reset(emu)
    sx, sy = read_pos(emu)

    tick_frames: list[tuple[str, int, int, int]] = []  # (dir, frame, x, y)
    # Phase 1: drive right for 6 x-ticks (long enough to reach steady-state 4f).
    prev_x = sx
    frame_i = 0
    x_ticks_seen = 0
    while x_ticks_seen < 6 and frame_i < 120:
        emu.advance_frames(1, buttons=["right"])
        frame_i += 1
        x, y = read_pos(emu)
        log_fh.write(json.dumps({
            "tag": "G_right", "frame": frame_i, "btn": "right",
            "x": x, "y": y,
        }) + "\n")
        if x != prev_x:
            tick_frames.append(("right", frame_i, x, y))
            prev_x = x
            x_ticks_seen += 1

    # Phase 2: switch to down, drive 6 more y-ticks.
    prev_y = y
    y_ticks_seen = 0
    frames_in_down = 0
    while y_ticks_seen < 6 and frames_in_down < 120:
        emu.advance_frames(1, buttons=["down"])
        frame_i += 1
        frames_in_down += 1
        x, y = read_pos(emu)
        log_fh.write(json.dumps({
            "tag": "G_down", "frame": frame_i, "btn": "down",
            "x": x, "y": y,
        }) + "\n")
        if y != prev_y:
            tick_frames.append(("down", frame_i, x, y))
            prev_y = y
            y_ticks_seen += 1

    print(f"  tick sequence (dir, abs_frame, x, y):")
    # Deltas between consecutive ticks
    for i, (d, f, x, y) in enumerate(tick_frames):
        if i == 0:
            print(f"    {d:5s} f={f:3d} ({x},{y})")
        else:
            prev_f = tick_frames[i - 1][1]
            print(f"    {d:5s} f={f:3d} ({x},{y})  delta={f - prev_f}")


def experiment_d_release_vs_swap(emu: EmulatorClient, log_fh) -> None:
    """At same phase, compare (i) 1f-release then UP  vs  (ii) direct swap to UP."""
    print("\n=== EXP D: release-1f vs direct-swap at fresh tile boundary ===")

    for mode in ("direct_swap", "release_1f_then_up"):
        reset(emu)
        sx, sy = read_pos(emu)

        # Drive until first right-tick.
        right_frames = 0
        while True:
            emu.advance_frames(1, buttons=["right"])
            right_frames += 1
            x, y = read_pos(emu)
            if x != sx or right_frames > 30:
                break

        if mode == "release_1f_then_up":
            emu.advance_frames(1)  # NO buttons — this is the control

        # Hold up and log 30 frames.
        trace: list[tuple[int, int, int]] = []
        for j in range(30):
            emu.advance_frames(1, buttons=["up"])
            x, y = read_pos(emu)
            trace.append((j + 1, x, y))
            log_fh.write(json.dumps({
                "tag": f"D_{mode}", "frame": j + 1, "btn": "up",
                "x": x, "y": y,
            }) + "\n")

        # Classify.
        y_tick_f = None
        x_over = None
        for f, x, y in trace:
            if x != trace[0][1] and x_over is None:
                x_over = x
            if y != sy and y_tick_f is None:
                y_tick_f = f
                break
        print(f"  mode={mode:>24}  first_y_tick_frame={y_tick_f}  "
              f"x_overshoot={x_over}  final={read_pos(emu)}")


def main() -> None:
    emu = get_client()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("w") as log_fh:
        experiment_a_steady_state(emu, log_fh)
        experiment_b_one_eighty(emu, log_fh)
        experiment_c_turn_phase_scan(emu, log_fh)
        experiment_d_release_vs_swap(emu, log_fh)
        experiment_e_long_steady_state(emu, log_fh)
        experiment_f_gear_during_turns(emu, log_fh)
        experiment_g_accel_across_turn(emu, log_fh)
    print(f"\nJSONL trace -> {LOG_PATH}")


if __name__ == "__main__":
    main()
