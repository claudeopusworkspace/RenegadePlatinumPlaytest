"""Verify fix hypothesis: load the FULL matrix (3x2) instead of the
viewport-driven 2x2 region, and re-run BFS. If the warp at (41,53) becomes
reachable, the root cause is view_map's chunk-bounding logic, not cross-map
topology.
"""
from __future__ import annotations

from renegade_mcp import addresses
from renegade_mcp.connection import get_client
from renegade_mcp.map_state import (
    _bfs_flood_fill,
    _load_viewport_terrain,
    get_matrix_for_map,
    read_objects,
    read_player_state,
)
from renegade_mcp.nav_constants import is_follower_npc


def main() -> None:
    emu = get_client()
    addresses.reset()
    addresses.detect_shift(emu)

    map_id, px, py, _facing = read_player_state(emu)
    mi = get_matrix_for_map(emu, map_id)
    assert mi is not None
    _mid, mw, mh, _hdrs, terrain_ids = mi
    print(f"Matrix: {mw}x{mh} chunks → full extent x[0,{mw*32}) y[0,{mh*32})")

    # Load FULL matrix — all 3x2 = 96x64 tiles
    full_terrain = _load_viewport_terrain(terrain_ids, mw, mh, 0, 0, mw * 32, mh * 32)
    objects = read_objects(emu)
    npc_pos = {
        (o["x"], o["y"])
        for o in objects
        if o["index"] != 0 and not is_follower_npc(o)
    }

    reach = _bfs_flood_fill(
        full_terrain, px, py, npc_pos,
        mw * 32, mh * 32, max_steps=500,
    )
    print(f"2D flood over full matrix: {len(reach)} tiles reachable")

    targets = [
        ("warp:1 (41,53)", 41, 53),
        ("warp:0 (30,55)", 30, 55),
        ("warp:2 (28,54)", 28, 54),
        ("warp:3 (55,54)", 55, 54),
        ("obj:1 Pokeball (57,53)", 57, 53),
        ("Hiker (20,38)", 20, 38),
        ("Hiker (17,38)", 17, 38),
        ("Youngster (5,42)", 5, 42),
        ("Camper (2,14)", 2, 14),
        ("Picnicker (5,14)", 5, 14),
        ("Lass (2,42)", 2, 42),
    ]
    print("\nPOI reachability with full-matrix flood:")
    for name, tx, ty in targets:
        s = reach.get((tx, ty))
        mark = "✓" if s is not None else "✗"
        # Also check adjacency (interaction tile may be adjacent)
        adj = [
            (tx + dx, ty + dy, lbl)
            for dx, dy, lbl in [(0, -1, "N"), (0, 1, "S"), (-1, 0, "W"), (1, 0, "E")]
        ]
        adj_reached = [
            f"{lbl}={reach[(ax, ay)]}"
            for ax, ay, lbl in adj if (ax, ay) in reach
        ]
        print(
            f"  {mark} {name}: steps={s}  adj_reached=[{', '.join(adj_reached)}]"
        )


if __name__ == "__main__":
    main()
