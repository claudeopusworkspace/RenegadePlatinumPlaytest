"""BUG-046 follow-up: find the authoritative cycling (on-bike) memory address.

Our `CYCLING_GEAR_ADDR = PLAYER_POS_BASE + 0x90` was observed to read 0 while
the player was visibly on the bike (manual inspection + use_item tool
confirmed mounted state). Same failure pattern as the gear byte — derived
mirror rather than authoritative.

Scan memory, toggle bike on/off via use_item, find addresses that flip
between 2 values every toggle consistently.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


REGIONS = [
    (0x0227E000, 0x00004000),   # 16 KB around SAVE_BLOCK_BASE + PLAYER_POS_BASE
    (0x021C0000, 0x00020000),   # 128 KB ARM9 heap (we found FOW candidates here)
]

SAVE_STATE = "route207_at_bike_slope_bottom"  # starts on bike
NUM_TOGGLES = 15
SETTLE = 60


def snap(emu):
    return {b: emu.read_memory_block(b, s) for b, s in REGIONS}


def find_candidates(snaps):
    if len(snaps) < 2:
        return []
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

    emu.load_state(SAVE_STATE)
    emu.advance_frames(60)
    # Dismount to start in a known state (on foot)
    r = use_item(emu, "Bicycle")
    print(f"After initial dismount: {r.get('formatted')}")
    emu.advance_frames(SETTLE)

    # Verify we're on foot (use_item's own bike toggle reports state)
    snaps = [snap(emu)]
    print(f"Snapshot 0 captured. Running {NUM_TOGGLES} mount/dismount toggles...")

    for i in range(NUM_TOGGLES):
        r = use_item(emu, "Bicycle")
        emu.advance_frames(SETTLE)
        snaps.append(snap(emu))
        print(f"  Toggle {i+1}: {r.get('formatted')}")

    candidates = find_candidates(snaps)
    print(f"\nTotal candidates: {len(candidates)}")
    candidates.sort(key=lambda c: abs(c[0] - addr("PLAYER_POS_BASE")))

    for addr_v, values in candidates[:30]:
        delta = addr_v - addr("PLAYER_POS_BASE")
        uniq = sorted(set(values))
        first = "".join(str(v) for v in values[:8])
        print(f"  0x{addr_v:08x}  +{delta:5d}  {first:18s}  {uniq}")


if __name__ == "__main__":
    main()
