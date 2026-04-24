"""Phase 6: snake harness using ``final_buttons`` to hand off cleanly.

MelonMCP issue #12 added ``final_buttons`` to ``advance_frames_until``,
letting callers control the trailing render frame's inputs. For the snake
harness, we predict the next direction (based on where the player will
be after the current tile commit) and pass it as ``final_buttons`` — the
trailing frame becomes the first frame of the new press, eliminating
the gap that caused phase 5's overshoots.

Tests:
  (1) Same 2xR 2xL 2xU sequence as phase 5 test 1, with predicted
      final_buttons. Expect no overshoot at step 5.
  (2) Mini snake harness: 1 seed x 20 targets with step budget cap.
  (3) Full snake: 3 seeds x 100 targets. Direct comparison vs Phase 3
      frame-by-frame results.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.nav_constants import BIKE_HOLD_FRAMES  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"
ARENA_X = (302, 306)
ARENA_Y = (540, 544)
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "spike_bike_snake_phase6.jsonl"


def read_pos(emu):
    base = addresses.addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def read_gear(emu):
    return emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")


def step_hold_with_handoff(emu, direction, next_direction, max_frames=16):
    """Hold ``direction`` until ANY axis ticks, with trailing frame already
    pressing ``next_direction`` so chained calls have no gap."""
    base = addresses.addr("PLAYER_POS_BASE")
    return emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[
            {"type": "changed", "address": base + 8, "size": "long"},
            {"type": "changed", "address": base + 12, "size": "long"},
        ],
        poll_interval=1,
        buttons=[direction],
        final_buttons=[next_direction],
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


def predict_next_dir(cur, direction, target):
    """If we tick once in ``direction``, where will we be, and what direction
    does the snake then need? Used to pre-fill final_buttons."""
    dx, dy = dir_delta(direction)
    next_pos = (cur[0] + dx, cur[1] + dy)
    return direction_to(next_pos, target) or direction


def in_arena(p):
    x, y = p
    return ARENA_X[0] <= x <= ARENA_X[1] and ARENA_Y[0] <= y <= ARENA_Y[1]


def pick_target(rng, cur):
    while True:
        t = (rng.randint(*ARENA_X), rng.randint(*ARENA_Y))
        if t != cur:
            return t


def test_1_turn_sequence(emu):
    """Hard-coded 2R 2L 2U with prediction-based final_buttons.

    Predicted next-direction is the SAME as current within a same-direction
    segment, and the NEXT segment's direction at the segment-end tile.
    """
    print("\n=== TEST 1: 2xR, 2xL, 2xU with final_buttons handoff ===")
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    print(f"  start=({x},{y}) gear={read_gear(emu)}")
    plan = [
        ("right", "right"),  # step 1: continue right
        ("right", "left"),   # step 2: hand off to left
        ("left",  "left"),   # step 3: continue left
        ("left",  "up"),     # step 4: hand off to up
        ("up",    "up"),     # step 5: continue up
        ("up",    "up"),     # step 6: continue up (final segment)
    ]
    overshoot_count = 0
    for i, (d, nd) in enumerate(plan, 1):
        res = step_hold_with_handoff(emu, d, nd)
        nx, ny = read_pos(emu)
        dx, dy = nx - x, ny - y
        want = dir_delta(d)
        flag = " OK" if (dx, dy) == want else " OVERSHOOT"
        if (dx, dy) != want:
            overshoot_count += 1
        print(f"  step {i} dir={d:<5s} next={nd:<5s} f={res.get('frames_elapsed', '?'):>2} "
              f"({x},{y})->({nx},{ny}) d=({dx:+},{dy:+}) want={want}{flag}")
        x, y = nx, ny
    print(f"  total overshoots: {overshoot_count}")
    return overshoot_count == 0


def run_snake(emu, num_targets, seed, log_fh, step_budget_factor=8, verbose=True):
    rng = random.Random(seed)
    do_load_state(emu, SAVE)
    emu.advance_frames(4)
    x, y = read_pos(emu)
    assert (x, y) == (304, 542), f"unexpected start ({x},{y})"
    gear = read_gear(emu)
    assert gear == 1

    target = pick_target(rng, (x, y))
    # Pre-pick the FOLLOWING target so we can pre-fill final_buttons on the
    # call that arrives at `target` — otherwise the trailing render frame
    # would hold the old direction and the next call would see the same
    # overshoot the bridge fix was meant to eliminate.
    after_target = pick_target(rng, target)
    direction = direction_to((x, y), target)
    targets_eaten = 0
    step_count = 0
    overshoots: list[str] = []
    arena_violations: list[str] = []
    step_frames: list[int] = []
    gear_min = gear
    total_frames = 0
    step_budget = num_targets * step_budget_factor

    while targets_eaten < num_targets and step_count < step_budget:
        # Predict next direction. If the current tick lands us on the target,
        # the trailing frame should already point at the FOLLOWING target so
        # the next call (which will press toward `after_target`) has no gap.
        dx, dy = dir_delta(direction)
        next_pos = (x + dx, y + dy)
        if next_pos == target:
            next_dir = direction_to(target, after_target) or direction
        else:
            next_dir = direction_to(next_pos, target) or direction
        res = step_hold_with_handoff(emu, direction, next_dir)
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
            "step": step_count, "dir": direction, "next_dir": next_dir,
            "x": nx, "y": ny, "gear": gear,
            "target": list(target), "eaten": targets_eaten,
            "f_elapsed": elapsed, "triggered": triggered,
        }) + "\n")
        if not triggered:
            overshoots.append(
                f"step {step_count} UNTRIGGERED dir={direction} pos ({x},{y})"
            )
            break
        dx, dy = nx - x, ny - y
        want = dir_delta(direction)
        if (dx, dy) != want:
            overshoots.append(
                f"step {step_count} eaten={targets_eaten} dir={direction} "
                f"want={want} got=({dx:+},{dy:+}) ({x},{y})->({nx},{ny}) "
                f"target={target} f={elapsed}"
            )
        x, y = nx, ny
        if not in_arena((x, y)):
            arena_violations.append(f"step {step_count} LEFT ARENA at ({x},{y})")
            break
        if (x, y) == target:
            targets_eaten += 1
            if verbose and targets_eaten % 10 == 0:
                print(f"  [{targets_eaten:>3}/{num_targets}] step={step_count} "
                      f"total_f={total_frames}")
            if targets_eaten >= num_targets:
                break
            # Promote the pre-picked target; pre-pick the next one.
            target = after_target
            after_target = pick_target(rng, target)
            direction = direction_to((x, y), target)
        else:
            direction = direction_to((x, y), target) or direction

    return {
        "seed": seed,
        "targets_eaten": targets_eaten,
        "step_count": step_count,
        "step_budget": step_budget,
        "total_frames": total_frames,
        "overshoots": overshoots,
        "arena_violations": arena_violations,
        "gear_min": gear_min,
        "step_frames": step_frames,
        "end_pos": read_pos(emu),
    }


def summarize(res, num_targets):
    print(f"\n--- Phase 6 snake (seed={res['seed']}) ---")
    print(f"  eaten: {res['targets_eaten']}/{num_targets}  "
          f"steps: {res['step_count']}/{res['step_budget']}  "
          f"total_f: {res['total_frames']}  "
          f"avg: {res['total_frames'] / max(1, res['step_count']):.2f} f/tile")
    print(f"  end_pos: {res['end_pos']}  gear_min: {res['gear_min']}")
    steady = res["step_frames"][5:] if len(res["step_frames"]) > 5 else []
    if steady:
        c = Counter(steady)
        print(f"  steady-state f_elapsed histogram: {dict(sorted(c.items()))}  "
              f"count={len(steady)}")
    for label, items in (
        ("OVERSHOOTS", res["overshoots"]),
        ("ARENA VIOLATIONS", res["arena_violations"]),
    ):
        if items:
            print(f"  ** {label} ({len(items)}):")
            for m in items[:8]:
                print(f"    - {m}")
    ok = (res["targets_eaten"] == num_targets and not res["overshoots"]
          and not res["arena_violations"] and res["gear_min"] == 1)
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    emu = get_client()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    t1 = test_1_turn_sequence(emu)
    if not t1:
        print("\nTest 1 failed — skipping snake.")
        return

    print("\n=== TEST 2: mini snake (seed=42, 20 targets) ===")
    with LOG_PATH.open("w") as log_fh:
        log_fh.write(json.dumps({"_run": "mini"}) + "\n")
        res = run_snake(emu, num_targets=20, seed=42, log_fh=log_fh)
        if not summarize(res, num_targets=20):
            print("\nMini snake failed — skipping full run.")
            return

    print("\n=== TEST 3: full snake (3 seeds x 100 targets) ===")
    with LOG_PATH.open("a") as log_fh:
        all_ok = True
        for seed in (42, 1234, 7777):
            log_fh.write(json.dumps({"_run_seed": seed}) + "\n")
            res = run_snake(emu, num_targets=100, seed=seed, log_fh=log_fh)
            ok = summarize(res, num_targets=100)
            all_ok = all_ok and ok
        print(f"\nOverall: {'ALL PASS' if all_ok else 'SOME FAIL'}")


if __name__ == "__main__":
    main()
