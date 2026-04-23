"""Precisely measure: where does the player end up when we poll for x>=landing
and release, with various post-settle durations?

Hypothesis: the 4-frame post-landing settle (at 4 frames/tile bike fast gear)
is exactly enough time for the engine to commit one more tile of in-progress
animation, producing a 1-tile overshoot.

Approach: from (5, 17) with known 4-tile runway, hold right, poll for
x>=13 (BFS landing = approach_x=9 + 4). Vary the post-settle: 0, 2, 4, 8
frames. Record final x after each variant.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR  # noqa: E402
from renegade_mcp.navigation import navigate_to as _navigate_to  # noqa: E402

from helpers import do_load_state  # noqa: E402


SAVE = "session31_wayward_cave_bike_ramps"
SOCK = ".melonds_test_bridge.sock"
START_X = 5
APPROACH_X = 9     # one before ramp
LANDING_X = 14     # approach + 5 (= ramp + 4, empirical fast-gear landing)


def setup(emu: EmulatorClient) -> None:
    """Place player at (5, 17) on bike in fast gear."""
    do_load_state(emu, SAVE, redetect_shift=True)
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")
    _navigate_to(emu, target_x=4, target_y=17, flee_encounters=True)
    emu.advance_frames(90)
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")
    # Step right once to (5, 17)
    pos_base = addresses.addr("PLAYER_POS_BASE")
    emu.advance_frames_until(
        max_frames=30,
        conditions=[{"type": "changed",
                     "address": pos_base + 8, "size": "long"}],
        poll_interval=1,
        buttons=["right"],
    )
    emu.advance_frames(90)
    emu.write_memory(BIKE_GEAR_STATE_ADDR, value=0, size="byte")


def trial(emu: EmulatorClient, poll_target: int, post_settle: int) -> int:
    """Place player at (5, 17), hold right, poll x>=poll_target, release.

    Returns final x after post_settle frames of no input.
    """
    setup(emu)
    pos_base = addresses.addr("PLAYER_POS_BASE")
    x_before = emu.read_memory(pos_base + 8, size="long")
    assert x_before == START_X, f"setup failed: x={x_before}"
    emu.advance_frames_until(
        max_frames=120,
        conditions=[{"type": "value", "address": pos_base + 8,
                     "size": "long", "operator": ">=",
                     "value": poll_target}],
        poll_interval=1,
        buttons=["right"],
    )
    x_at_release = emu.read_memory(pos_base + 8, size="long")
    if post_settle > 0:
        emu.advance_frames(post_settle)
    x_final = emu.read_memory(pos_base + 8, size="long")
    return x_at_release, x_final


def main() -> None:
    emu = EmulatorClient(SOCK)
    print(f"Start=({START_X},17), approach=({APPROACH_X},17), BFS landing=({LANDING_X},17)\n")
    print(f"{'poll_target':>11} {'settle':>6} {'x_at_release':>13} {'x_final':>8} {'delta':>6}")
    for settle in (0, 4, 8, 16, 32, 64):
        x_rel, x_fin = trial(emu, poll_target=LANDING_X, post_settle=settle)
        print(f"{LANDING_X:>11} {settle:>6} {x_rel:>13} {x_fin:>8} {x_fin - LANDING_X:+d}")
    print()
    # poll at approach+5 (one past BFS landing): does drift overshoot further?
    for settle in (0, 4, 8, 16, 32, 64):
        x_rel, x_fin = trial(emu, poll_target=LANDING_X + 1, post_settle=settle)
        print(f"{LANDING_X+1:>11} {settle:>6} {x_rel:>13} {x_fin:>8} {x_fin - LANDING_X:+d}")
    print()
    # Old-behavior simulation: hold button just long enough to step onto ramp
    # (to ramp_x), then release and let jump play out.
    print("Baseline — release at ramp tile (x=10), idle various durations:")
    for settle in (16, 32, 40, 60, 90):
        x_rel, x_fin = trial(emu, poll_target=10, post_settle=settle)
        print(f"{10:>11} {settle:>6} {x_rel:>13} {x_fin:>8}")


if __name__ == "__main__":
    main()
