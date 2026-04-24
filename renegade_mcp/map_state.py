"""High-level map-state orchestration + backward-compat shim.

This file is intentionally thin. The heavy lifting lives in:
  map_terrain    — ROM/RAM terrain loading, matrix/chunk resolution,
                   tile-behavior + facing constants.
  map_elevation  — BDHC parsing and per-tile elevation analysis.
  map_render     — ASCII rendering with axis rulers.
  map_poi        — warp/sign/object classification and interactibles.

The four native functions here are the orchestrators that tie the other
modules together: read_objects (dynamic object scan), read_player_state
(position/facing), get_map_state (terrain + objects + player as one
dict), and view_map (the public MCP tool).

Everything else imported below is re-exported for backward compatibility;
new code should import directly from the specialised modules.
"""

from __future__ import annotations

import struct
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# Object-array layout — used by read_objects (below).
OBJ_STRIDE = 0x128
OBJ_MAX_ENTRIES = 64

# ── Re-exports from map_terrain (backward-compat shim) ──
from renegade_mcp.map_terrain import (  # noqa: F401
    BEHAVIORS,
    BIKE_BRIDGE_BEHAVIORS,
    CHUNK_SIZE,
    CYCLING_ROAD_BRIDGE_BEHAVIORS,
    FACING_ARROWS,
    FACING_NAMES,
    FLAG_ON_CYCLING_ROAD,
    GFX_DATA_FILE,
    GFX_NAMES,
    LAND_DATA_DIR,
    MATRIX_DIR,
    MOVEMENT_TYPES,
    ROMDATA_DIR,
    SIGN_GFX_IDS,
    TERRAIN_SIZE,
    ZONE_EVENT_DIR,
    _BG_EVENT_SIZE,
    _EVENTS_ARCHIVE_OFFSET,
    _OBJ_EVENT_SIZE,
    _WARP_EVENT_SIZE,
    _load_gfx_names,
    find_matrix_for_map,
    get_matrix_for_map,
    is_terrain_empty,
    load_terrain_from_rom,
    needs_chunk_lookup,
    parse_matrix,
    read_terrain_from_ram,
    resolve_chunk,
    resolve_terrain_from_rom,
)
from renegade_mcp.map_elevation import (  # noqa: F401
    _tile_to_bdhc,
    analyze_elevation,
    get_land_data_id,
    parse_bdhc,
    read_player_height,
    tile_to_bdhc,
)
from renegade_mcp.map_render import (  # noqa: F401
    _compute_viewport_bounds,
    _load_viewport_terrain,
    _render_with_axes,
    render_map,
)
from renegade_mcp.map_poi import (  # noqa: F401
    _build_interactibles,
    _classify_object,
    _merge_adjacent_warps,
    is_on_cycling_road,
    read_sign_tiles_from_rom,
    read_warps_from_rom,
)


# ── Lightweight passability for BFS flood-fill (view_map reachability) ──
# Mirrors navigation.py's passability logic without importing it.
_FLOOD_OBSTACLES = {0x10, 0x15, 0x13, 0x4A, 0x4B}  # water, waterfall, rock climb
_FLOOD_PASSABLE_OVERRIDES = {
    0x69,                                  # door
    0x62, 0x63, 0x64, 0x6C, 0x6D, 0x6F,   # directional warps
    0x38, 0x39, 0x3A, 0x3B,               # ledges
    0x6E,                                  # walk-into warp north
}


def _bfs_flood_fill(
    terrain: list[list[int]],
    start_x: int, start_y: int,
    npc_positions: set[tuple[int, int]],
    width: int, height: int,
    max_steps: int | None = None,
) -> dict[tuple[int, int], int]:
    """BFS flood-fill from (start_x, start_y). Returns {(x,y): steps} for all reachable tiles.

    When ``max_steps`` is given, the flood stops expanding beyond that
    distance — tiles farther than the cap are simply absent from the result.
    """
    dist: dict[tuple[int, int], int] = {(start_x, start_y): 0}
    queue: deque[tuple[int, int, int]] = deque([(start_x, start_y, 0)])

    while queue:
        x, y, d = queue.popleft()
        if max_steps is not None and d >= max_steps:
            continue
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in dist:
                continue
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in npc_positions:
                continue
            val = terrain[ny][nx]
            behavior = val & 0x00FF
            is_blocked = (val & 0x8000) != 0
            if is_blocked and behavior not in _FLOOD_PASSABLE_OVERRIDES:
                continue
            if behavior in _FLOOD_OBSTACLES:
                continue
            nd = d + 1
            dist[(nx, ny)] = nd
            queue.append((nx, ny, nd))

    return dist


# ── Dynamic objects ──

def read_objects(emu: EmulatorClient) -> list[dict[str, Any]]:
    """Scan the overworld object array and return active objects with identity info.

    For each active entry, parses the MapObject struct header to get
    graphicsID, movementType, localID, trainerType, and script — enabling
    identification of what each object actually is (NPC, item ball, etc.).

    Reads the whole 64-slot array as one memory block and parses locally.
    The previous "stop after 3 consecutive empty slots" heuristic was
    unsafe: Gen 4 evicts distant NPCs out of the array while keeping
    others loaded, so slots 2/3/4 can be empty (status=0) while 5+ are
    live. Once that happened we silently dropped Mira, all trainers, and
    every hidden rock from view_map's output. One block read costs one
    round-trip and ~19 KB of data, which is cheaper than the prior
    up-to-20 per-slot reads anyway.
    """
    import struct
    from renegade_mcp.addresses import addr

    obj_fpx_base = addr("OBJ_ARRAY_FPX_BASE")
    obj_struct_base = obj_fpx_base - 0x70  # True start of MapObject[0]
    fpx_offset_within_slot = obj_fpx_base - obj_struct_base  # 0x70

    block = emu.read_memory_block(obj_struct_base, OBJ_STRIDE * OBJ_MAX_ENTRIES)

    objects = []
    for i in range(OBJ_MAX_ENTRIES):
        off = i * OBJ_STRIDE
        # First 15 u32s: 9 header fields (status, unk, localID, mapID,
        # graphicsID, movementType, trainerType, flag, script), then 5
        # direction fields (initialDir, facingDir, movingDir, prevFacingDir,
        # prevMovingDir), then data[0] at index 14 (offset 0x38). data[0]
        # is the zone_event NPC-params field — e.g. soil objects put the
        # berry patch index here.
        header = struct.unpack_from("<15I", block, off)
        status = header[0]
        # Empty slot — keep scanning; later slots can still be populated.
        if status == 0:
            continue

        # Three u32s at +0x70: fpx (tile_x fx32), fpy (height fx32), fpz
        # (tile_y fx32). Naming matches `read_player_height` which reads
        # the middle u32 from the same layout (OBJ_ARRAY_FPX_BASE + 4).
        fpx, fpy_height, fpz = struct.unpack_from(
            "<III", block, off + fpx_offset_within_slot,
        )
        tile_x = (fpx >> 16) & 0xFFFF
        tile_y = (fpz >> 16) & 0xFFFF
        if tile_x > 10000 or tile_y > 10000:
            continue

        # Object's world height (fx32 → units). Signed interpretation —
        # under-ground heights exist but are rare; player height canary uses
        # the same conversion in `read_player_height`.
        height_raw = fpy_height
        if height_raw >= 0x80000000:
            height_raw -= 0x100000000
        height_units = height_raw / 4096.0

        gfx_id = header[4]
        mv_id = header[5]
        obj: dict[str, Any] = {
            "index": i,
            "x": tile_x, "y": tile_y,
            "fpx": fpx, "fpy": fpz, "height": height_units,
            "local_id": header[2],
            "graphics_id": gfx_id,
            "name": GFX_NAMES.get(gfx_id, f"Unknown ({gfx_id})"),
            "movement_type": MOVEMENT_TYPES.get(mv_id, f"type_{mv_id}"),
            "movement_type_id": mv_id,
            "trainer_type": header[6],
            "script": header[8],
            "data0": header[14],
        }
        objects.append(obj)

    return objects


# ── Player state ──

def read_player_state(emu: EmulatorClient) -> tuple[int, int, int, int]:
    """Read player position and facing. Returns (map_id, x, y, facing)."""
    from renegade_mcp.addresses import addr
    pos_base = addr("PLAYER_POS_BASE")
    map_id = emu.read_memory(pos_base, size="long")
    x = emu.read_memory(pos_base + 8, size="long")
    y = emu.read_memory(pos_base + 12, size="long")
    facing = emu.read_memory(addr("PLAYER_FACING_ADDR"), size="long")
    return map_id, x, y, facing


# ── High-level map state ──

def get_map_state(emu: EmulatorClient) -> dict[str, Any] | None:
    """Read full map state: terrain grid, objects, player position.

    Terrain is resolved from ROM (zone header → matrix → land_data) which is
    immune to RAM corruption from menu overlays.  Falls back to RAM terrain
    only when ROM resolution fails.

    Returns dict with terrain, objects, positions, and origin info.
    Returns None if all resolution methods fail.
    """
    map_id, px, py, facing = read_player_state(emu)
    objects = read_objects(emu)

    # Always try ROM first — reliable regardless of menu state.
    terrain, origin_x, origin_y, matrix_w, matrix_h = resolve_terrain_from_rom(emu, map_id, px, py)
    chunked = matrix_w > 1 or matrix_h > 1

    # Fall back to RAM terrain if ROM resolution failed.
    if terrain is None:
        ram_terrain = read_terrain_from_ram(emu)
        if not is_terrain_empty(ram_terrain):
            terrain = ram_terrain
            origin_x, origin_y = 0, 0
            chunked = False

    if terrain is None:
        return None

    local_px = px - origin_x
    local_py = py - origin_y
    height = len(terrain)
    width = len(terrain[0]) if terrain else 0
    for obj in objects:
        lx = obj["x"] - origin_x
        ly = obj["y"] - origin_y
        obj["local_x"] = lx
        obj["local_y"] = ly
        # Record terrain behavior underneath this object
        if 0 <= ly < height and 0 <= lx < width:
            tile_val = terrain[ly][lx]
            behavior = tile_val & 0x00FF
            if behavior != 0:
                obj["standing_on"] = f"0x{behavior:02X}"

    return {
        "terrain": terrain,
        "objects": objects,
        "map_id": map_id,
        "px": px, "py": py,
        "local_px": local_px, "local_py": local_py,
        "origin_x": origin_x, "origin_y": origin_y,
        "facing": facing,
        "chunked": chunked,
    }


def view_map(emu: EmulatorClient, level: int = -1) -> dict[str, Any]:
    """Get player-centered ASCII map with terrain, NPCs, and interactibles.

    Indoor/small maps: compact content-fitted rendering (no void padding).
    Overworld maps: 15x15 viewport centered on the player, loading adjacent
    chunks as needed. Edges clamp to world bounds.

    Args:
        level: Show only this elevation level (-1 = show all levels).
    """
    map_id, px, py, facing = read_player_state(emu)
    objects = read_objects(emu)
    facing_name = FACING_NAMES.get(facing, "?")

    # Get matrix metadata for viewport computation
    matrix_info = get_matrix_for_map(emu, map_id)

    if matrix_info is None:
        # Fallback: single-chunk from ROM or RAM (legacy path)
        state = get_map_state(emu)
        if state is None:
            return {
                "error": "Could not resolve map chunk",
                "map": "", "player": {},
                "interactibles": [], "unreachable_interactibles": [],
            }
        # Use old single-chunk path with content crop
        terrain = state["terrain"]
        origin_x, origin_y = state["origin_x"], state["origin_y"]
        chunked = False
        matrix_w, matrix_h, terrain_ids = 1, 1, [[0]]
    else:
        _matrix_id, matrix_w, matrix_h, _header_ids, terrain_ids = matrix_info
        chunked = matrix_w > 1 or matrix_h > 1

        # Load the player's chunk for indoor content-bounds detection
        chunk_terrain, origin_x, origin_y, _, _ = resolve_terrain_from_rom(emu, map_id, px, py)
        if chunk_terrain is None:
            return {
                "error": "Could not resolve terrain",
                "map": "", "player": {},
                "interactibles": [], "unreachable_interactibles": [],
            }
        terrain = chunk_terrain

    # Compute viewport bounds
    vp_x, vp_y, vp_w, vp_h = _compute_viewport_bounds(
        px, py, matrix_w, matrix_h, terrain_ids,
        terrain, origin_x, origin_y, objects, chunked,
    )

    # Load viewport terrain
    if chunked:
        vp_terrain = _load_viewport_terrain(terrain_ids, matrix_w, matrix_h, vp_x, vp_y, vp_w, vp_h)
    else:
        # Indoor: extract the viewport sub-rectangle from the single chunk
        local_vp_x = vp_x - origin_x
        local_vp_y = vp_y - origin_y
        vp_terrain = []
        for row in range(vp_h):
            src_row = local_vp_y + row
            vp_terrain.append(terrain[src_row][local_vp_x:local_vp_x + vp_w])

    # Compute viewport-relative positions
    for obj in objects:
        obj["local_x"] = obj["x"] - vp_x
        obj["local_y"] = obj["y"] - vp_y
        # Record terrain behavior underneath this object
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= ly < vp_h and 0 <= lx < vp_w:
            behavior = vp_terrain[ly][lx] & 0x00FF
            if behavior != 0:
                obj["standing_on"] = f"0x{behavior:02X}"

    player_grid_x = px - vp_x
    player_grid_y = py - vp_y

    # Filter objects to viewport
    visible_objects = [
        o for o in objects
        if 0 <= o["local_x"] < vp_w and 0 <= o["local_y"] < vp_h
    ]

    # Elevation (only meaningful for single-chunk indoor maps)
    elevation = None
    player_elev = None
    if not chunked:
        land_id = get_land_data_id(emu, map_id, px, py)
        if land_id is not None:
            bdhc = parse_bdhc(land_id)
            if bdhc is not None:
                # analyze_elevation uses the full 32x32 chunk terrain
                elevation = analyze_elevation(bdhc, terrain)
                if elevation is not None:
                    player_h = round(read_player_height(emu))
                    player_elev = elevation["height_to_level"].get(player_h)

                    # Translate elevation keys from chunk-local to viewport-local
                    offset_x = vp_x - origin_x
                    offset_y = vp_y - origin_y
                    elevation["level_map"] = {
                        (c - offset_x, r - offset_y): lvls
                        for (c, r), lvls in elevation["level_map"].items()
                        if 0 <= c - offset_x < vp_w and 0 <= r - offset_y < vp_h
                    }
                    elevation["ramp_tiles"] = {
                        (c - offset_x, r - offset_y): info
                        for (c, r), info in elevation["ramp_tiles"].items()
                        if 0 <= c - offset_x < vp_w and 0 <= r - offset_y < vp_h
                    }

    filter_level = level if level >= 0 else None

    map_str = render_map(
        vp_terrain, visible_objects,
        player_grid_x, player_grid_y, facing,
        elevation=elevation, player_level=player_elev,
        filter_level=filter_level,
    )

    # Build header with viewport origin
    from renegade_mcp.map_names import lookup_map_name
    location = lookup_map_name(map_id)
    elev_str = f" L{player_elev}" if elevation and player_elev is not None else ""
    header = f"{location['display']} ({px},{py}) {facing_name}{elev_str}  origin:({vp_x},{vp_y}) {vp_w}x{vp_h}"

    # ── Reachability BFS — keyed by GLOBAL tile coords, capped at 250 steps.
    #    Scope spans the full multi-chunk (up to 5x5) or indoor chunk so
    #    interactibles outside the 15x15 render viewport still get a
    #    reachable/unreachable answer. Under-bridge tiles correctly stay
    #    unreachable from on-bridge players via the elevation-aware 3D BFS.
    #    Cap raised 150→250 (cave systems), then 250→500 in session 29 —
    #    Wayward Cave post-Mira-quest (73,29) → (41,53) is ~100+ Manhattan
    #    through the cave interior with lots of branching, and BFS on a
    #    5×5 chunk multi-chunk cave has been comfortably fast at 500 steps.
    MAX_REACH_STEPS = 500
    reachable_tiles: dict[tuple[int, int], int] = {}
    reachable_tiles_3d: dict[tuple[int, int, int], int] | None = None
    object_levels: dict[int, int] = {}
    mc_elev_for_classifier: dict | None = None
    reach_3d_ok = False
    mc_bounds: tuple[int, int, int, int] | None = None  # (ox, oy, w, h)

    if chunked:
        from renegade_mcp.pathfinding import (
            _bfs_reachable_3d,
            _build_multi_chunk_elevation,
            _build_multi_chunk_terrain,
            _height_to_level,
        )
        # Gather every POI chunk so the BFS grid spans them. Without this the
        # region is viewport-bounded and POIs in distant chunks of the same
        # map appear unreachable (BUG-039: Wayward Cave bridge (73,29) →
        # warp (41,53) routes through x<32 which the viewport never loads).
        poi_points: list[tuple[int, int]] = [
            (obj["x"], obj["y"]) for obj in objects if obj["index"] != 0
        ]
        for w in read_warps_from_rom(emu, map_id):
            poi_points.append((w["x"], w["y"]))
        mc_result = _build_multi_chunk_terrain(
            emu, map_id, px, py,
            vp_x + vp_w - 1, vp_y + vp_h - 1,
            extra_targets=poi_points,
        )
        if mc_result is not None:
            mc_terrain, mc_ox, mc_oy, mc_w, mc_h = mc_result
            mc_bounds = (mc_ox, mc_oy, mc_w, mc_h)
            mc_elev = _build_multi_chunk_elevation(
                emu, map_id, mc_terrain, mc_ox, mc_oy, mc_w, mc_h,
            )
            if mc_elev is not None:
                mc_player_level = _height_to_level(
                    read_player_height(emu), mc_elev,
                    tile_x=px - mc_ox, tile_y=py - mc_oy,
                )
                if mc_player_level is not None:
                    from renegade_mcp.nav_constants import is_follower_npc
                    # Build 3D NPC blocker set. Each NPC blocks only the level
                    # closest to its stored height — bridge-level trainers
                    # don't block ground paths under the bridge and vice
                    # versa.
                    mc_npc_3d: set[tuple[int, int, int]] = set()
                    object_levels: dict[int, int] = {}
                    for o in objects:
                        if o["index"] == 0 or is_follower_npc(o):
                            continue
                        olx, oly = o["x"] - mc_ox, o["y"] - mc_oy
                        if not (0 <= olx < mc_w and 0 <= oly < mc_h):
                            continue
                        olevel = _height_to_level(
                            o.get("height", 0.0), mc_elev,
                            tile_x=olx, tile_y=oly,
                        )
                        if olevel is None:
                            continue
                        mc_npc_3d.add((olx, oly, olevel))
                        object_levels[o["index"]] = olevel
                    reach_3d_local = _bfs_reachable_3d(
                        mc_terrain, mc_npc_3d, mc_elev,
                        px - mc_ox, py - mc_oy, mc_player_level,
                        width=mc_w, height=mc_h,
                        max_steps=MAX_REACH_STEPS,
                    )
                    # 3D-keyed reach in global coords (x, y, level) → steps.
                    reachable_tiles_3d: dict[tuple[int, int, int], int] = {
                        (gx + mc_ox, gy + mc_oy, lv): s
                        for (gx, gy, lv), s in reach_3d_local.items()
                    }
                    # Flatten to 2D for back-compat with code paths that
                    # only need tile-level reach info.
                    reachable_tiles = {}
                    for (gx, gy, _lv), s in reachable_tiles_3d.items():
                        prev = reachable_tiles.get((gx, gy))
                        if prev is None or s < prev:
                            reachable_tiles[(gx, gy)] = s
                    mc_elev_for_classifier = mc_elev
                    reach_3d_ok = True

    if not reach_3d_ok:
        # 2D fallback on raw u16 terrain. On chunked maps where the BDHC
        # reported flat terrain (mc_elev is None) but a multi-chunk extent
        # was still built, flood over that whole extent — otherwise POIs
        # just outside the 15x15 render viewport would be reported
        # unreachable even when a short walking path exists (e.g. Mira in
        # Wayward Cave, 4 tiles north of the viewport top).
        if chunked and mc_bounds is not None:
            mc_ox, mc_oy, mc_w, mc_h = mc_bounds
            flood_terrain = _load_viewport_terrain(
                terrain_ids, matrix_w, matrix_h,
                mc_ox, mc_oy, mc_w, mc_h,
            )
            flood_w, flood_h = mc_w, mc_h
            flood_ox, flood_oy = mc_ox, mc_oy
            local_px_flood = px - mc_ox
            local_py_flood = py - mc_oy
        elif chunked:
            flood_terrain = vp_terrain
            flood_w, flood_h = vp_w, vp_h
            flood_ox, flood_oy = vp_x, vp_y
            local_px_flood, local_py_flood = player_grid_x, player_grid_y
        else:
            flood_terrain = terrain
            flood_h = len(terrain)
            flood_w = len(terrain[0]) if flood_h > 0 else 0
            flood_ox, flood_oy = origin_x, origin_y
            local_px_flood = px - origin_x
            local_py_flood = py - origin_y

        if 0 <= local_px_flood < flood_w and 0 <= local_py_flood < flood_h:
            from renegade_mcp.nav_constants import is_follower_npc
            npc_positions = {
                (obj["x"] - flood_ox, obj["y"] - flood_oy)
                for obj in objects
                if obj["index"] != 0 and not is_follower_npc(obj)
            }
            reach2d = _bfs_flood_fill(
                flood_terrain, local_px_flood, local_py_flood,
                npc_positions, flood_w, flood_h,
                max_steps=MAX_REACH_STEPS,
            )
            reachable_tiles = {
                (lx + flood_ox, ly + flood_oy): s
                for (lx, ly), s in reach2d.items()
            }

    # Package 3D reach info for the elevation-aware POI classifier. The
    # classifier needs to translate global coords to the BDHC's local grid
    # (mc_ox, mc_oy origin) to look up per-tile level_map entries.
    reach_info_3d: dict[str, Any] | None = None
    if reachable_tiles_3d is not None and mc_elev_for_classifier is not None:
        assert mc_bounds is not None
        reach_info_3d = {
            "reach": reachable_tiles_3d,
            "object_levels": object_levels,
            "elevation": mc_elev_for_classifier,
            "origin": (mc_bounds[0], mc_bounds[1]),
        }
    interactibles, unreachable_interactibles = _build_interactibles(
        emu, map_id, objects, reachable_tiles, px, py,
        reach_info_3d=reach_info_3d,
    )

    map_str_with_axes = _render_with_axes(map_str, vp_x, vp_y, vp_w, vp_h)

    map_body = header + "\n\n" + map_str_with_axes
    if unreachable_interactibles:
        map_body += (
            f"\nUnreachable: {len(unreachable_interactibles)} interactible(s) — "
            f"see `unreachable_interactibles`"
        )

    result: dict[str, Any] = {
        "map": map_body,
        "location": location,
        "player": {
            "x": px, "y": py,
            "facing": facing_name,
            "grid_x": player_grid_x,
            "grid_y": player_grid_y,
        },
        "interactibles": interactibles,
        "unreachable_interactibles": unreachable_interactibles,
    }
    if elevation is not None and player_elev is not None:
        result["player"]["elevation"] = player_elev
    return result
