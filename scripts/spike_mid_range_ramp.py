"""Characterize bike-ramp jump landings across runway × release × gear regimes.

Goal — find an input pattern that produces a clean **ramp+3** landing so BFS
can model it and solve the Wayward B1F row-6 chain puzzle.  Map 285 row 6::

    x   17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38
    beh 7a 7a 7b 7b 7b 7b 7a 7a 70 08 08 08 d7 08 00 08 d7 08 00 08 08 08
         ↑ bike bridge (EW)      ↑ floor   ↑ram1 ↑ ↑-- ↑=target
                                                  void  x=32 POCKET

Ramp1 lives at x=29; ramp2 at x=33.  Void at x=31 between ramp1 and ramp2,
void at x=35 east of ramp2.  The single-tile pocket at x=32 (between ramp2
and the void east of it) is the only access point to the Pokéball pocket at
(33, 8).  FAR jump lands at ramp+4 = x=33 = ON ramp2 → auto-chains → x=38.
NEAR jump (cold start) lands at ramp+1 = x=30 — dead-end, blocked south at
(31, 7)=0x39 column.  We must produce ramp+3 (x=32) to split the chain.

Test environment
----------------
``session42_wayward_b1f_first_ramp_approach`` — player at (25, 6) facing left,
OFF bike on bridge_start (0x70).  Approach tile = (28, 6).  Runway tiles
(25-28) are all walkable while cycling.  West of x=25 is bike bridge body
(bike-only — convenient for runway measurement since we start on-bike).

Regimes swept
-------------
* **Runway × continuous hold, FAST gear** — start at (start_x, 6) on bike
  FAST, hold right through ramp.  Sweep start_x ∈ {28, 27, 26, 25} — that
  is, runway = 1, 2, 3, 4 tiles (inclusive of approach).
* **Runway × continuous hold, SLOW gear** — same sweep, SLOW.
* **Release-timing sweep, FAST, full runway** — start at (25, 6) with max
  runway, hold right until player.x reaches trigger, release.  Sweep trigger.

All trials use the modern ``_set_bike_gear`` API (B-press toggle).  Direct
memory writes to the gear byte get re-synced by the engine within ~10 frames
(addresses.py:121–142) and are unreliable in current code.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.use_item import _set_bike_gear, use_item  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "session42_wayward_b1f_first_ramp_approach"
SOCK = ".melonds_test_bridge.sock"
TARGET_ROW = 6
RAMP1_X = 29
RAMP2_X = 33
POCKET_X = 32  # ramp1+3, the single-tile target we need to reach


def _pos(emu: EmulatorClient) -> tuple[int, int]:
    base = addresses.addr("PLAYER_POS_BASE")
    return (
        emu.read_memory(base + 8, size="long"),
        emu.read_memory(base + 12, size="long"),
    )


def _on_bike(emu: EmulatorClient) -> bool:
    return bool(emu.read_memory(addresses.addr("CYCLING_GEAR_ADDR"), size="short"))


def _gear_byte(emu: EmulatorClient) -> int:
    return emu.read_memory(addresses.addr("BIKE_GEAR_STATE_ADDR"), size="byte")


def _status_line(emu: EmulatorClient, tag: str) -> None:
    x, y = _pos(emu)
    print(f"    [{tag}] pos=({x},{y}) bike={int(_on_bike(emu))} "
          f"gear_byte={_gear_byte(emu)}")


def _step_right(emu: EmulatorClient) -> bool:
    base = addresses.addr("PLAYER_POS_BASE")
    res = emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed", "address": base + 8, "size": "long"}],
        poll_interval=1,
        buttons=["right"],
    )
    if not res.get("triggered"):
        return False
    emu.advance_frames(90)  # drain coast / residual momentum
    return True


def setup(emu: EmulatorClient, start_x: int, gear: int) -> bool:
    """Place player at (start_x, 6) on bike with requested gear.

    Protocol:
      1. Load session42 (player at (25, 6), off bike, facing left).
      2. Mount bike via ``use_item("Bicycle")`` — works on bridge_start tile.
      3. Set gear.
      4. For start_x > 25, step east that many tiles with 90f settles
         between so each new start tile is cold (momentum=0).
      5. For start_x == 25, already there — the tile to our west (24, 6) is
         bike_bridge body so we could extend runway further, but every east
         tile from (25, 6) through (28, 6) is clean runway.
    """
    do_load_state(emu, SAVE, redetect_shift=True)
    if _on_bike(emu):
        return False  # save should start off-bike; if not, state drift
    r = use_item(emu, "Bicycle")
    if not r.get("success") or not _on_bike(emu):
        print(f"    mount failed: {r}")
        return False
    if not _set_bike_gear(emu, gear):
        print(f"    gear set failed (target={gear}, byte={_gear_byte(emu)})")
        return False

    # Step east from (25, 6) to (start_x, 6) with cold-start settle per tile.
    for _ in range(start_x - 25):
        if not _step_right(emu):
            return False
        if not _set_bike_gear(emu, gear):
            return False

    x, y = _pos(emu)
    return (x, y) == (start_x, TARGET_ROW)


def trial_continuous_hold(
    emu: EmulatorClient, start_x: int, gear: int, max_frames: int = 300,
) -> dict:
    """Hold RIGHT continuously from (start_x, 6); record trajectory + landing."""
    if not setup(emu, start_x, gear):
        return {"start_x": start_x, "gear": gear, "error": "setup failed"}

    base = addresses.addr("PLAYER_POS_BASE")
    trajectory: list[tuple[int, int, int]] = [(*_pos(emu), 0)]
    frames = 0
    stall = 0
    last = trajectory[0][:2]
    while frames < max_frames:
        emu.advance_frames(2, buttons=["right"])
        frames += 2
        x, y = _pos(emu)
        if (x, y) != last:
            trajectory.append((x, y, frames))
            last = (x, y)
            stall = 0
        else:
            stall += 2
            if stall >= 60:
                break
    emu.advance_frames(30)
    fx, fy = _pos(emu)
    return {
        "start_x": start_x, "gear": gear,
        "trajectory": trajectory,
        "final": (fx, fy),
        "runway_tiles": 29 - start_x,  # tiles from start to approach (inclusive)
    }


def trial_release_at_x(
    emu: EmulatorClient, start_x: int, release_x: int, gear: int = 0,
) -> dict:
    """Hold RIGHT until player.x >= release_x, release, 60f idle, record."""
    if not setup(emu, start_x, gear):
        return {"start_x": start_x, "release_x": release_x, "error": "setup failed"}

    base = addresses.addr("PLAYER_POS_BASE")
    res = emu.advance_frames_until(
        max_frames=240,
        conditions=[{"type": "value", "address": base + 8, "size": "long",
                     "operator": ">=", "value": release_x}],
        poll_interval=1,
        buttons=["right"],
    )
    x_rel, y_rel = _pos(emu)
    triggered = res.get("triggered", False)
    emu.advance_frames(60)
    fx, fy = _pos(emu)
    return {
        "start_x": start_x, "release_x": release_x, "gear": gear,
        "triggered": triggered,
        "at_release": (x_rel, y_rel),
        "final": (fx, fy),
    }


def fmt_landing(final: tuple[int, int]) -> str:
    fx = final[0]
    rel = fx - RAMP1_X
    tag = {
        0: "@RAMP1",
        1: "ramp1+1 (NEAR)",
        2: "ramp1+2",
        3: "ramp1+3 (TARGET)",
        4: "ramp1+4 (ON RAMP2)",
        5: "ramp1+5 (CHAIN+0)",
        9: "ramp1+9 (CHAIN+5)",
    }.get(rel, f"ramp1{rel:+d}")
    return f"x={fx:>3}  [{tag}]"


def print_trajectory(traj: list[tuple[int, int, int]]) -> None:
    if not traj:
        return
    if len(traj) <= 8:
        for s in traj:
            print(f"        {s}")
        return
    for s in traj[:3]:
        print(f"        {s}")
    print(f"        ... ({len(traj) - 6} mid samples elided)")
    for s in traj[-3:]:
        print(f"        {s}")


def main() -> None:
    emu = EmulatorClient(SOCK)
    print("=" * 78)
    print("WAYWARD CAVE B1F ROW-6 RAMP CHAIN — MID-RANGE JUMP SPIKE")
    print(f"  save={SAVE}")
    print(f"  ramp1 at x={RAMP1_X}, ramp2 at x={RAMP2_X}, target pocket x={POCKET_X}")
    print(f"  Need landing at x={POCKET_X} (ramp1+3) to split the chain.")
    print("=" * 78)

    # ── Section B: Runway sweep × gear, continuous hold ──
    print("\n[B] Runway sweep × gear, CONTINUOUS HOLD RIGHT:")
    for gear, gname in [(0, "FAST"), (1, "SLOW")]:
        print(f"\n  -- {gname} gear --")
        for sx in (28, 27, 26, 25):
            r = trial_continuous_hold(emu, sx, gear=gear)
            if "error" in r:
                print(f"    start=({sx},6): ERROR {r['error']}")
                continue
            runway = r["runway_tiles"] + 1  # include approach tile
            print(f"    start=({sx},6) runway={runway}t  "
                  f"final={r['final']}  {fmt_landing(r['final'])}")
            print_trajectory(r["trajectory"])

    # ── Section C: Release-timing sweep from full runway (25, 6), FAST ──
    print("\n[C] Release-timing sweep from (25,6) FAST "
          "(release when player.x >= trigger):")
    for trig in (26, 27, 28, 29, 30, 31, 32, 33):
        r = trial_release_at_x(emu, start_x=25, release_x=trig, gear=0)
        if "error" in r:
            print(f"    trig={trig}: ERROR {r['error']}")
            continue
        print(f"    trig={trig:>2}  at_release={r['at_release']}  "
              f"final={r['final']}  {fmt_landing(r['final'])}  "
              f"triggered={r['triggered']}")

    # ── Section D: Release-timing sweep from approach (28, 6), FAST ──
    print("\n[D] Release-timing from (28,6) FAST (1t runway, release at trigger):")
    for trig in (29, 30, 31, 32):
        r = trial_release_at_x(emu, start_x=28, release_x=trig, gear=0)
        if "error" in r:
            print(f"    trig={trig}: ERROR {r['error']}")
            continue
        print(f"    trig={trig:>2}  at_release={r['at_release']}  "
              f"final={r['final']}  {fmt_landing(r['final'])}  "
              f"triggered={r['triggered']}")

    # ── Section E: End-to-end puzzle solve ──
    # Sanity: (25,6) → hold-release-at-ramp → (32,6) → step south + east
    # → arrive at (33,8) facing east = ready to pick up Pokéball.
    print("\n[E] End-to-end puzzle solve from (25,6) → Pokéball at (33,8):")
    if not setup(emu, 25, gear=0):
        print("    setup failed")
    else:
        base = addresses.addr("PLAYER_POS_BASE")
        # Hold right until player.x >= 29 (ramp tile), release + idle.
        emu.advance_frames_until(
            max_frames=240,
            conditions=[{"type": "value", "address": base + 8, "size": "long",
                         "operator": ">=", "value": 29}],
            poll_interval=1,
            buttons=["right"],
        )
        emu.advance_frames(60)  # landing settles
        x, y = _pos(emu)
        print(f"    after ramp jump: ({x},{y})  {fmt_landing((x,y))}")
        if (x, y) != (32, 6):
            print(f"    ✗ expected (32, 6); abort descent")
        else:
            # Step down from (32, 6) to (32, 8), then east to (33, 8).
            for expected in [(32, 7), (32, 8)]:
                res = emu.advance_frames_until(
                    max_frames=30,
                    conditions=[{"type": "changed",
                                 "address": base + 12, "size": "long"}],
                    poll_interval=1, buttons=["down"])
                emu.advance_frames(30)
                x, y = _pos(emu)
                ok = (x, y) == expected
                print(f"    step down  → ({x},{y}) {'✓' if ok else '✗ expected '+str(expected)}")
            # East to (33, 8) — this should land on the Pokéball / trigger
            # the item-get dialogue, but we just want to verify the tile is
            # reachable (Pokéball OBJ may be an NPC face to interact).
            res = emu.advance_frames_until(
                max_frames=30,
                conditions=[{"type": "changed",
                             "address": base + 8, "size": "long"}],
                poll_interval=1, buttons=["right"])
            emu.advance_frames(30)
            x, y = _pos(emu)
            print(f"    step right → ({x},{y})")
            print(f"    {'✓ reached' if (x,y)==(33,8) else '✗ expected (33, 8)'} the Pokéball tile")

    print("\nDone.")


if __name__ == "__main__":
    main()
