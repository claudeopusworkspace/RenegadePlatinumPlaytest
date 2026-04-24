"""BUG-046: empirical — can the player walk from (7, 30) to (7, 25) on foot?
If yes, terrain is fine and the bike's north-stop at (7, 30) is a bike-specific
tile behavior (slope rejection?). If no, there's a ledge or elevation issue.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE_STATE = "session31_wayward_cave_bike_ramps"


def pos(emu):
    from renegade_mcp.addresses import addr
    base = addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def step(emu, direction, max_frames=60):
    from renegade_mcp.addresses import addr
    axis = 8 if direction in ("left", "right") else 12
    before = pos(emu)
    res = emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[{"type": "changed",
                     "address": addr("PLAYER_POS_BASE") + axis, "size": "long"}],
        poll_interval=1,
        buttons=[direction],
    )
    emu.advance_frames(16)
    after = pos(emu)
    moved = before != after
    return moved, after


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE_STATE)
    emu.advance_frames(120)

    cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
    print(f"Start: pos={pos(emu)} cycling={cycling}")
    if cycling:
        use_item(emu, "Bicycle")
        emu.advance_frames(60)
        print(f"Post-dismount: pos={pos(emu)} cycling={bool(emu.read_memory(addr('CYCLING_GEAR_ADDR'), size='short'))}")

    # Walk down step by step from (7, 22)
    print("\nWalking DOWN from start:")
    for i in range(15):
        moved, p = step(emu, "down")
        print(f"  down {i+1}: moved={moved} pos={p}")
        if not moved:
            print(f"  BLOCKED going down at {p}!")
            break
        if p[1] >= 34:
            break

    # Now walk UP step by step back to start
    print("\nWalking UP back to start:")
    for i in range(15):
        moved, p = step(emu, "up")
        print(f"  up {i+1}: moved={moved} pos={p}")
        if not moved:
            print(f"  BLOCKED going up at (7, {p[1]}) — trying to reach (7, {p[1]-1})")
            break
        if p[1] <= 20:
            break

    print(f"\nFinal pos: {p}")


if __name__ == "__main__":
    main()
