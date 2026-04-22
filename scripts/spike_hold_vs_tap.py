"""Empirical spike: does sustained-hold actually work across advance_frames calls?

Uses spike_eterna_open_ground (player at (304, 542) in Eterna City outdoors).
Open tiles: 7+ N, 7+ S, 7 E, 3 W. No encounters, no NPCs in the tested paths.

1. **Position-update timing** — hold dir for N=1..20 frames, release, settle.
   Answers: does the engine "commit" mid-animation, or only at animation end?

2. **Back-to-back (5-tile run)** — chain 5 `advance_frames_until` calls in the
   same direction. Compare frames_elapsed across calls (should stabilize if
   sustained-hold works). Compare no-gap vs 1f-gap vs 2f-gap between calls.
   If a gap costs frames, the engine sees a release.

3. **Release-at-change settle** — trigger, then release for varying durations.
   Tells us if the player drifts, overshoots, or stays put.

4. **Direction change** — hold up until moved, then immediately hold right.
   Does the direction change cost any extra frames? (Same-call buttons change.)
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from melonds_mcp.client import EmulatorClient
from renegade_mcp import addresses
from renegade_mcp.connection import get_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from helpers import do_load_state  # noqa: E402


def read_pos(emu: EmulatorClient) -> tuple[int, int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    m = emu.read_memory(base, size="long")
    x = emu.read_memory(base + 8, size="long")
    y = emu.read_memory(base + 12, size="long")
    return m, x, y


def _btns(direction: str, aux: list[str] | None) -> list[str]:
    return [direction] + (aux or [])


def experiment_1_hold_threshold(emu: EmulatorClient, direction: str, save: str,
                                 max_hold: int = 24,
                                 aux: list[str] | None = None) -> None:
    """How many frames of held input are needed for a step to commit?"""
    tag = "+".join([direction] + (aux or []))
    print(f"\n=== EXP1: hold threshold [{save}, {tag}] ===")
    print(f"{'hold_f':>8} {'pos_change_f':>14} {'start_pos':>12} {'release_pos':>14} "
          f"{'final_pos':>14} {'commit?':>8}")
    for hold_f in range(1, max_hold + 1):
        do_load_state(emu, save)

        _, sx, sy = read_pos(emu)
        # Hold and watch: poll every frame for change
        res = emu.advance_frames_until(
            max_frames=hold_f,
            conditions=[{"type": "changed", "address": addresses.addr("PLAYER_POS_BASE") + (8 if direction in ("left","right") else 12), "size": "long"}],
            poll_interval=1,
            buttons=_btns(direction, aux),
        )
        triggered = res.get("triggered", False)
        pos_change_f = res.get("frames_elapsed") if triggered else None

        # If the condition hasn't fired by hold_f, advance remaining frames still holding
        remaining = hold_f - res["frames_elapsed"]
        if remaining > 0:
            emu.advance_frames(remaining, buttons=_btns(direction, aux))
        _, rx, ry = read_pos(emu)

        # Now release for 60 frames and see final
        emu.advance_frames(60)
        _, fx, fy = read_pos(emu)

        committed = (fx, fy) != (sx, sy)
        print(f"{hold_f:>8} {str(pos_change_f):>14} {f'({sx},{sy})':>12} "
              f"{f'({rx},{ry})':>14} {f'({fx},{fy})':>14} {committed!s:>8}")


def experiment_2_back_to_back(emu: EmulatorClient, direction: str, save: str,
                               hold_cap: int = 30, num_tiles: int = 5,
                               aux: list[str] | None = None) -> None:
    """N consecutive holds — does the engine see a release between calls?

    Chains N `advance_frames_until(cond=pos_changed, buttons=[dir])` calls
    back-to-back. If the engine sees a release between calls, the per-tile
    frame count should spike (re-accelerate). If it doesn't, the per-tile
    counts should be stable (or trending down if there's engine-side
    acceleration curve).
    """
    axis_offset = 8 if direction in ("left", "right") else 12

    tag = "+".join([direction] + (aux or []))
    for gap_frames in (0, 1, 2, 4):
        label = "no-gap" if gap_frames == 0 else f"{gap_frames}f-release-gap"
        print(f"\n=== EXP2: {num_tiles}-tile run [{save}, {tag}, {label}] ===")
        do_load_state(emu, save)
        _, sx, sy = read_pos(emu)
        print(f"  start={sx},{sy}")

        positions = [(sx, sy)]
        frames = []
        for tile_i in range(num_tiles):
            if tile_i > 0 and gap_frames > 0:
                emu.advance_frames(gap_frames)  # NO buttons held
            res = emu.advance_frames_until(
                max_frames=hold_cap,
                conditions=[{"type": "changed",
                             "address": addresses.addr("PLAYER_POS_BASE") + axis_offset,
                             "size": "long"}],
                poll_interval=1,
                buttons=_btns(direction, aux),
            )
            _, nx, ny = read_pos(emu)
            positions.append((nx, ny))
            frames.append(res["frames_elapsed"])

        # Settle
        emu.advance_frames(60)
        _, fx, fy = read_pos(emu)
        total_tiles = abs(fx - sx) + abs(fy - sy)
        print(f"  per-tile frames: {frames}")
        print(f"  positions after each call: {positions}")
        print(f"  final (60f settle): ({fx},{fy})  total tiles moved: {total_tiles}")


def experiment_3_release_settle(emu: EmulatorClient, direction: str, save: str,
                                 aux: list[str] | None = None) -> None:
    """After condition fires, do we settle on that tile or keep moving?"""
    axis_offset = 8 if direction in ("left", "right") else 12
    tag = "+".join([direction] + (aux or []))
    print(f"\n=== EXP3: release-at-change settle [{save}, {tag}] ===")

    for settle_f in (0, 1, 2, 4, 8, 16, 32, 64):
        do_load_state(emu, save)
        _, sx, sy = read_pos(emu)

        res = emu.advance_frames_until(
            max_frames=30,
            conditions=[{"type": "changed",
                         "address": addresses.addr("PLAYER_POS_BASE") + axis_offset,
                         "size": "long"}],
            poll_interval=1,
            buttons=_btns(direction, aux),
        )
        _, cx, cy = read_pos(emu)

        if settle_f > 0:
            emu.advance_frames(settle_f)  # NO buttons
        _, fx, fy = read_pos(emu)

        print(f"  settle={settle_f:>3}f: pos_at_trigger=({cx},{cy}) frames_to_trigger="
              f"{res['frames_elapsed']}  final_after_settle=({fx},{fy})")


def experiment_4_direction_change(emu: EmulatorClient, save: str) -> None:
    """Hold UP until moved, then immediately hold RIGHT. Does the turn cost extra frames?

    Compares: (a) first-tile UP from standing still; (b) first-tile RIGHT
    immediately after UP completed (no gap); (c) first-tile RIGHT from
    standing still. If (b) is materially more expensive than (c), direction
    changes cost frames that straight-line runs don't.
    """
    print(f"\n=== EXP4: direction change [{save}] ===")
    BASE = addresses.addr("PLAYER_POS_BASE")

    # (a) First UP from rest
    do_load_state(emu, save)
    res_a = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": BASE + 12, "size": "long"}],
        poll_interval=1, buttons=["up"],
    )
    print(f"  (a) first UP from rest: {res_a['frames_elapsed']}f")

    # (b) RIGHT immediately after UP (same session)
    res_b1 = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": BASE + 12, "size": "long"}],
        poll_interval=1, buttons=["up"],
    )
    res_b2 = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": BASE + 8, "size": "long"}],
        poll_interval=1, buttons=["right"],
    )
    print(f"  (b) UP then RIGHT: UP={res_b1['frames_elapsed']}f, RIGHT={res_b2['frames_elapsed']}f")

    # (c) First RIGHT from rest (reset)
    do_load_state(emu, save)
    res_c = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": BASE + 8, "size": "long"}],
        poll_interval=1, buttons=["right"],
    )
    print(f"  (c) first RIGHT from rest: {res_c['frames_elapsed']}f")

    # (d) RIGHT immediately after UP with NO frame gap (buttons change in single call sequence)
    do_load_state(emu, save)
    _ = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": BASE + 12, "size": "long"}],
        poll_interval=1, buttons=["up"],
    )
    # Advance 1 frame with NO buttons (simulate a release)
    emu.advance_frames(1)
    res_d = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": BASE + 8, "size": "long"}],
        poll_interval=1, buttons=["right"],
    )
    print(f"  (d) UP, 1f release, RIGHT: RIGHT={res_d['frames_elapsed']}f")


def experiment_5_momentum_slide(emu: EmulatorClient, direction: str, save: str,
                                 aux: list[str] | None = None) -> None:
    """Hold for N frames, then release for 120f. How far does the player travel?"""
    tag = "+".join([direction] + (aux or []))
    print(f"\n=== EXP5: momentum slide [{save}, {tag}] ===")
    print(f"{'hold_f':>8} {'pos_during_hold':>16} {'pos_after_120f_release':>24} "
          f"{'tiles_during':>14} {'tiles_after':>14}")

    for hold_f in (6, 11, 16, 24, 32, 48, 64, 96, 128, 200):
        do_load_state(emu, save)
        _, sx, sy = read_pos(emu)
        emu.advance_frames(hold_f, buttons=_btns(direction, aux))
        _, hx, hy = read_pos(emu)
        emu.advance_frames(120)  # no buttons — pure settle
        _, fx, fy = read_pos(emu)
        during = abs(hx - sx) + abs(hy - sy)
        after = abs(fx - hx) + abs(fy - hy)
        print(f"{hold_f:>8} {f'({hx},{hy})':>16} {f'({fx},{fy})':>24} "
              f"{during:>14} {after:>14}")


def main():
    emu = get_client()

    # Running (B+direction) on the on-foot open-ground save. If running has no
    # momentum and faster per-tile frames than walking, it replaces walking as
    # the general-nav default.
    SAVE = "spike_eterna_open_ground"
    print(f"\n{'#' * 60}\n# RUNNING (B+dir) on {SAVE}\n{'#' * 60}")
    do_load_state(emu, SAVE)
    m, x, y = read_pos(emu)
    print(f"Loaded {SAVE}: map={m} pos=({x},{y})")

    experiment_1_hold_threshold(emu, "up", SAVE, max_hold=20, aux=["b"])
    experiment_2_back_to_back(emu, "up", SAVE, hold_cap=30, num_tiles=5, aux=["b"])
    experiment_3_release_settle(emu, "up", SAVE, aux=["b"])
    experiment_5_momentum_slide(emu, "up", SAVE, aux=["b"])


if __name__ == "__main__":
    main()
