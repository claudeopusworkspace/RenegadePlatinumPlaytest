"""Determine gear encoding by forcing each value then observing slope ascent.

Uses bug_bike_slope_north_climb_fail (Wayward B1F at slope base, mounted on bike).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE = "bug_bike_slope_north_climb_fail"


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr, reset, detect_shift
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE)
    emu.advance_frames(120)
    reset()
    detect_shift(emu)

    ppb = addr("PLAYER_POS_BASE")
    gear_addr = addr("BIKE_GEAR_STATE_ADDR")
    cycling_addr = addr("CYCLING_GEAR_ADDR")

    print(f"PPB=0x{ppb:08x}  BIKE_GEAR=0x{gear_addr:08x}  CYCLING=0x{cycling_addr:08x}")

    def read_state():
        return {
            "gear": emu.read_memory(gear_addr, size="byte"),
            "cycling": bool(emu.read_memory(cycling_addr, size="short")),
            "map": emu.read_memory(ppb, size="long"),
            "x": emu.read_memory(ppb + 8, size="long"),
            "y": emu.read_memory(ppb + 12, size="long"),
        }

    print(f"\nPost-load: {read_state()}")

    # Mount bike if needed
    if not read_state()["cycling"]:
        use_item(emu, "Bicycle")
        emu.advance_frames(60)
        print(f"After mount: {read_state()}")

    for target_byte in [0, 1]:
        emu.load_state(SAVE)
        emu.advance_frames(120)
        if not read_state()["cycling"]:
            use_item(emu, "Bicycle")
            emu.advance_frames(60)

        # Force gear to target_byte via B toggles
        for _ in range(6):
            if emu.read_memory(gear_addr, size="byte") == target_byte:
                break
            emu.press_buttons(["b"], frames=8)
            emu.advance_frames(30)

        start = read_state()
        print(f"\n=== target_byte={target_byte} — actual: {start} ===")

        # Hold UP for 300 frames (enough for runway + slope)
        emu.advance_frames(300, buttons=["up"])
        emu.advance_frames(60)

        end = read_state()
        print(f"    end: {end}")
        dy = end["y"] - start["y"]
        dx = end["x"] - start["x"]
        print(f"    Δx={dx}  Δy={dy}  {'CLIMBED' if dy < -3 else 'BLOCKED'}")


if __name__ == "__main__":
    main()
