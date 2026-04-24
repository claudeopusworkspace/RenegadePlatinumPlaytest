"""Phase 3: high-speed bike "snake" — 100 random targets, zero idle frames.

Given Phase 1+2 primitives (frame-by-frame hold with read-then-decide on
every tile commit, turns are zero-cost at tick boundaries, gear stays FAST),
Phase 3 puts it through its paces.

Arena: 5x5 walkable square centered on (304, 542) in Eterna City.
  x in [302, 306],  y in [540, 544]

Loop per target:
  1. Pick a random target tile != current.
  2. Walk toward target one axis at a time (x first, then y).
  3. Every frame: advance_frames(1, buttons=[active_dir]) + read (x, y).
  4. On tile commit, check: did we land ON the target? If yes, pick new
     target + new direction. If no, keep holding (direction may flip when
     first axis is aligned).

Invariants asserted every frame:
  * No empty-button frame (structural — buttons=[dir] always non-empty).
  * Player inside arena.
  * Gear byte stays == 1 (FAST) throughout.
  * Per-tile dx,dy matches held direction exactly (no double-step, no
    perpendicular drift — a.k.a. no overshoot).

Output: JSONL trace + summary. Failure mode aborts and dumps last 30 ticks.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "spike_eterna_open_bike_fast"
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "spike_bike_snake_phase3.jsonl"

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

    abs_frame = 0
    targets_eaten = 0
    last_tick_frame = 0
    gear_min = gear
    overshoots: list[str] = []
    arena_violations: list[str] = []
    deltas: list[int] = []
    tick_log: list[tuple] = []  # (abs_frame, dir, x, y, delta, target_idx)

    targets_list: list[tuple[int, int]] = [target]

    while targets_eaten < num_targets:
        emu.advance_frames(1, buttons=[direction])
        abs_frame += 1
        nx, ny = read_pos(emu)
        gear = read_gear(emu)
        if gear < gear_min:
            gear_min = gear

        log_fh.write(json.dumps({
            "abs_frame": abs_frame, "dir": direction,
            "x": nx, "y": ny, "gear": gear,
            "target": list(target), "eaten": targets_eaten,
        }) + "\n")

        if (nx, ny) == (x, y):
            continue  # no tick this frame

        # Tile committed — validate.
        dx, dy = nx - x, ny - y
        want_dx, want_dy = dir_delta(direction)
        if (dx, dy) != (want_dx, want_dy):
            overshoots.append(
                f"frame {abs_frame} eaten={targets_eaten} dir={direction} "
                f"expected d=({want_dx},{want_dy}) got d=({dx},{dy}) "
                f"pos ({x},{y})->({nx},{ny}) target={target}"
            )
            # Don't abort — capture and continue for post-mortem.

        delta = abs_frame - last_tick_frame
        last_tick_frame = abs_frame
        deltas.append(delta)
        tick_log.append((abs_frame, direction, nx, ny, delta, len(targets_list) - 1))

        x, y = nx, ny

        if not in_arena((x, y)):
            arena_violations.append(
                f"frame {abs_frame} eaten={targets_eaten} dir={direction} "
                f"LEFT ARENA at ({x},{y}) target={target}"
            )
            break

        if (x, y) == target:
            targets_eaten += 1
            if verbose and targets_eaten % 10 == 0:
                print(f"  [{targets_eaten:>3}/{num_targets}] frame={abs_frame} "
                      f"pos=({x},{y})")
            if targets_eaten >= num_targets:
                break
            target = pick_target(rng, (x, y))
            targets_list.append(target)
            direction = direction_to((x, y), target)
            assert direction is not None
        else:
            # Not yet on target; recompute direction (flips when first axis
            # aligns). Continue without any idle frame.
            new_dir = direction_to((x, y), target)
            if new_dir is None:
                # Impossible — we're not on target but direction_to is None?
                overshoots.append(
                    f"frame {abs_frame}: direction_to None at ({x},{y}) target={target}"
                )
                break
            direction = new_dir

    final = read_pos(emu)
    return {
        "targets_eaten": targets_eaten,
        "abs_frame": abs_frame,
        "overshoots": overshoots,
        "arena_violations": arena_violations,
        "gear_min": gear_min,
        "deltas": deltas,
        "tick_log_tail": tick_log[-30:],
        "end_pos": final,
        "targets": targets_list,
        "seed": seed,
    }


def summarize(result: dict, num_targets: int) -> bool:
    print(f"\n--- Snake result (seed={result['seed']}) ---")
    print(f"  targets_eaten:    {result['targets_eaten']} / {num_targets}")
    print(f"  total_frames:     {result['abs_frame']}  "
          f"(avg {result['abs_frame'] / max(1, result['targets_eaten']):.1f} f/target)")
    print(f"  tick_count:       {len(result['deltas'])}")
    print(f"  end_pos:          {result['end_pos']}")
    print(f"  gear_min:         {result['gear_min']}")
    steady = result["deltas"][5:] if len(result["deltas"]) > 5 else []
    if steady:
        from collections import Counter
        c = Counter(steady)
        print(f"  steady-state delta histogram (post-accel): "
              f"{dict(sorted(c.items()))}  count={len(steady)}")
    if result["arena_violations"]:
        print(f"  ** ARENA VIOLATIONS ({len(result['arena_violations'])}):")
        for v in result["arena_violations"]:
            print(f"    - {v}")
    if result["overshoots"]:
        print(f"  ** OVERSHOOTS / UNEXPECTED TICKS ({len(result['overshoots'])}):")
        for o in result["overshoots"][:10]:
            print(f"    - {o}")
        if len(result["overshoots"]) > 10:
            print(f"    ... ({len(result['overshoots']) - 10} more)")
    if result["arena_violations"] or result["overshoots"]:
        print("\n  Tail of tick log (last 30):")
        for t in result["tick_log_tail"]:
            af, d, x, y, delta, tgt_i = t
            print(f"    f={af:>4d} dir={d:>5s} pos=({x},{y}) d={delta:>2d} tgt_i={tgt_i}")
    ok = (result["targets_eaten"] == num_targets
          and not result["overshoots"]
          and not result["arena_violations"]
          and result["gear_min"] == 1)
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    emu = get_client()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Three seeds — one canonical (42), two variants. If any fail we have
    # multiple traces to compare.
    seeds = [42, 1234, 7777]
    all_ok = True
    with LOG_PATH.open("w") as log_fh:
        for seed in seeds:
            print(f"\n=== Snake run (seed={seed}, 100 targets) ===")
            log_fh.write(json.dumps({"_run_seed": seed}) + "\n")
            res = run_snake(emu, num_targets=100, seed=seed, log_fh=log_fh)
            ok = summarize(res, num_targets=100)
            all_ok = all_ok and ok

    print(f"\nJSONL trace -> {LOG_PATH}")
    print(f"\nOverall: {'ALL PASS' if all_ok else 'SOME FAIL'}")


if __name__ == "__main__":
    main()
