"""Verify PLAYER_POS_BASE + 0x48 reliably reflects cycling state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE = "route207_at_bike_slope_bottom"
NEW_CYCLING = 0x0227F498
OLD_CYCLING = 0x0227F4E0


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE)
    emu.advance_frames(120)

    def state():
        return {
            "NEW (+0x48)": emu.read_memory(NEW_CYCLING, size="byte"),
            "OLD (+0x90)": emu.read_memory(OLD_CYCLING, size="short"),
        }

    print(f"Post-load:       {state()}")

    # Toggle 4 times, check both addresses against what use_item reports
    for i in range(4):
        r = use_item(emu, "Bicycle")
        emu.advance_frames(60)
        expected = "ON" if r.get("on_bicycle") else "OFF"
        vals = state()
        print(f"After toggle {i+1} ({expected}): {vals}")


if __name__ == "__main__":
    main()
