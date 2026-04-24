"""Determine empirically which value of PPB+0x8c corresponds to FAST vs SLOW.

For each byte value in {0, 1}:
  1. Force the bike into that value by toggling B until observed value matches.
  2. Position at runway bottom, hold UP for 180f.
  3. Check if the player Y actually moved up past the slope boundary.

FAST gear climbs the slope, SLOW gear is blocked. This tells us the true encoding.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE = "bug_slope_ascent_mount_thrash"


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr, reset, detect_shift
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE)
    emu.advance_frames(120)
    reset()
    detect_shift(emu)

    cycling_addr = addr("CYCLING_GEAR_ADDR")
    gear_addr = addr("BIKE_GEAR_STATE_ADDR")
    pos_x_addr = addr("PLAYER_POS_BASE")

    print(f"CYCLING_GEAR_ADDR: 0x{cycling_addr:08x}")
    print(f"BIKE_GEAR_STATE_ADDR: 0x{gear_addr:08x}")

    # Make sure we're on the bike
    cycling = bool(emu.read_memory(cycling_addr, size="short"))
    print(f"\nInitial cycling state: {cycling}")
    if not cycling:
        r = use_item(emu, "Bicycle")
        emu.advance_frames(60)
        cycling = bool(emu.read_memory(cycling_addr, size="short"))
        print(f"After mount: cycling={cycling}")

    # Read player Y (at PPB+4)
    def read_pos():
        x = emu.read_memory(pos_x_addr, size="long")
        y = emu.read_memory(pos_x_addr + 4, size="long")
        z = emu.read_memory(pos_x_addr + 8, size="long")
        return (x, y, z)

    def read_gear():
        return emu.read_memory(gear_addr, size="byte")

    print(f"\nInitial pos: {read_pos()}, gear byte: {read_gear()}")

    # Test each gear value
    for target_value in [0, 1]:
        emu.load_state(SAVE)
        emu.advance_frames(120)

        # Ensure cycling
        if not bool(emu.read_memory(cycling_addr, size="short")):
            use_item(emu, "Bicycle")
            emu.advance_frames(60)

        # Force gear to target_value via B-press toggles
        for _ in range(6):
            if read_gear() == target_value:
                break
            emu.press_buttons(["b"], frames=8)
            emu.advance_frames(30)

        actual = read_gear()
        start_pos = read_pos()
        print(f"\n--- Test with gear byte = {target_value} (actual: {actual}) ---")
        print(f"Starting pos: {start_pos}")

        # Hold UP for 180 frames
        emu.advance_frames(180, buttons=["up"])
        emu.advance_frames(30)

        end_pos = read_pos()
        end_gear = read_gear()
        print(f"Ending pos:   {end_pos}")
        print(f"Ending gear:  {end_gear}")
        print(f"Y delta: {end_pos[1] - start_pos[1]}  (negative = moved up/north)")
        if end_pos[1] < start_pos[1] - 3:
            print(f"==> gear byte {target_value} = FAST (climbed the slope)")
        else:
            print(f"==> gear byte {target_value} = SLOW (blocked at runway)")


if __name__ == "__main__":
    main()
