"""Phase 5: step_hold that watches BOTH axes simultaneously.

Phase 4 showed step_hold's advance_frames_until watches only the axis of
the held direction, missing perpendicular overshoots. The fix is to pass
two conditions (x changed OR y changed) so the bridge returns on the
FIRST tile commit regardless of axis — giving us the same granularity as
our Phase 3 frame-by-frame loop without forcing melonDS to render every
frame.

Two tests:
  (1) Sequence B from phase 4 debug (2 right, 2 left, 2 up). Expect no
      extra perpendicular tiles on the left->up transition.
  (2) Smaller shakedown snake harness: 1 seed x 20 targets, with a step
      budget cap so infinite loops bail in seconds, not minutes.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.nav_constants import BIKE_HOLD_FRAMES  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"
ARENA_X = (302, 306)
ARENA_Y = (540, 544)
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "spike_bike_snake_phase5.jsonl"


def read_pos(emu):
    base = addresses.addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def read_gear(emu):
    return emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")


def step_hold_both_axes(emu, direction, max_frames=16):
    """Return on ANY pos change (x or y), not just the direction's axis.

    Two 'changed' conditions — advance_frames_until fires on first match.
    """
    base = addresses.addr("PLAYER_POS_BASE")
    return emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[
            {"type": "changed", "address": base + 8, "size": "long"},
            {"type": "changed", "address": base + 12, "size": "long"},
        ],
        poll_interval=1,
        buttons=[direction],
    )


def direction_to(cur, tgt):
    cx, cy = cur
    tx, ty = tgt
    if cx != tx:
        return "right" if tx > cx else "left"
    if cy != ty:
        return "down" if ty > cy else "up"
    return None


def dir_delta(d):
    return {"right": (1, 0), "left": (-1, 0),
            "down": (0, 1), "up": (0, -1)}[d]


def in_arena(p):
    x, y = p
    return ARENA_X[0] <= x <= ARENA_X[1] and ARENA_Y[0] <= y <= ARENA_Y[1]


def pick_target(rng, cur):
    while True:
        t = (rng.randint(*ARENA_X), rng.randint(*ARENA_Y))
        if t != cur:
            return t


def test_1_turn_sequence(emu):
    print("\n=== TEST 1: 2xR, 2xL, 2xU with both-axes step_hold ===")
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    print(f"  start=({x},{y}) gear={read_gear(emu)}")
    overshoot_count = 0
    for i, d in enumerate(["right", "right", "left", "left", "up", "up"], 1):
        res = step_hold_both_axes(emu, d)
        nx, ny = read_pos(emu)
        dx, dy = nx - x, ny - y
        want = dir_delta(d)
        flag = " OK" if (dx, dy) == want else " OVERSHOOT"
        if (dx, dy) != want:
            overshoot_count += 1
        print(f"  step {i} dir={d:<5s} f={res.get('frames_elapsed', '?'):>2} "
              f"({x},{y})->({nx},{ny})  d=({dx:+},{dy:+}) want={want}{flag}")
        x, y = nx, ny
    print(f"  total overshoots: {overshoot_count}")
    return overshoot_count == 0


def test_2_mini_snake(emu, seed=42, num_targets=20, step_budget=400):
    print(f"\n=== TEST 2: mini snake (seed={seed}, {num_targets} targets, "
          f"budget {step_budget} steps) ===")
    rng = random.Random(seed)
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    assert (x, y) == (304, 542)

    target = pick_target(rng, (x, y))
    direction = direction_to((x, y), target)
    targets_eaten = 0
    step_count = 0
    overshoots: list[str] = []
    arena_violations: list[str] = []
    step_frames: list[int] = []
    gear_min = read_gear(emu)
    total_frames = 0

    with LOG_PATH.open("w") as log_fh:
        while targets_eaten < num_targets and step_count < step_budget:
            res = step_hold_both_axes(emu, direction)
            elapsed = res.get("frames_elapsed", 0)
            triggered = res.get("triggered", False)
            nx, ny = read_pos(emu)
            gear = read_gear(emu)
            if gear < gear_min:
                gear_min = gear
            total_frames += elapsed
            step_count += 1
            step_frames.append(elapsed)
            log_fh.write(json.dumps({
                "step": step_count, "dir": direction,
                "x": nx, "y": ny, "gear": gear,
                "target": list(target), "eaten": targets_eaten,
                "f_elapsed": elapsed, "triggered": triggered,
            }) + "\n")

            if not triggered:
                overshoots.append(
                    f"step {step_count} UNTRIGGERED dir={direction} "
                    f"pos ({x},{y}) f={elapsed}"
                )
                break

            dx, dy = nx - x, ny - y
            want = dir_delta(direction)
            if (dx, dy) != want:
                overshoots.append(
                    f"step {step_count} eaten={targets_eaten} dir={direction} "
                    f"want={want} got=({dx:+},{dy:+}) "
                    f"({x},{y})->({nx},{ny}) target={target} f={elapsed}"
                )

            x, y = nx, ny
            if not in_arena((x, y)):
                arena_violations.append(
                    f"step {step_count} LEFT ARENA at ({x},{y}) target={target}"
                )
                break

            if (x, y) == target:
                targets_eaten += 1
                if targets_eaten % 5 == 0:
                    print(f"  [{targets_eaten:>2}/{num_targets}] step={step_count} "
                          f"total_f={total_frames} pos=({x},{y})")
                if targets_eaten >= num_targets:
                    break
                target = pick_target(rng, (x, y))
                direction = direction_to((x, y), target)
            else:
                direction = direction_to((x, y), target) or direction

    print(f"  eaten: {targets_eaten}/{num_targets}  steps: {step_count}  "
          f"total_f: {total_frames}  gear_min: {gear_min}")
    if step_frames[5:]:
        c = Counter(step_frames[5:])
        print(f"  steady-state f_elapsed histogram: {dict(sorted(c.items()))}")
    if overshoots:
        print(f"  OVERSHOOTS ({len(overshoots)}):")
        for o in overshoots[:10]:
            print(f"    - {o}")
    if arena_violations:
        print(f"  ARENA VIOLATIONS ({len(arena_violations)}):")
        for a in arena_violations:
            print(f"    - {a}")
    ok = (targets_eaten == num_targets and not overshoots
          and not arena_violations and gear_min == 1)
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_3_frame_by_frame_same_sequence(emu):
    """Same 2R 2L 2U sequence driven by frame-by-frame advance_frames(1).

    If this ALSO shows overshoot at step 5, the overshoot is a real
    engine behavior (old-direction tile queued post-180). If it does
    NOT, the overshoot is specifically a side-effect of how
    advance_frames_until starts a new hold.
    """
    print("\n=== TEST 3: same sequence, frame-by-frame ===")
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    print(f"  start=({x},{y})")
    sequence = [("right", 2), ("left", 2), ("up", 2)]
    overshoot_count = 0
    step = 0
    for direction, wanted_ticks in sequence:
        ticks_in_seg = 0
        frames_used = 0
        while ticks_in_seg < wanted_ticks and frames_used < 40:
            emu.advance_frames(1, buttons=[direction])
            frames_used += 1
            nx, ny = read_pos(emu)
            if (nx, ny) != (x, y):
                step += 1
                dx, dy = nx - x, ny - y
                want = dir_delta(direction)
                flag = " OK" if (dx, dy) == want else " OVERSHOOT"
                if (dx, dy) != want:
                    overshoot_count += 1
                print(f"  step {step} dir={direction:<5s} f={frames_used:>2} "
                      f"({x},{y})->({nx},{ny}) d=({dx:+},{dy:+}) want={want}{flag}")
                x, y = nx, ny
                ticks_in_seg += 1
                frames_used = 0  # per-tick timing
    print(f"  total overshoots: {overshoot_count}")
    return overshoot_count == 0


def test_4_extra_final_frame_repro(emu):
    """Reproduce advance_frames_until's overshoot with pure advance_frames.

    Hypothesis: advance_frames_until's "extra final frame with same buttons"
    (emulator.py:518-520) primes the engine to commit one more tile in the
    old direction after the new direction press begins.

    Test: drive 2xR 2xL with frame-by-frame as in test 3, BUT after the
    final left tile commits, press LEFT for 1 more frame (mimicking the
    extra render frame), THEN start pressing UP. If overshoot reproduces,
    the bug is confirmed at the bridge level.
    """
    print("\n=== TEST 4: simulate advance_frames_until's extra-frame quirk ===")
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    print(f"  start=({x},{y})")

    # Drive 2xR 2xL frame-by-frame.
    for direction in ["right"] * 2 + ["left"] * 2:
        ticks_needed = 1
        frames_used = 0
        while ticks_needed > 0 and frames_used < 30:
            emu.advance_frames(1, buttons=[direction])
            frames_used += 1
            nx, ny = read_pos(emu)
            if (nx, ny) != (x, y):
                x, y = nx, ny
                ticks_needed -= 1
    print(f"  post-2R-2L pos=({x},{y})  (expected (304,542))")

    # Now add ONE EXTRA frame of pressing "left" — mimic what
    # advance_frames_until does at line 519 after the condition fires.
    emu.advance_frames(1, buttons=["left"])
    print(f"  after extra-left-frame pos={read_pos(emu)}")

    # Now press UP frame-by-frame and watch the first tile commit.
    overshoot = False
    for i in range(1, 10):
        emu.advance_frames(1, buttons=["up"])
        nx, ny = read_pos(emu)
        if (nx, ny) != (x, y):
            dx, dy = nx - x, ny - y
            print(f"  up-press frame {i}: ({x},{y})->({nx},{ny}) d=({dx:+},{dy:+})")
            if (dx, dy) != (0, -1):
                overshoot = True
            x, y = nx, ny
            break
    print(f"  overshoot reproduced: {overshoot}")
    return overshoot


def main():
    emu = get_client()
    t1 = test_1_turn_sequence(emu)
    t3 = test_3_frame_by_frame_same_sequence(emu)
    t4 = test_4_extra_final_frame_repro(emu)
    print(f"\nSummary:")
    print(f"  test 1 (advance_frames_until, 2 axes) overshoot: {not t1}")
    print(f"  test 3 (pure advance_frames(1))     overshoot: {not t3}")
    print(f"  test 4 (frame-by-frame + 1 extra)   overshoot: {t4}")
    if t1:
        test_2_mini_snake(emu)


if __name__ == "__main__":
    main()
