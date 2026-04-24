"""Inspect what the new BFS plans for navigate_to(31, 17) on
bug_bike_ramps_repel — and where in that plan the executor breaks.

Read-only: drives only memory reads + BFS calls. Does not press buttons.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.connection import get_client  # noqa: E402
from renegade_mcp.pathfinding import (  # noqa: E402
    _bfs_pathfind, _bfs_pathfind_3d, _build_multi_chunk_terrain,
    _build_multi_chunk_elevation,
)

from helpers import do_load_state  # noqa: E402


def main():
    emu = get_client()
    do_load_state(emu, "bug_bike_ramps_repel")
    emu.advance_frames(4)
    base = addresses.addr("PLAYER_POS_BASE")
    map_id = emu.read_memory(base, size="long")
    px = emu.read_memory(base + 8, size="long")
    py = emu.read_memory(base + 12, size="long")
    print(f"map_id={map_id} pos=({px},{py})")

    target_x, target_y = 31, 17
    multi = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
    if multi is None:
        print("multi-chunk terrain build failed")
        return
    terrain_info, ox, oy, w, h = multi
    elev = _build_multi_chunk_elevation(emu, map_id, terrain_info, ox, oy, w, h)
    npc_set: set = set()  # ignore NPCs for analysis

    sx, sy = px - ox, py - oy
    gx, gy = target_x - ox, target_y - oy
    print(f"local start=({sx},{sy}) goal=({gx},{gy}) grid {w}x{h} origin=({ox},{oy})")

    # 2D BFS first
    path_2d = _bfs_pathfind(terrain_info, npc_set, sx, sy, gx, gy, width=w, height=h)
    if path_2d:
        print(f"\n2D path ({len(path_2d)} steps): {path_2d}")
    else:
        print("\n2D path: None")

    # 3D BFS
    path_3d = _bfs_pathfind_3d(
        terrain_info, npc_set, elev,
        sx, sy, gx, gy, start_level=0, width=w, height=h,
    )
    if path_3d:
        print(f"\n3D path ({len(path_3d)} steps): {path_3d}")
    else:
        print("\n3D path: None")

    if path_3d:
        from renegade_mcp.nav_constants import (
            _DIR_DELTAS, BIKE_RAMP_BEHAVIORS, BIKE_SLOPE_BEHAVIORS,
            BIKE_RAMP_JUMP_TILES, BIKE_RAMP_RUNWAY_TILES,
        )
        # Dump row 17 around the ramp area
        print("\nRow 17 terrain (cols 5..32):")
        row_y = 17 - oy
        for x_local in range(5 - ox, 33 - ox):
            if 0 <= x_local < len(terrain_info[row_y]):
                _, beh = terrain_info[row_y][x_local]
                tag = ""
                if beh in BIKE_RAMP_BEHAVIORS:
                    tag = " RAMP_E" if beh == 0xD7 else " RAMP_other"
                elif beh in BIKE_SLOPE_BEHAVIORS:
                    tag = " SLOPE"
                print(f"  ({x_local + ox},17) beh=0x{beh & 0xFF:02x}{tag}")

        # Re-trace the BFS path PROPERLY — unfurl ramp jumps to their
        # landing. We mimic the BFS edge logic.
        cx, cy = sx, sy
        m = 0
        runway = BIKE_RAMP_RUNWAY_TILES
        print("\nRamp-aware trace:")
        for i, d in enumerate(path_3d):
            dx, dy = _DIR_DELTAS[d]
            nx, ny = cx + dx, cy + dy
            if not (0 <= ny < len(terrain_info) and 0 <= nx < len(terrain_info[0])):
                print(f"  [{i:>2}] {d} -> OUT OF BOUNDS")
                break
            _, beh = terrain_info[ny][nx]
            if beh in BIKE_RAMP_BEHAVIORS:
                # Ramp jump
                if m + 1 >= runway:
                    landing_x = cx + dx * BIKE_RAMP_JUMP_TILES
                    landing_y = cy + dy * BIKE_RAMP_JUMP_TILES
                    new_m = runway
                    kind = "FAR"
                else:
                    landing_x = cx + dx * (BIKE_RAMP_JUMP_TILES - 4)  # NEAR
                    landing_y = cy + dy * (BIKE_RAMP_JUMP_TILES - 4)
                    new_m = 1
                    kind = "NEAR"
                print(f"  [{i:>2}] {d:<5s} ({cx + ox},{cy + oy}) ramp@({nx + ox},{ny + oy}) "
                      f"m={m} -> {kind} landing ({landing_x + ox},{landing_y + oy}) m={new_m}")
                cx, cy = landing_x, landing_y
                m = new_m
            else:
                print(f"  [{i:>2}] {d:<5s} ({cx + ox},{cy + oy})->({nx + ox},{ny + oy}) "
                      f"walk beh=0x{beh & 0xFF:02x} m={m}->{min(m + 1, runway)}")
                cx, cy = nx, ny
                m = min(m + 1, runway)
        print(f"\nFinal pos: ({cx + ox}, {cy + oy})  expected ({target_x}, {target_y})")


if __name__ == "__main__":
    main()
