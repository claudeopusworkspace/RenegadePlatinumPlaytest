"""Scan for the gear toggle address in the E4 save specifically (different heap shift).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE = "bug_slope_ascent_mount_thrash"
REGIONS = [(0x0227E000, 0x00004000)]
TOGGLES = 15


def snap(emu):
    return {b: emu.read_memory_block(b, s) for b, s in REGIONS}


def find(snaps):
    out = []
    for base in snaps[0]:
        size = len(snaps[0][base])
        for off in range(size):
            values = [s[base][off] for s in snaps]
            uniq = set(values)
            if len(uniq) != 2:
                continue
            if all(values[i] != values[i - 1] for i in range(1, len(values))):
                out.append((base + off, values))
    return out


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE)
    emu.advance_frames(120)

    ppb = addr("PLAYER_POS_BASE")
    print(f"PPB (shifted): 0x{ppb:08x}")

    # Ensure on bike
    r = use_item(emu, "Bicycle")
    emu.advance_frames(60)
    if not bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")):
        r = use_item(emu, "Bicycle")
        emu.advance_frames(60)

    snaps = [snap(emu)]
    for i in range(TOGGLES):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(45)
        snaps.append(snap(emu))

    candidates = find(snaps)
    print(f"Candidates that 0/1 toggle: ", end="")
    only_01 = [(a, v) for (a, v) in candidates if set(v) == {0, 1}]
    print(len(only_01))
    for addr_v, values in sorted(only_01, key=lambda c: abs(c[0] - ppb)):
        delta = addr_v - ppb
        print(f"  0x{addr_v:08x}  PPB+{delta:+4d}  {''.join(str(v) for v in values[:8])}")


if __name__ == "__main__":
    main()
