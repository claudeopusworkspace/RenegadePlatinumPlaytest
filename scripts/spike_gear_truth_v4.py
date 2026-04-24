"""Determine gear encoding by forcing each byte value then attempting slope climb
from a REAL slope bottom (route207_at_bike_slope_bottom).

The Route 207 slope is at (306, 718-719). Player starts at (306, 720) facing left.
To climb: turn to face up, run runway south, then hold UP to go N through the slope.
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

    for target_byte in [0, 1]:
        emu.load_state(SAVE)
        emu.advance_frames(120)
        st = read_state()
        print(f"\n=== target_byte={target_byte} ===")
        print(f"  post-load: {st}")

        # Mount bike
        if not st["cycling"]:
            use_item(emu, "Bicycle")
            emu.advance_frames(90)
        st = read_state()
        print(f"  post-mount: {st}")

        # Force gear to target_byte
        toggles = 0
        for _ in range(6):
            if emu.read_memory(gear_addr, size="byte") == target_byte:
                break
            emu.press_buttons(["b"], frames=8)
            emu.advance_frames(30)
            toggles += 1
        st = read_state()
        print(f"  post-toggle ({toggles} B-presses): {st}")

        # Back up south 3 tiles for runway
        for _ in range(3):
            emu.advance_frames(16, buttons=["down"])
            emu.advance_frames(8)
        st = read_state()
        print(f"  post-backup: {st}")

        # Hold UP continuously for 400 frames
        emu.advance_frames(400, buttons=["up"])
        emu.advance_frames(60)
        end = read_state()
        print(f"  end: {end}")
        dy = end["y"] - st["y"]
        print(f"  Δy={dy}  -> {'CLIMBED SLOPE' if end['y'] <= 718 else 'BLOCKED BELOW SLOPE'}")


if __name__ == "__main__":
    main()
