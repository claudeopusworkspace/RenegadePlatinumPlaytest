"""Compare _bfs_reachable_3d output across Wayward B1F save states.

Loads each candidate state, runs the same 3D BFS view_map uses, then prints
whether each landmark tile (slope ends, ramp landings, warp:0) is in the
reach set, and at what step distance and level.

Run against the LIVE bridge — this loads save states into memory only.
"""
from __future__ import annotations

import sys
from typing import Any

from renegade_mcp import addresses
from renegade_mcp.connection import get_client
from renegade_mcp.map_state import (
    get_matrix_for_map,
    read_objects,
    read_player_height,
    read_player_state,
    read_warps_from_rom,
)
from renegade_mcp.nav_constants import is_follower_npc
from renegade_mcp.pathfinding import (
    _bfs_reachable_3d,
    _build_multi_chunk_elevation,
    _build_multi_chunk_terrain,
    _height_to_level,
)


STATES = [
    "session31_wayward_cave_bike_ramps",
    "session32_wayward_b1f_ramp_slope_stairs",
    "session42_wayward_b1f_first_ramp_approach",
    "session47_wayward_b1f_post_obj3_rare_candy",
    "bug048_wayward_b1f_east_chamber_via_chain_through",
]

# Tiles of interest along the climb from (7, 22) to (43, 38)
LANDMARKS = [
    ("player",            None, None),  # filled per state
    ("(7,22) lower mid",  7,  22),
    ("(7,18) mid corr",   7,  18),
    ("(7,10) just S of slope", 7, 10),
    ("(7,9) slope_bottom", 7,  9),
    ("(7,8) slope_top",    7,  8),
    ("(7,7) above slope",  7,  7),
    ("(13,9) mid chamber", 13, 9),
    ("(25,6) ramp approach row", 25, 6),
    ("(33,7) east of obj3",33, 7),
    ("(42,6) chain landing", 42, 6),
    ("warp:0 (43,38)",    43, 38),
]


def probe(emu) -> None:
    addresses.reset()
    addresses.detect_shift(emu)
    map_id, px, py, facing = read_player_state(emu)
    print(f"  Player: map={map_id} ({px},{py}) facing={facing}")

    mi = get_matrix_for_map(emu, map_id)
    if mi is None:
        print("  no matrix")
        return
    _matrix_id, mw, mh, _hdrs, terrain_ids = mi

    objects = read_objects(emu)
    warps = read_warps_from_rom(emu, map_id)
    poi_points = [(o["x"], o["y"]) for o in objects] + [(w["x"], w["y"]) for w in warps]

    vp_x, vp_y, vp_w, vp_h = px - 7, py - 7, 15, 15
    mc = _build_multi_chunk_terrain(
        emu, map_id, px, py,
        vp_x + vp_w - 1, vp_y + vp_h - 1,
        extra_targets=poi_points,
    )
    if mc is None:
        print("  no mc terrain")
        return
    mc_terrain, mc_ox, mc_oy, mc_w, mc_h = mc
    print(f"  MC bounds: origin=({mc_ox},{mc_oy}) size={mc_w}x{mc_h} "
          f"covers x[{mc_ox},{mc_ox+mc_w}) y[{mc_oy},{mc_oy+mc_h})")

    mc_elev = _build_multi_chunk_elevation(emu, map_id, mc_terrain, mc_ox, mc_oy, mc_w, mc_h)
    if mc_elev is None:
        print("  No elevation; 2D fallback")
        return

    ph = read_player_height(emu)
    p_level = _height_to_level(ph, mc_elev, tile_x=px - mc_ox, tile_y=py - mc_oy)
    print(f"  player_height={ph} → level={p_level}")

    npc_pos = {
        (o["x"] - mc_ox, o["y"] - mc_oy)
        for o in objects
        if o["index"] != 0 and not is_follower_npc(o)
    }

    reach = _bfs_reachable_3d(
        mc_terrain, npc_pos, mc_elev,
        px - mc_ox, py - mc_oy, p_level,
        width=mc_w, height=mc_h,
        max_steps=500,
    )
    # 3D-keyed reach (x, y, level) → steps, in MC-local coords. Convert to global.
    reach_3d_global: dict[tuple[int, int, int], int] = {
        (lx + mc_ox, ly + mc_oy, lv): s for (lx, ly, lv), s in reach.items()
    }
    # Per-tile any-level reach (for whether view_map exposes it)
    flat: dict[tuple[int, int], tuple[int, int]] = {}
    for (gx, gy, lv), s in reach_3d_global.items():
        prev = flat.get((gx, gy))
        if prev is None or s < prev[0]:
            flat[(gx, gy)] = (s, lv)
    print(f"  reach: {len(flat)} tiles (3D entries: {len(reach_3d_global)})")

    # Per-level summary
    by_level: dict[int, int] = {}
    for (_x, _y, lv) in reach_3d_global:
        by_level[lv] = by_level.get(lv, 0) + 1
    print(f"  per-level reach counts: {sorted(by_level.items())}")

    # Probe elevation/level data along the (7, y=8..22) column
    print("  Column x=7 elevation (BDHC level_map):")
    level_map = mc_elev["level_map"]
    ramp_tiles = mc_elev["ramp_tiles"]
    height_by_level = {lv["level"]: lv["height"] for lv in mc_elev["levels"]}
    for ly in range(7, 23):
        key = (7 - mc_ox, ly - mc_oy)
        lvls = level_map.get(key)
        ri = ramp_tiles.get(key)
        passable, behavior = mc_terrain[ly - mc_oy][7 - mc_ox]
        per_lvl = sorted(
            (lv, s) for (gx, gy, lv), s in reach_3d_global.items()
            if gx == 7 and gy == ly
        )
        h_str = f"levels={lvls} ramp={ri}" if ri else f"levels={lvls}"
        print(f"    (7,{ly}) beh=0x{behavior:02X} pass={passable} {h_str} reach={per_lvl}")
    print(f"  height_by_level: {height_by_level}")

    # 2D-flat ASCII grid of level reach + walls
    GRID_X0, GRID_X1 = 0, 50
    GRID_Y0, GRID_Y1 = 0, 45
    print(f"  Reach grid (cols {GRID_X0}-{GRID_X1-1}, rows {GRID_Y0}-{GRID_Y1-1}):  '.'=L0  '~'=L2  '+'=L1  'B'=both  '#'=wall  '·'=passable_unreached")
    for ly in range(GRID_Y0, GRID_Y1):
        line = f"    y={ly:2d} "
        for lx in range(GRID_X0, GRID_X1):
            in_mc = mc_ox <= lx < mc_ox + mc_w and mc_oy <= ly < mc_oy + mc_h
            if not in_mc:
                line += "?"
                continue
            passable, _ = mc_terrain[ly - mc_oy][lx - mc_ox]
            in0 = (lx, ly, 0) in reach_3d_global
            in2 = (lx, ly, 2) in reach_3d_global
            if not passable:
                ch = "#"
            elif lx == px and ly == py:
                ch = "P"
            elif in0 and in2:
                ch = "B"
            elif in0:
                ch = "."
            elif in2:
                ch = "~"
            else:
                ch = "·"
            line += ch
        print(line)
    print("  Landmarks:")
    for name, lx, ly in LANDMARKS:
        if name == "player":
            lx, ly = px, py
        if lx is None:
            continue
        per_level = sorted(
            (lv, s) for (gx, gy, lv), s in reach_3d_global.items()
            if gx == lx and gy == ly
        )
        in_mc = mc_ox <= lx < mc_ox + mc_w and mc_oy <= ly < mc_oy + mc_h
        passable = None
        behavior = None
        if in_mc:
            passable, behavior = mc_terrain[ly - mc_oy][lx - mc_ox]
        flag = "  "
        if name == "player":
            flag = "*P"
        elif lx == 43 and ly == 38:
            flag = "*W"
        if per_level:
            print(f"    {flag} {name:30s} ({lx},{ly}) passable={passable!s:5s} beh=0x{(behavior or 0):02X} reach={per_level}")
        else:
            print(f"    {flag} {name:30s} ({lx},{ly}) passable={passable!s:5s} beh=0x{(behavior or 0):02X} UNREACHED")


def main() -> None:
    emu = get_client()

    state = sys.argv[1] if len(sys.argv) > 1 else None
    targets = [state] if state else STATES

    from pathlib import Path
    savestates_dir = Path("/workspace/RenegadePlatinumPlaytest/savestates")
    for s in targets:
        print(f"\n=== {s} ===")
        ok = emu.load_state(str(savestates_dir / f"{s}.mst"))
        if not ok:
            print(f"  load_state failed for {s}")
            continue
        try:
            probe(emu)
        except Exception as exc:
            print(f"  ERROR: {exc!r}")


if __name__ == "__main__":
    main()
