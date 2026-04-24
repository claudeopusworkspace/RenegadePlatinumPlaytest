"""BUG-046 spike: find the authoritative bike-gear memory address.

Decomp says `playerData->cyclingGear` (u16 at PlayerData offset 0) is what
the engine reads for gear. Our `BIKE_GEAR_STATE_ADDR = 0x021BF6AC` is NOT
backed by this field — our `_set_bike_gear` reads this byte and short-
circuits if it already matches target, but the real gear state can be
different.

Strategy: snapshot a wide memory range, B-press-toggle the gear many times,
find addresses that alternate every toggle between exactly two values
(0 and 1 for a gear byte).

Run: .venv/bin/python3 scripts/spike_find_authoritative_gear.py
Requires bike-mounted save state (bug_slope_ascent_mount_thrash works).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


# Regions to scan. DS main RAM is 0x02000000-0x023FFFFF (4 MB).
# Picking narrower windows around known struct areas for speed.
REGIONS = [
    # Save block area + PlayerAvatar region
    (0x0227E000, 0x00004000),   # 16 KB around SAVE_BLOCK_BASE + PLAYER_POS_BASE
    # BIKE_GEAR_STATE_ADDR neighborhood (ARM9 BSS)
    (0x021BE000, 0x00002000),   # 8 KB around BIKE_GEAR_STATE_ADDR
    # Heap-allocated structs often live here
    (0x021C0000, 0x00010000),   # 64 KB upper ARM9 heap
]

SAVE_STATE = "bug_slope_ascent_mount_thrash"
NUM_TOGGLES = 30
TOGGLE_WAIT = 30  # frames between B-press and readback
B_PRESS_FRAMES = 8


def snapshot_region(emu, base: int, size: int) -> bytes:
    return emu.read_memory_block(base, size)


def find_candidates(snapshots: list[dict[int, bytes]]) -> list[tuple[int, list[int]]]:
    """Return addresses where the byte toggled between exactly 2 distinct
    values across ALL snapshots (i.e. value[i] != value[i-1] for all i > 0,
    and len(set(values)) == 2)."""
    if len(snapshots) < 2:
        return []
    candidates = []
    for base in snapshots[0]:
        size = len(snapshots[0][base])
        blocks = [snap[base] for snap in snapshots]
        for off in range(size):
            values = [b[off] for b in blocks]
            uniq = set(values)
            if len(uniq) != 2:
                continue
            # Must alternate every step — each adjacent pair differs.
            alternates = all(values[i] != values[i - 1] for i in range(1, len(values)))
            if alternates:
                candidates.append((base + off, values))
    return candidates


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr, BIKE_GEAR_STATE_ADDR
    from renegade_mcp.use_item import use_item

    # Load the save. Ensure we're on the bike (save state has us walking, but
    # the save captures a state where outer auto-mount has fired in prior
    # tests; to be deterministic, we manually mount.
    emu.load_state(SAVE_STATE)
    emu.advance_frames(30)

    # Ensure cycling — if not, mount via use_item.
    cycling_addr = addr("CYCLING_GEAR_ADDR")
    if not emu.read_memory(cycling_addr, size="short"):
        print("Not cycling — mounting bicycle.")
        use_item(emu, "Bicycle")
        emu.advance_frames(60)
    else:
        print("Already cycling.")

    # Capture gear state reads from our known byte for reference.
    known = emu.read_memory(BIKE_GEAR_STATE_ADDR, size="byte")
    print(f"Known BIKE_GEAR_STATE_ADDR (0x{BIKE_GEAR_STATE_ADDR:08x}) = {known}")

    snapshots: list[dict[int, bytes]] = []

    def snap():
        return {base: snapshot_region(emu, base, size) for base, size in REGIONS}

    # Initial snapshot (before any toggles)
    snapshots.append(snap())
    print(f"Snapshot 0 captured. Starting {NUM_TOGGLES} B-press toggles...")

    for i in range(NUM_TOGGLES):
        emu.press_buttons(["b"], frames=B_PRESS_FRAMES)
        emu.advance_frames(TOGGLE_WAIT)
        snapshots.append(snap())
        gear_byte = emu.read_memory(BIKE_GEAR_STATE_ADDR, size="byte")
        print(f"  Toggle {i+1}/{NUM_TOGGLES}: BIKE_GEAR_STATE_ADDR byte = {gear_byte}")

    # Analyze
    print("\n=== Finding addresses that alternate every toggle ===")
    candidates = find_candidates(snapshots)
    print(f"Total candidates: {len(candidates)}")

    # Sort by distance from BIKE_GEAR_STATE_ADDR for readability
    candidates.sort(key=lambda c: abs(c[0] - BIKE_GEAR_STATE_ADDR))

    # Report
    print(f"{'ADDR':12s}  {'Δfrom_known':12s}  {'first_6_values':20s}  {'all_values_uniq'}")
    for addr_v, values in candidates[:40]:
        delta = addr_v - BIKE_GEAR_STATE_ADDR
        uniq = sorted(set(values))
        first6 = "".join(str(v) for v in values[:6])
        print(f"0x{addr_v:08x}  {delta:+13d}  {first6:20s}  {uniq}")

    print(f"\n(Showing top 40 of {len(candidates)} candidates)")


if __name__ == "__main__":
    main()
