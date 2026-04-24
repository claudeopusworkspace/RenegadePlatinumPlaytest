"""BUG-046: write OPPOSITE value to each gear candidate, see which leads.

If writing to addr X flips addr Y as well within ~120 frames, X is the
authoritative leader (or closer to it). Addresses that get reverted when
written are derived mirrors.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE_STATE = "bug_slope_ascent_mount_thrash"

CANDIDATES = [
    ("BIKE",  0x021bf6ac),
    ("PD?",   0x021ccdb4),
    ("FOW",   0x0227f4bc),
]

SETTLE = 120


def read_all(emu):
    return {name: emu.read_memory(a, size="byte") for name, a in CANDIDATES}


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE_STATE)
    emu.advance_frames(30)
    if not emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"):
        use_item(emu, "Bicycle")
        emu.advance_frames(60)

    for write_name, write_addr in CANDIDATES:
        emu.load_state(SAVE_STATE)
        emu.advance_frames(30)
        if not emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"):
            use_item(emu, "Bicycle")
            emu.advance_frames(60)

        initial = read_all(emu)
        cur = initial[write_name]
        flipped = 1 - cur
        print(f"\n=== Fresh-mount. {write_name}={cur}. Writing {flipped} to {write_name} (0x{write_addr:08x}) ===")
        print(f"  initial: {initial}")
        emu.write_memory(write_addr, value=flipped, size="byte")
        for t in (1, 10, 30, 60, 120, 240):
            if t == 1:
                emu.advance_frames(1)
            else:
                # Advance to the target t
                pass
        # Poll at several points
        intervals = [1, 10, 30, 60, 120, 240]
        advanced = 0
        for target in intervals:
            emu.advance_frames(target - advanced)
            advanced = target
            vals = read_all(emu)
            print(f"  after {target:3d}f: {vals}")


if __name__ == "__main__":
    main()
