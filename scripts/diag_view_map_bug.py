"""Diagnostic for view_map false-unreachable bug in Wayward Cave.

Inspects the BFS pipeline at (73, 29) → shows multi-chunk bounds, elevation
status, the set of reachable tiles, and the shortest Manhattan-distance
unreachable POIs.
"""
from __future__ import annotations

from renegade_mcp import addresses
from renegade_mcp.connection import get_client
from renegade_mcp.map_state import (
    get_matrix_for_map,
    read_objects,
    read_player_state,
)
from renegade_mcp.pathfinding import (
    _bfs_reachable_3d,
    _build_multi_chunk_elevation,
    _build_multi_chunk_terrain,
    _height_to_level,
)


def main() -> None:
    emu = get_client()
    addresses.reset()
    addresses.detect_shift(emu)

    map_id, px, py, facing = read_player_state(emu)
    print(f"Player: map={map_id} at ({px},{py}) facing={facing}")

    mi = get_matrix_for_map(emu, map_id)
    if mi is None:
        print("no matrix")
        return
    matrix_id, mw, mh, _headers, terrain_ids = mi
    print(f"Matrix: id={matrix_id} size={mw}x{mh} chunks")

    # Same viewport logic as view_map: target is vp bottom-right
    # For a 15x15 viewport centered on player
    vp_x, vp_y, vp_w, vp_h = px - 7, py - 7, 15, 15
    target_x = vp_x + vp_w - 1
    target_y = vp_y + vp_h - 1
    print(f"Viewport target (br corner): ({target_x},{target_y})")

    mc = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
    if mc is None:
        print("no mc terrain")
        return
    mc_terrain, mc_ox, mc_oy, mc_w, mc_h = mc
    print(
        f"MC bounds: origin=({mc_ox},{mc_oy}) size={mc_w}x{mc_h} "
        f"→ covers x[{mc_ox},{mc_ox+mc_w}) y[{mc_oy},{mc_oy+mc_h})"
    )

    mc_elev = _build_multi_chunk_elevation(
        emu, map_id, mc_terrain, mc_ox, mc_oy, mc_w, mc_h,
    )
    print(f"MC elevation: {'present' if mc_elev else 'flat/none'}")

    # Inspect BDHC per loaded chunk
    from renegade_mcp.map_state import parse_bdhc
    print("\nPer-chunk BDHC plate detail:")
    for cy_ in range(mc_oy // 32, (mc_oy + mc_h) // 32):
        for cx_ in range(mc_ox // 32, (mc_ox + mc_w) // 32):
            lid = terrain_ids[cy_][cx_]
            if lid == 0xFFFF:
                continue
            bdhc = parse_bdhc(lid)
            if bdhc is None:
                continue
            print(f"  chunk ({cx_},{cy_}) land={lid}:")
            for i, pl in enumerate(bdhc["plates"]):
                p1 = bdhc["points"][pl["p1"]]
                p2 = bdhc["points"][pl["p2"]]
                nrm = bdhc["normals"][pl["normal"]]
                cnst = bdhc["constants"][pl["constant"]]
                # tile coords: bdhc coord = tile*16 - 256 approximately
                # tile = (bdhc + 256)/16
                tx1 = (min(p1[0], p2[0]) + 256) / 16
                tx2 = (max(p1[0], p2[0]) + 256) / 16
                tz1 = (min(p1[1], p2[1]) + 256) / 16
                tz2 = (max(p1[1], p2[1]) + 256) / 16
                gx1 = int(tx1) + cx_ * 32
                gx2 = int(tx2) + cx_ * 32
                gy1 = int(tz1) + cy_ * 32
                gy2 = int(tz2) + cy_ * 32
                print(
                    f"    plate {i}: bdhc=({p1[0]},{p1[1]})..({p2[0]},{p2[1]}) "
                    f"tile x[{gx1},{gx2}] y[{gy1},{gy2}] "
                    f"normal=({nrm[0]:.3f},{nrm[1]:.3f},{nrm[2]:.3f}) d={cnst}"
                )

    print("\nPer-chunk BDHC flat heights:")
    for cy in range(mc_oy // 32, (mc_oy + mc_h) // 32):
        for cx in range(mc_ox // 32, (mc_ox + mc_w) // 32):
            lid = terrain_ids[cy][cx]
            if lid == 0xFFFF:
                print(f"  chunk ({cx},{cy}): land=0xFFFF (empty)")
                continue
            bdhc = parse_bdhc(lid)
            if bdhc is None:
                print(f"  chunk ({cx},{cy}): land={lid} no BDHC")
                continue
            flats: set[int] = set()
            ramps = 0
            for plate in bdhc["plates"]:
                nx, ny_, nz = bdhc["normals"][plate["normal"]]
                if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny_) > 0.01:
                    d = bdhc["constants"][plate["constant"]]
                    flats.add(round(-d / ny_))
                elif abs(ny_) > 0.01:
                    ramps += 1
            print(
                f"  chunk ({cx},{cy}): land={lid} plates={len(bdhc['plates'])} "
                f"flats={sorted(flats)} ramps={ramps}"
            )

    objects = read_objects(emu)

    from renegade_mcp.map_state import read_player_height
    from renegade_mcp.nav_constants import is_follower_npc

    if mc_elev is not None:
        ph = read_player_height(emu)
        p_level = _height_to_level(ph, mc_elev, tile_x=px - mc_ox, tile_y=py - mc_oy)
        print(f"Player height={ph} → level={p_level}")
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
        reach_global = {(gx + mc_ox, gy + mc_oy): s for (gx, gy), s in reach.items()}
    else:
        print("Elevation absent — running 2D fallback over mc_bounds")
        from renegade_mcp.map_state import _bfs_flood_fill, _load_viewport_terrain
        flood_terrain = _load_viewport_terrain(
            terrain_ids, mw, mh, mc_ox, mc_oy, mc_w, mc_h,
        )
        npc_pos = {
            (o["x"] - mc_ox, o["y"] - mc_oy)
            for o in objects
            if o["index"] != 0 and not is_follower_npc(o)
        }
        reach2d = _bfs_flood_fill(
            flood_terrain, px - mc_ox, py - mc_oy,
            npc_pos, mc_w, mc_h,
            max_steps=500,
        )
        reach_global = {(lx + mc_ox, ly + mc_oy): s for (lx, ly), s in reach2d.items()}

    print(f"3D BFS: {len(reach_global)} reachable tiles")
    if reach_global:
        xs = sorted({x for x, _ in reach_global})
        ys = sorted({y for _, y in reach_global})
        print(f"  x range: {xs[0]}..{xs[-1]}   y range: {ys[0]}..{ys[-1]}")
        # Sample: shape of the reachable region by rows
        for row in range(min(ys), max(ys) + 1):
            cells = sorted(x for (x, y) in reach_global if y == row)
            if cells:
                # Compress into runs
                runs = []
                a = cells[0]; b = a
                for v in cells[1:]:
                    if v == b + 1:
                        b = v
                    else:
                        runs.append((a, b))
                        a = v; b = v
                runs.append((a, b))
                run_s = ",".join(f"{a}-{b}" if a != b else f"{a}" for a, b in runs)
                print(f"  y={row}: {run_s}")

    # Dump raw terrain around the SW exit warp area
    print("\nTerrain x[38,68) y[48,60) (P=passable, X=blocked, numeric=behavior byte):")
    from renegade_mcp.map_state import _load_viewport_terrain
    raw = _load_viewport_terrain(terrain_ids, mw, mh, 38, 10, 56, 54)
    # raw is u16 matrix; show passability flag + behavior
    from renegade_mcp.nav_constants import (
        TERRAIN_OBSTACLES,
        WARP_PASSABLE,
        LEDGE_DIRECTIONS,
    )
    print("      " + "".join(f"{(38+i)%10}" for i in range(56)))
    for row in range(54):
        gy = 10 + row
        line = f" y={gy:2d} "
        for col in range(56):
            gx = 38 + col
            val = raw[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            passable = (
                (not is_blocked
                 or behavior in WARP_PASSABLE
                 or behavior in LEDGE_DIRECTIONS)
                and behavior not in TERRAIN_OBSTACLES
            )
            in_reach = (gx, gy) in reach_global
            if gx == px and gy == py:
                line += "P"
            elif in_reach:
                line += "."
            elif passable:
                line += "o"  # passable but NOT reached
            else:
                line += "#"
        print(line)

    # Histogram of unique behavior bytes in passable tiles (whole mc)
    from collections import Counter
    behavior_count: Counter[int] = Counter()
    for row in range(mc_h):
        for col in range(mc_w):
            val = raw[row][col] if False else None
    # Just use mc_terrain directly — flag per tile
    from renegade_mcp.map_state import _load_viewport_terrain as _lvt
    raw_all = _lvt(terrain_ids, mw, mh, mc_ox, mc_oy, mc_w, mc_h)
    for row in range(mc_h):
        for col in range(mc_w):
            val = raw_all[row][col]
            behavior = val & 0x00FF
            is_blocked = (val & 0x8000) != 0
            behavior_count[(behavior, is_blocked)] += 1
    print("\nBehavior histogram across full mc region (behavior, blocked_bit): count")
    for (b, blk), c in sorted(behavior_count.items()):
        print(f"  0x{b:02X} blocked={blk}: {c}")

    # Focus: look at tiles in the "unreached but passable" south corridor
    # and see what behaviors they have
    print("\nBehavior bytes at (gx=41 col y in 48..56):")
    for gy in range(48, 57):
        val = raw_all[gy - mc_oy][41 - mc_ox]
        b = val & 0x00FF
        blk = (val & 0x8000) != 0
        print(f"  (41, {gy}): behavior=0x{b:02X} blocked={blk}")

    # Check specific POIs of interest
    targets = [
        ("warp to 206 (41,53)", 41, 53),
        ("warp to 206 (30,55)", 30, 55),
        ("warp (28,54)", 28, 54),
        ("pokeball (57,53)", 57, 53),
        ("warp (55,54)", 55, 54),
        ("hiker (20,38)", 20, 38),
        ("hiker (17,38)", 17, 38),
    ]
    print("\nTarget reachability:")
    for name, tx, ty in targets:
        in_mc = mc_ox <= tx < mc_ox + mc_w and mc_oy <= ty < mc_oy + mc_h
        passable = None
        if in_mc:
            passable, behavior = mc_terrain[ty - mc_oy][tx - mc_ox]
        reached = (tx, ty) in reach_global
        s = reach_global.get((tx, ty))
        print(
            f"  {name}: in_mc={in_mc} passable={passable} "
            f"reached={reached} steps={s}"
        )


if __name__ == "__main__":
    main()
