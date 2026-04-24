"""Dump BDHC elevation level assignments for Wayward Cave B1F tiles.

Answers: are (13, 9) and (23, 9) on the same BDHC level, or different ones?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE = "session32_wayward_b1f_ramp_slope_stairs"
PROBE_TILES = [
    (13, 9),  # player spawn — where nav to (7, 6) works
    (23, 9),  # east chamber — where nav to (7, 6) is rejected
    (7, 9),   # slope bottom
    (7, 8),   # slope top
    (7, 6),   # target that was reachable
    (10, 6),  # target that was rejected
    (16, 6),  # target that was rejected
    (33, 8),  # obj:3 Pokeball
]


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr, reset, detect_shift
    from renegade_mcp.pathfinding import (
        _build_multi_chunk_elevation,
        _build_multi_chunk_terrain,
    )

    emu.load_state(SAVE)
    emu.advance_frames(120)
    reset()
    detect_shift(emu)

    ppb = addr("PLAYER_POS_BASE")
    map_id = emu.read_memory(ppb, size="long")
    px = emu.read_memory(ppb + 8, size="long")
    py = emu.read_memory(ppb + 12, size="long")
    print(f"Player: map={map_id} ({px}, {py})")

    # Grab the multi-chunk terrain and build elevation.  Include all probe
    # targets so the terrain window covers them.
    mc_terrain = _build_multi_chunk_terrain(
        emu, map_id, px, py,
        target_x=PROBE_TILES[0][0], target_y=PROBE_TILES[0][1],
        extra_targets=PROBE_TILES[1:],
    )
    if mc_terrain is None:
        print("No multi-chunk terrain data.")
        return
    terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_terrain
    print(f"Terrain: origin=({grid_ox},{grid_oy}) size={grid_w}x{grid_h}")

    elev = _build_multi_chunk_elevation(
        emu, map_id, terrain_info, grid_ox, grid_oy, grid_w, grid_h,
    )
    if elev is None:
        print("No elevation (flat).")
        return

    print(f"Levels: {elev['levels']}")
    print(f"Ramps: {len(elev['ramps'])}")
    for r in elev["ramps"]:
        print(f"  ramp #{r['ramp_index']}: cols={r['col_range']} rows={r['row_range']} "
              f"{r['from_level']}→{r['to_level']} dir={r['direction']}")

    level_map = elev["level_map"]
    ramp_tiles = elev["ramp_tiles"]

    print("\nProbe tiles:")
    for (x, y) in PROBE_TILES:
        lvls = level_map.get((x, y))
        ramp = ramp_tiles.get((x, y))
        tag = f"levels={lvls}" if lvls is not None else "NO level_map entry"
        if ramp is not None:
            tag += f"  RAMP({ramp['from_level']}→{ramp['to_level']}, {ramp['direction']})"
        print(f"  ({x},{y}): {tag}")


if __name__ == "__main__":
    main()
