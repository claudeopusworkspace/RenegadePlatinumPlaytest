"""BUG-046: trace bike state every 50 frames during a slope-bound hold.

Tracks position, cycling state, FOW gear, BIKE mirror throughout the hold.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE_STATE = "bug_slope_ascent_mount_thrash"
FOW = 0x0227f4bc
BIKE = 0x021bf6ac


def read_state(emu):
    from renegade_mcp.addresses import addr
    base = addr("PLAYER_POS_BASE")
    return {
        "x": emu.read_memory(base + 8, size="long"),
        "y": emu.read_memory(base + 12, size="long"),
        "cycling": bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")),
        "FOW": emu.read_memory(FOW, size="byte"),
        "BIKE": emu.read_memory(BIKE, size="byte"),
    }


def step(emu, direction, max_frames=60):
    from renegade_mcp.addresses import addr
    axis = 8 if direction in ("left", "right") else 12
    res = emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[{"type": "changed",
                     "address": addr("PLAYER_POS_BASE") + axis, "size": "long"}],
        poll_interval=1,
        buttons=[direction],
    )
    emu.advance_frames(8)
    return bool(res.get("triggered"))


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE_STATE)
    emu.advance_frames(60)
    if bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")):
        use_item(emu, "Bicycle")
        emu.advance_frames(30)

    # Walk to (7, 31)
    for _ in range(3):
        step(emu, "down")

    # Fresh mount
    use_item(emu, "Bicycle")
    emu.advance_frames(90)
    s = read_state(emu)
    print(f"Pre-hold: {s}")

    # Trace during hold — chunked advance_frames with buttons=["up"]
    for chunk in range(12):  # 12 × 50f = 600f max
        emu.advance_frames(50, buttons=["up"])
        s = read_state(emu)
        print(f"  +{50*(chunk+1):3d}f: {s}")
        if s["y"] <= 25:
            break

    # Release + settle
    emu.advance_frames(120)
    s = read_state(emu)
    print(f"After settle: {s}")


if __name__ == "__main__":
    main()
