"""Phase 4: snake harness driven by the production ``step_hold`` primitive.

Phase 3 proved that a frame-by-frame advance_frames(1, buttons=[dir]) loop
gives us turn-on-a-dime correctness. Phase 4 asks the narrower question:
does the EXISTING navigation primitive (nav_constants.step_hold, which is
what navigation.py dispatches into for non-ramp bike tiles) also sustain
those invariants when we swap it in for the inner tick loop?

If yes: the existing per-tile driver is already momentum-safe across turns
(despite navigation.py's current assumption to the contrary in
``_bike_ramp_segment``). BUG-048 Gap 2's fix is contained to the BFS model
+ ramp-segment turn-termination rule. The executor doesn't need a rewrite.

If no: we also need a new continuous-hold executor for multi-direction
runs into ramps, and we'd build it on the frame-by-frame primitive from
Phase 3.

Rules same as Phase 3:
  * 5x5 arena, 3 seeds x 100 targets (42 / 1234 / 7777 — matches Phase 3 so
    the random path is identical).
  * Assert on every tile: dx/dy matches held direction, in arena, gear == 1.
  * Record per-step frames_elapsed to characterize cadence under step_hold.

Differences from Phase 3:
  * Inner loop calls ``step_hold(emu, direction, BIKE_HOLD_FRAMES)`` instead
    of frame-by-frame advance_frames(1). No sub-tile visibility; we only
    observe the committed tile.
  * Can't detect "no idle frame" directly; infer from gear-persistence and
    cadence (if momentum drops, deltas will show it).
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
from renegade_mcp.nav_constants import BIKE_HOLD_FRAMES, step_hold  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "spike_bike_snake_phase4.jsonl"

ARENA_X = (302, 306)
ARENA_Y = (540, 544)


def read_pos(emu: EmulatorClient) -> tuple[int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def read_gear(emu: EmulatorClient) -> int:
    return emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")


def direction_to(cur: tuple[int, int], tgt: tuple[int, int]) -> str | None:
    cx, cy = cur
    tx, ty = tgt
    if cx != tx:
        return "right" if tx > cx else "left"
    if cy != ty:
        return "down" if ty > cy else "up"
    return None


def dir_delta(direction: str) -> tuple[int, int]:
    return {
        "right": (1, 0), "left": (-1, 0),
        "down": (0, 1), "up": (0, -1),
    }[direction]


def in_arena(pos: tuple[int, int]) -> bool:
    x, y = pos
    return ARENA_X[0] <= x <= ARENA_X[1] and ARENA_Y[0] <= y <= ARENA_Y[1]


def pick_target(rng: random.Random, cur: tuple[int, int]) -> tuple[int, int]:
    while True:
        tx = rng.randint(ARENA_X[0], ARENA_X[1])
        ty = rng.randint(ARENA_Y[0], ARENA_Y[1])
        if (tx, ty) != cur:
            return (tx, ty)


def run_snake(emu: EmulatorClient, num_targets: int, seed: int,
              log_fh, verbose: bool = True) -> dict:
    rng = random.Random(seed)

    do_load_state(emu, SAVE)
    emu.advance_frames(4)

    x, y = read_pos(emu)
    assert (x, y) == (304, 542), f"unexpected start ({x},{y})"
    gear = read_gear(emu)
    assert gear == 1, f"gear not FAST at start (byte={gear})"

    target = pick_target(rng, (x, y))
    direction = direction_to((x, y), target)
    assert direction is not None

    targets_eaten = 0
    gear_min = gear
    overshoots: list[str] = []
    arena_violations: list[str] = []
    untriggered: list[str] = []
    step_frames: list[int] = []
    targets_list: list[tuple[int, int]] = [target]
    step_count = 0
    total_frames = 0

    while targets_eaten < num_targets:
        result = step_hold(emu, direction, BIKE_HOLD_FRAMES)
        elapsed = result.get("frames_elapsed", 0)
        triggered = result.get("triggered", False)
        total_frames += elapsed
        step_count += 1
        step_frames.append(elapsed)

        nx, ny = read_pos(emu)
        gear = read_gear(emu)
        if gear < gear_min:
            gear_min = gear

        log_fh.write(json.dumps({
            "step": step_count, "dir": direction,
            "x": nx, "y": ny, "gear": gear,
            "target": list(target), "eaten": targets_eaten,
            "frames_elapsed": elapsed, "triggered": triggered,
        }) + "\n")

        if not triggered:
            untriggered.append(
                f"step {step_count} eaten={targets_eaten} dir={direction} "
                f"pos ({x},{y}) elapsed={elapsed} — step_hold timed out"
            )
            break

        # Validate tile commit.
        dx, dy = nx - x, ny - y
        want_dx, want_dy = dir_delta(direction)
        if (dx, dy) != (want_dx, want_dy):
            overshoots.append(
                f"step {step_count} eaten={targets_eaten} dir={direction} "
                f"expected d=({want_dx},{want_dy}) got d=({dx},{dy}) "
                f"pos ({x},{y})->({nx},{ny}) target={target} elapsed={elapsed}"
            )

        x, y = nx, ny

        if not in_arena((x, y)):
            arena_violations.append(
                f"step {step_count} eaten={targets_eaten} dir={direction} "
                f"LEFT ARENA at ({x},{y}) target={target}"
            )
            break

        if (x, y) == target:
            targets_eaten += 1
            if verbose and targets_eaten % 10 == 0:
                print(f"  [{targets_eaten:>3}/{num_targets}] step={step_count} "
                      f"total_f={total_frames} pos=({x},{y})")
            if targets_eaten >= num_targets:
                break
            target = pick_target(rng, (x, y))
            targets_list.append(target)
            direction = direction_to((x, y), target)
            assert direction is not None
        else:
            new_dir = direction_to((x, y), target)
            if new_dir is None:
                overshoots.append(
                    f"step {step_count}: direction_to None at ({x},{y}) target={target}"
                )
                break
            direction = new_dir

    return {
        "targets_eaten": targets_eaten,
        "step_count": step_count,
        "total_frames": total_frames,
        "overshoots": overshoots,
        "arena_violations": arena_violations,
        "untriggered": untriggered,
        "gear_min": gear_min,
        "step_frames": step_frames,
        "end_pos": read_pos(emu),
        "targets": targets_list,
        "seed": seed,
    }


def summarize(result: dict, num_targets: int) -> bool:
    print(f"\n--- Phase 4 snake (seed={result['seed']}) ---")
    print(f"  targets_eaten: {result['targets_eaten']} / {num_targets}")
    print(f"  steps:         {result['step_count']}  "
          f"total_frames: {result['total_frames']}  "
          f"avg: {result['total_frames'] / max(1, result['step_count']):.2f} f/tile")
    print(f"  end_pos:       {result['end_pos']}")
    print(f"  gear_min:      {result['gear_min']}")
    steady = result["step_frames"][5:] if len(result["step_frames"]) > 5 else []
    if steady:
        c = Counter(steady)
        print(f"  frames_elapsed histogram (post-accel): {dict(sorted(c.items()))}  "
              f"count={len(steady)}")
    for label, items in (
        ("UNTRIGGERED", result["untriggered"]),
        ("ARENA VIOLATIONS", result["arena_violations"]),
        ("OVERSHOOTS / BAD TICKS", result["overshoots"]),
    ):
        if items:
            print(f"  ** {label} ({len(items)}):")
            for m in items[:10]:
                print(f"    - {m}")
            if len(items) > 10:
                print(f"    ... ({len(items) - 10} more)")
    ok = (result["targets_eaten"] == num_targets
          and not result["overshoots"]
          and not result["arena_violations"]
          and not result["untriggered"]
          and result["gear_min"] == 1)
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    emu = get_client()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    seeds = [42, 1234, 7777]
    all_ok = True
    with LOG_PATH.open("w") as log_fh:
        for seed in seeds:
            print(f"\n=== Phase 4 snake (seed={seed}, step_hold driver) ===")
            log_fh.write(json.dumps({"_run_seed": seed}) + "\n")
            res = run_snake(emu, num_targets=100, seed=seed, log_fh=log_fh)
            ok = summarize(res, num_targets=100)
            all_ok = all_ok and ok

    print(f"\nJSONL trace -> {LOG_PATH}")
    print(f"\nOverall: {'ALL PASS' if all_ok else 'SOME FAIL'}")


if __name__ == "__main__":
    main()
