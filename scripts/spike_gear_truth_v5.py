"""Confirm _set_bike_gear(0) now produces FAST (climbs slope).

Uses route207_at_bike_slope_bottom — player south of Route 207 slope.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE = "route207_at_bike_slope_bottom"


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr, reset, detect_shift
    from renegade_mcp.use_item import _set_bike_gear, use_item

    for target_gear, label in [(0, "FAST (decomp 0)"), (1, "SLOW (decomp 1)")]:
        emu.load_state(SAVE)
        emu.advance_frames(120)
        reset()
        detect_shift(emu)

        ppb = addr("PLAYER_POS_BASE")
        bgs = addr("BIKE_GEAR_STATE_ADDR")
        cyc = addr("CYCLING_GEAR_ADDR")

        def read_state():
            return {
                "gear_byte": emu.read_memory(bgs, size="byte"),
                "cycling": bool(emu.read_memory(cyc, size="short")),
                "x": emu.read_memory(ppb + 8, size="long"),
                "y": emu.read_memory(ppb + 12, size="long"),
            }

        # Mount if needed
        if not read_state()["cycling"]:
            use_item(emu, "Bicycle")
            emu.advance_frames(90)

        # Use the API to set gear
        _set_bike_gear(emu, target_gear)
        st = read_state()
        print(f"\n=== _set_bike_gear({target_gear}) — {label} ===")
        print(f"  post-call: {st}")

        # Backup 3 tiles south
        for _ in range(3):
            emu.advance_frames(16, buttons=["down"])
            emu.advance_frames(8)

        st_pre = read_state()
        # Hold UP 400f
        emu.advance_frames(400, buttons=["up"])
        emu.advance_frames(60)
        st_end = read_state()
        climbed = st_end["y"] <= 718
        print(f"  pre-hold y={st_pre['y']}, end y={st_end['y']}, map={emu.read_memory(ppb, size='long')}")
        print(f"  -> {'CLIMBED' if climbed else 'BLOCKED'}")


if __name__ == "__main__":
    main()
