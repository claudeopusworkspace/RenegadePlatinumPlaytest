"""Dump a full ASCII map of the current room to a text file, labeling each
tile with its BFS-reach status from the current emulator state.

Args:
  argv[1] (optional): save state name to load before dumping.
  argv[2] (optional): output path. Defaults to logs/<map_id>_reach_<state>.txt

Tile glyphs combine terrain category + reach status. Lowercase = reached,
uppercase = passable but BFS did NOT reach.

  @  player
  #  wall / impassable
  .  reached level 0 only
  ~  reached level 2 only
  +  reached level 1 only
  B  reached on multiple levels (e.g. 0+2 ramp tile)
  o  passable but NOT reached  <-- BFS gaps

Special-terrain glyphs (pair: reached / unreached):
  s / S    bike slope (0xD9 top, 0xDA bottom)   — going UP gated by 4-tile runway
  r / R    bike ramp east  (0xD7)
  l / L    bike ramp west  (0xD8)
  v / V    ledge south     (0x3B)
  n / N    bike bridge body / bridge start
  w / W    warp tile

After the grid, interactibles are listed with their interaction-tile reach.
"""
from __future__ import annotations

import sys
from pathlib import Path

from renegade_mcp import addresses
from renegade_mcp.connection import get_client
from renegade_mcp.map_state import (
    get_matrix_for_map,
    read_objects,
    read_player_height,
    read_player_state,
    read_warps_from_rom,
)
from renegade_mcp.nav_constants import (
    BIKE_RAMP_BEHAVIORS,
    BIKE_SLOPE_BEHAVIORS,
    LEDGE_DIRECTIONS,
    WARP_PASSABLE,
    is_follower_npc,
)
from renegade_mcp.pathfinding import (
    _bfs_reachable_3d,
    _build_multi_chunk_elevation,
    _build_multi_chunk_terrain,
    _height_to_level,
)


# (reached_glyph, unreached_glyph) per behavior. None means "fall through to
# generic floor / level coding".
def _special_glyph(behavior: int) -> tuple[str, str] | None:
    if behavior in BIKE_SLOPE_BEHAVIORS:
        return ("s", "S")
    if behavior == 0xD7:
        return ("r", "R")
    if behavior == 0xD8:
        return ("l", "L")
    if behavior in LEDGE_DIRECTIONS:
        d = LEDGE_DIRECTIONS[behavior]
        if d == "down":
            return ("v", "V")
        if d == "up":
            return ("^", "^")
        if d == "left":
            return ("<", "<")
        if d == "right":
            return (">", ">")
    if behavior == 0x70 or behavior in (0x76, 0x77, 0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7D):
        return ("n", "N")
    if behavior in WARP_PASSABLE:
        return ("w", "W")
    return None


def main() -> None:
    state_name = sys.argv[1] if len(sys.argv) > 1 else None
    out_path_arg = sys.argv[2] if len(sys.argv) > 2 else None

    emu = get_client()
    if state_name:
        savestates_dir = Path("/workspace/RenegadePlatinumPlaytest/savestates")
        ok = emu.load_state(str(savestates_dir / f"{state_name}.mst"))
        if not ok:
            print(f"load_state failed for {state_name}", file=sys.stderr)
            sys.exit(1)

    addresses.reset()
    addresses.detect_shift(emu)

    map_id, px, py, facing = read_player_state(emu)
    print(f"Player: map={map_id} ({px},{py}) facing={facing}")

    mi = get_matrix_for_map(emu, map_id)
    if mi is None:
        print("no matrix")
        sys.exit(1)
    _matrix_id, mw, mh, _hd, terrain_ids = mi

    objects = read_objects(emu)
    warps = read_warps_from_rom(emu, map_id)
    poi_points = (
        [(o["x"], o["y"]) for o in objects]
        + [(w["x"], w["y"]) for w in warps]
    )

    vp_x, vp_y, vp_w, vp_h = px - 7, py - 7, 15, 15
    mc = _build_multi_chunk_terrain(
        emu, map_id, px, py,
        vp_x + vp_w - 1, vp_y + vp_h - 1,
        extra_targets=poi_points,
    )
    if mc is None:
        print("no mc terrain")
        sys.exit(1)
    mc_terrain, mc_ox, mc_oy, mc_w, mc_h = mc

    mc_elev = _build_multi_chunk_elevation(
        emu, map_id, mc_terrain, mc_ox, mc_oy, mc_w, mc_h,
    )
    if mc_elev is None:
        print("no elevation; abort", file=sys.stderr)
        sys.exit(1)

    ph = read_player_height(emu)
    p_level = _height_to_level(
        ph, mc_elev, tile_x=px - mc_ox, tile_y=py - mc_oy,
    )
    height_by_level = {lv["level"]: lv["height"] for lv in mc_elev["levels"]}

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
    reach_3d_global: dict[tuple[int, int, int], int] = {
        (lx + mc_ox, ly + mc_oy, lv): s for (lx, ly, lv), s in reach.items()
    }

    from renegade_mcp.map_terrain import CHUNK_SIZE as _CHUNK
    def _chunk_is_oob(gx: int, gy: int) -> bool:
        cx = gx // _CHUNK
        cy = gy // _CHUNK
        if not (0 <= cy < len(terrain_ids) and 0 <= cx < len(terrain_ids[0])):
            return True
        return terrain_ids[cy][cx] == 0xFFFF

    # Trim grid extent to in-bounds chunks only
    in_chunks_x = [
        cx for cx in range(mc_ox // _CHUNK, (mc_ox + mc_w) // _CHUNK)
        if any(
            terrain_ids[cy][cx] != 0xFFFF
            for cy in range(mc_oy // _CHUNK, (mc_oy + mc_h) // _CHUNK)
        )
    ]
    in_chunks_y = [
        cy for cy in range(mc_oy // _CHUNK, (mc_oy + mc_h) // _CHUNK)
        if any(
            terrain_ids[cy][cx] != 0xFFFF
            for cx in range(mc_ox // _CHUNK, (mc_ox + mc_w) // _CHUNK)
        )
    ]
    if in_chunks_x and in_chunks_y:
        grid_x0 = in_chunks_x[0] * _CHUNK
        grid_x1 = (in_chunks_x[-1] + 1) * _CHUNK
        grid_y0 = in_chunks_y[0] * _CHUNK
        grid_y1 = (in_chunks_y[-1] + 1) * _CHUNK
    else:
        grid_x0, grid_x1 = mc_ox, mc_ox + mc_w
        grid_y0, grid_y1 = mc_oy, mc_oy + mc_h

    def reach_levels(gx: int, gy: int) -> tuple[bool, bool, bool]:
        return (
            (gx, gy, 0) in reach_3d_global,
            (gx, gy, 1) in reach_3d_global,
            (gx, gy, 2) in reach_3d_global,
        )

    def cell(gx: int, gy: int) -> str:
        if _chunk_is_oob(gx, gy):
            return " "
        if gx == px and gy == py:
            return "@"
        passable, behavior = mc_terrain[gy - mc_oy][gx - mc_ox]
        # Special-terrain glyphs first — bike ramps + slopes have the wall
        # bit set in raw terrain (they're "obstacle"-class) but BFS can
        # traverse them via runway / direction rules. Render as their glyph,
        # not as walls.
        l0, l1, l2 = reach_levels(gx, gy)
        any_reach = l0 or l1 or l2
        sg = _special_glyph(behavior)
        if sg is not None:
            return sg[0] if any_reach else sg[1]
        if not passable:
            return "#"
        # plain floor → level reach indicator
        if not any_reach:
            return "o"
        if l0 and l2:
            return "B"
        if l0 and l1:
            return "B"
        if l1 and l2:
            return "B"
        if l0:
            return "."
        if l2:
            return "~"
        return "+"

    # Trim grid extent to the bounding box of "interesting" tiles: walls or
    # any reached (x,y,*) entry. Empty cave-floor cells outside this box are
    # padding from the chunk loader and clutter the visualization.
    interesting_xs: list[int] = []
    interesting_ys: list[int] = []
    for gy in range(grid_y0, grid_y1):
        for gx in range(grid_x0, grid_x1):
            if not (mc_oy <= gy < mc_oy + mc_h and mc_ox <= gx < mc_ox + mc_w):
                continue
            passable, _ = mc_terrain[gy - mc_oy][gx - mc_ox]
            reached = any((gx, gy, lv) in reach_3d_global for lv in (0, 1, 2))
            if (not passable) or reached or (gx == px and gy == py):
                interesting_xs.append(gx)
                interesting_ys.append(gy)
    if interesting_xs and interesting_ys:
        # 2-tile pad to keep context around the trimmed bbox
        grid_x0 = max(grid_x0, min(interesting_xs) - 2)
        grid_x1 = min(grid_x1, max(interesting_xs) + 3)
        grid_y0 = max(grid_y0, min(interesting_ys) - 2)
        grid_y1 = min(grid_y1, max(interesting_ys) + 3)

    counts_by_level: dict[int, int] = {}
    for (_x, _y, lv) in reach_3d_global:
        counts_by_level[lv] = counts_by_level.get(lv, 0) + 1

    lines: list[str] = []
    lines.append(f"=== Map {map_id} reach dump ===")
    if state_name:
        lines.append(f"State: {state_name}")
    lines.append(
        f"Player: ({px}, {py}) facing={facing}  height={ph}  start_level={p_level}"
    )
    lines.append(f"BDHC heights by level: {height_by_level}")
    lines.append(
        f"BFS reach: {len(reach_3d_global)} (x,y,level) entries; "
        f"per-level {sorted(counts_by_level.items())}"
    )
    lines.append(f"Grid extent: x[{grid_x0},{grid_x1})  y[{grid_y0},{grid_y1})")
    lines.append("")
    lines.append("Legend (lowercase=reached, uppercase=passable but BFS UNREACHED):")
    lines.append("  @  player                                #  wall")
    lines.append("  .  reached level 0     ~  reached level 2     +  reached level 1     B  multi-level")
    lines.append("  o  passable but NOT reached   <-- BFS gaps")
    lines.append("  s/S  bike slope    r/R  ramp east    l/L  ramp west")
    lines.append("  v/V  ledge south   n/N  bike bridge   w/W  warp tile")
    lines.append("  Overlays: digit = obj:<n>,  letter = warp:<n-letter> (a=warp:0, b=warp:1, …)")
    lines.append("")

    pad = 7
    # Tens digit ruler
    tens = " " * pad
    for x in range(grid_x0, grid_x1):
        tens += str((x // 10) % 10) if x % 10 == 0 else " "
    ones = " " * pad
    for x in range(grid_x0, grid_x1):
        ones += str(x % 10)
    lines.append(tens)
    lines.append(ones)

    # Overlay map: (gx, gy) -> single-char marker (object/warp annotation)
    overlay: dict[tuple[int, int], str] = {}
    for o in objects:
        idx = o["index"]
        if idx == 0:
            continue
        gx, gy = o["x"], o["y"]
        if gx == 0 and gy == 0:
            continue
        overlay[(gx, gy)] = str(idx) if idx < 10 else "*"
    for i, w in enumerate(warps):
        overlay[(w["x"], w["y"])] = chr(ord("a") + i) if i < 26 else "*"

    for y in range(grid_y0, grid_y1):
        prefix = f" y={y:3d} "
        row_chars = []
        for x in range(grid_x0, grid_x1):
            base = cell(x, y)
            if (x, y) in overlay and base != "@":
                # show the overlay marker; original tile glyph still recorded
                # in the per-interactible list below.
                row_chars.append(overlay[(x, y)])
            else:
                row_chars.append(base)
        lines.append(prefix + "".join(row_chars))

    # Annotated interactibles
    lines.append("")
    lines.append("Objects (index:label  pos→best_interaction_reach):")
    for o in objects:
        idx = o["index"]
        if idx == 0:
            continue
        gx, gy = o["x"], o["y"]
        if gx == 0 and gy == 0:
            continue
        sprite = (o.get("name", "") or "").strip()
        # Best interaction tile reach via 4-adjacency, any level
        best = None  # (steps, ax, ay, level)
        for ax, ay, _f in [
            (gx, gy - 1, "down"), (gx, gy + 1, "up"),
            (gx - 1, gy, "right"), (gx + 1, gy, "left"),
        ]:
            for lv in (0, 1, 2):
                key = (ax, ay, lv)
                if key in reach_3d_global:
                    s = reach_3d_global[key]
                    if best is None or s < best[0]:
                        best = (s, ax, ay, lv)
        if best is None:
            status = f"UNREACHABLE  manhattan={abs(gx-px)+abs(gy-py)}"
        else:
            s, ax, ay, lv = best
            status = f"reach@{s} via ({ax},{ay},lv{lv})"
        lines.append(f"  obj:{idx:<2}  ({gx:3d},{gy:3d}) h={o.get('height')}  sprite={sprite!r}  -> {status}")

    lines.append("")
    lines.append("Warps (index  pos→reach):")
    for i, w in enumerate(warps):
        gx, gy = w["x"], w["y"]
        best_s = None
        best_lv = None
        for lv in (0, 1, 2):
            key = (gx, gy, lv)
            if key in reach_3d_global:
                s = reach_3d_global[key]
                if best_s is None or s < best_s:
                    best_s = s
                    best_lv = lv
        if best_s is None:
            status = f"UNREACHABLE  manhattan={abs(gx-px)+abs(gy-py)}"
        else:
            status = f"reach@{best_s} (lv{best_lv})"
        dest = w.get("dest_map") if isinstance(w, dict) else None
        lines.append(f"  warp:{i:<2} ({gx:3d},{gy:3d}) -> dest_map={dest}  -> {status}")

    if out_path_arg:
        out_path = Path(out_path_arg)
    else:
        tag = state_name or "current"
        out_path = (
            Path("/workspace/RenegadePlatinumPlaytest/logs")
            / f"map{map_id}_reach_{tag}.txt"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    total_bytes = sum(len(line) + 1 for line in lines)
    print(f"Wrote {len(lines)} lines, {total_bytes} bytes to {out_path}")


if __name__ == "__main__":
    main()
