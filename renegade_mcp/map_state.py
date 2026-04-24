"""Terrain, dynamic objects, and player state reading + ASCII map rendering.

Terrain is always loaded from ROM via the zone header → matrix → land_data
chain. RAM terrain at 0x0231D1E4 is unreliable (garbled after menu
interactions indoors) and only used as a last-resort fallback.
"""

from __future__ import annotations

import os
import struct
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from renegade_mcp.map_names import lookup_map_name

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# Zone header table in ARM9 (Platinum US / Renegade Platinum).
# Each entry is 24 bytes; first u16 is the matrix_id for that zone.
# ARM9 address — fixed across all emulators, no shift.
from renegade_mcp.addresses import ZONE_HEADER_BASE, ZONE_HEADER_STRIDE

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


def is_on_cycling_road(emu: "EmulatorClient", target_x: int = -1, target_y: int = -1) -> bool:
    """Check if player or target is on cycling road bridge tiles while cycling.

    The cycling road (Route 206) forces downhill sliding when the player is
    on the bicycle and standing on bridge tiles (behaviors 0x70/0x71). Detection
    uses tile behavior + cycling state rather than script flags, since the runtime
    flag (PlayerAvatar.unk_00) isn't in save RAM.

    When target coordinates are provided, also checks if the path between player
    and target would cross bridge body tiles (0x71) — catches the case where the
    player is just above the bridge but the target is on it. The column-scan
    heuristic is gated on player *elevation* (BUG-030): under-bridge players
    on ground tiles share the bridge's 2D column but are physically below it,
    so the slide mode must not engage for them.
    """
    from renegade_mcp.addresses import addr
    cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
    if not cycling:
        return False

    state = get_map_state(emu)
    if state is None:
        return False

    terrain = state["terrain"]
    lx, ly = state["local_px"], state["local_py"]
    ox = state.get("origin_x", 0)
    oy = state.get("origin_y", 0)

    # Check current tile
    if 0 <= ly < len(terrain) and 0 <= lx < len(terrain[ly]):
        behavior = terrain[ly][lx] & 0x00FF
        if behavior in CYCLING_ROAD_BRIDGE_BEHAVIORS:
            return True

    # Column-scan heuristic for "player about to step onto bridge body from
    # above". Skipping a naive target-tile behavior check — `bridge_start`
    # (0x70) appears as bookend tiles on Wayward-style bike bridges that
    # are NOT forced-slide, and triggering cycling_road dispatch for
    # those produces a false positive (the Wayward bridges are bike-
    # required but not auto-slide).
    # Only valid when the player is actually at bridge elevation —
    # an under-bridge player on ground shares the bridge's 2D column but is
    # physically below it, and sliding would be wrong. Compare player
    # height to typical bridge body height (>= 40 in fx32 units for Cycling
    # Road's L3 bridge body). Skip scan if we can't read height.
    if target_x >= 0 and target_y >= 0:
        tlx = target_x - ox
        tly = target_y - oy

        try:
            player_h = read_player_height(emu)
        except Exception:
            player_h = None

        if player_h is None or player_h >= 40:
            min_y = min(ly, tly)
            max_y = max(ly, tly)
            check_x = lx  # scan along player's column
            for scan_y in range(min_y, max_y + 1):
                if 0 <= scan_y < len(terrain) and 0 <= check_x < len(terrain[scan_y]):
                    scan_b = terrain[scan_y][check_x] & 0x00FF
                    if scan_b == 0x71:  # bridge body = auto-slide
                        return True

    return False


def read_warps_from_rom(emu: "EmulatorClient", map_id: int) -> list[dict[str, int]]:
    """Read warp events for a map from the ROM zone_event data.

    Returns list of dicts with keys: x, y (tile coords), dest_map, dest_warp.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE + _EVENTS_ARCHIVE_OFFSET
    events_id = emu.read_memory(addr, size="short")

    event_path = ZONE_EVENT_DIR / f"{events_id:04d}.bin"
    if not event_path.exists():
        return []

    data = event_path.read_bytes()
    off = 0

    # Skip BG events
    num_bg = struct.unpack_from("<I", data, off)[0]; off += 4
    off += num_bg * _BG_EVENT_SIZE

    # Skip Object events
    num_obj = struct.unpack_from("<I", data, off)[0]; off += 4
    off += num_obj * _OBJ_EVENT_SIZE

    # Read Warp events
    num_warps = struct.unpack_from("<I", data, off)[0]; off += 4
    warps = []
    for _ in range(num_warps):
        wx, wz, dest_map, dest_warp = struct.unpack_from("<HHHH", data, off)
        off += _WARP_EVENT_SIZE
        warps.append({"x": wx, "y": wz, "dest_map": dest_map, "dest_warp": dest_warp})

    return warps


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


def read_sign_tiles_from_rom(emu: "EmulatorClient", map_id: int) -> list[tuple[int, int]]:
    """Read sign obstacle tiles from ROM zone_event data.

    Returns both the sign tile itself (impassable object) and the activation
    tile one south of it (auto-triggers dialogue when facing north).
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE + _EVENTS_ARCHIVE_OFFSET
    events_id = emu.read_memory(addr, size="short")

    event_path = ZONE_EVENT_DIR / f"{events_id:04d}.bin"
    if not event_path.exists():
        return []

    data = event_path.read_bytes()
    off = 0

    # Skip BG events
    num_bg = struct.unpack_from("<I", data, off)[0]; off += 4
    off += num_bg * _BG_EVENT_SIZE

    # Read Object events, extract sign positions
    num_obj = struct.unpack_from("<I", data, off)[0]; off += 4
    tiles = []
    for _ in range(num_obj):
        gfx_id = struct.unpack_from("<H", data, off + 0x02)[0]
        if gfx_id in SIGN_GFX_IDS:
            sign_x = struct.unpack_from("<H", data, off + 0x18)[0]
            sign_y = struct.unpack_from("<H", data, off + 0x1A)[0]
            tiles.append((sign_x, sign_y))        # sign tile itself (impassable)
            tiles.append((sign_x, sign_y + 1))  # activation tile one south
        off += _OBJ_EVENT_SIZE

    return tiles


# ── Viewport helpers ──

def _compute_viewport_bounds(
    px: int, py: int,
    matrix_w: int, matrix_h: int,
    terrain_ids: list[list[int]],
    terrain: list[list[int]],
    origin_x: int, origin_y: int,
    objects: list[dict],
    chunked: bool,
    viewport_size: int = 15,
) -> tuple[int, int, int, int]:
    """Compute viewport rectangle in global tile coordinates.

    Indoor/small maps: returns tight content bounds (preserves compact rendering).
    Overworld/multi-chunk maps: returns viewport_size x viewport_size centered on
    player, clamped to world edges.

    Returns (vp_x, vp_y, vp_w, vp_h).
    """
    if not chunked:
        # Indoor / single-chunk: find content bounds (existing crop logic)
        min_row, max_row = 31, 0
        min_col, max_col = 31, 0
        for row in range(32):
            for col in range(32):
                if terrain[row][col] != 0:
                    min_row = min(min_row, row)
                    max_row = max(max_row, row)
                    min_col = min(min_col, col)
                    max_col = max(max_col, col)

        for obj in objects:
            lx = obj["x"] - origin_x
            ly = obj["y"] - origin_y
            if 0 <= lx < 32 and 0 <= ly < 32:
                min_row = min(min_row, ly)
                max_row = max(max_row, ly)
                min_col = min(min_col, lx)
                max_col = max(max_col, lx)

        # 1-tile padding
        min_row = max(0, min_row - 1)
        max_row = min(31, max_row + 1)
        min_col = max(0, min_col - 1)
        max_col = min(31, max_col + 1)

        return (
            origin_x + min_col,
            origin_y + min_row,
            max_col - min_col + 1,
            max_row - min_row + 1,
        )

    # Overworld / multi-chunk: center on player, clamp to world bounds
    world_w = matrix_w * CHUNK_SIZE
    world_h = matrix_h * CHUNK_SIZE

    vp_w = min(viewport_size, world_w)
    vp_h = min(viewport_size, world_h)

    vp_x = px - vp_w // 2
    vp_y = py - vp_h // 2

    # Clamp to world edges
    vp_x = max(0, min(vp_x, world_w - vp_w))
    vp_y = max(0, min(vp_y, world_h - vp_h))

    return (vp_x, vp_y, vp_w, vp_h)


def _load_viewport_terrain(
    terrain_ids: list[list[int]],
    matrix_w: int, matrix_h: int,
    vp_x: int, vp_y: int, vp_w: int, vp_h: int,
) -> list[list[int]]:
    """Load and composite raw tile values for the viewport from ROM chunks.

    Returns a vp_h x vp_w grid of u16 tile values (same format as
    load_terrain_from_rom). Tiles from missing/void chunks are 0.
    """
    grid = [[0] * vp_w for _ in range(vp_h)]

    # Determine which chunks overlap the viewport
    cx_min = vp_x // CHUNK_SIZE
    cx_max = (vp_x + vp_w - 1) // CHUNK_SIZE
    cy_min = vp_y // CHUNK_SIZE
    cy_max = (vp_y + vp_h - 1) // CHUNK_SIZE

    for cy in range(cy_min, cy_max + 1):
        for cx in range(cx_min, cx_max + 1):
            if not (0 <= cx < matrix_w and 0 <= cy < matrix_h):
                continue
            land_id = terrain_ids[cy][cx]
            if land_id == 0xFFFF:
                continue

            chunk_terrain = load_terrain_from_rom(land_id)
            if chunk_terrain is None:
                continue

            # Copy the overlapping sub-rectangle from this chunk into the grid
            chunk_global_x = cx * CHUNK_SIZE
            chunk_global_y = cy * CHUNK_SIZE

            # Overlap region in global coords
            ox_start = max(vp_x, chunk_global_x)
            oy_start = max(vp_y, chunk_global_y)
            ox_end = min(vp_x + vp_w, chunk_global_x + CHUNK_SIZE)
            oy_end = min(vp_y + vp_h, chunk_global_y + CHUNK_SIZE)

            for gy in range(oy_start, oy_end):
                for gx in range(ox_start, ox_end):
                    grid[gy - vp_y][gx - vp_x] = chunk_terrain[gy - chunk_global_y][gx - chunk_global_x]

    return grid


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


# ── ASCII map rendering ──

def render_map(
    terrain: list, objects: list, player_local_x: int, player_local_y: int,
    facing: int, elevation: dict | None = None, player_level: int | None = None,
    filter_level: int | None = None,
) -> str:
    """Render a compact 1-char-per-tile ASCII map.

    Symbols: ^v<> player, A-Za-z NPCs, # wall, _ walkable floor,
    · cave floor, . void (outside map), ≈ water, " grass,
    0-9 elevation, /\\ ramps, ][ directional blocks.
    Hex behaviors mapped to single chars with a key when present.

    The terrain grid IS the viewport — render it all, no cropping needed.
    Objects' local_x/local_y are viewport-relative. Elevation keys are
    also viewport-relative when provided.
    """
    # 1-char behavior symbols for common hex behaviors
    _BEHAVIOR_CHAR: dict[int, str] = {
        0x00: '_',  # walkable ground
        0x02: '"', 0x03: '"',  # grass
        0x08: '·',  # cave / dungeon floor (distinct from '.' void)
        0x10: '≈', 0x13: '≈', 0x15: '≈',  # water
        0x20: '=', 0x21: ',',  # ice, sand
        0x30: ']', 0x31: '[',  # directional blocks
        0x38: '>', 0x39: '<', 0x3A: '^', 0x3B: 'v',  # ledges (arrow = jump direction)
        0x5E: '/', 0x5F: '\\',  # stairs
        0x69: 'D', 0x6E: 'D',  # doors
        0x62: '+', 0x63: '+', 0x64: '+', 0x65: '+', 0x67: '+',  # warps
        0x6A: '%', 0x6B: '%',  # escalators
        0x6C: '|', 0x6D: '|', 0x6F: '-',  # sides
        0x70: 'n', 0x71: 'n',  # bridge start/body
        0x72: 'n', 0x73: 'n', 0x74: 'n', 0x75: 'n',  # bridge-over variants
        0x76: 'n', 0x77: 'n', 0x78: 'n', 0x79: 'n',  # bike bridge N-S
        0x7A: 'n', 0x7B: 'n', 0x7C: 'n', 0x7D: 'n',  # bike bridge E-W
        0x80: ':',  # counter
        0xA1: '~', 0xA2: '~', 0xA3: '~',  # snow (deep/deeper/deepest)
        0xA8: '~', 0xA9: '~',  # snow (shallow/shadows)
        0xD9: '\\', 0xDA: '/',  # bike slope top/bottom
        0xD7: '>', 0xD8: '<',  # bike ramps (jump E/W on bike)
    }

    grid_h = len(terrain)
    grid_w = len(terrain[0]) if grid_h > 0 else 0

    obj_at = {}
    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < grid_w and 0 <= ly < grid_h:
            if obj["index"] == 0:
                obj_at[(lx, ly)] = FACING_ARROWS.get(facing, "P")
            else:
                idx = obj["index"]
                if 1 <= idx <= 26:
                    obj_at[(lx, ly)] = chr(ord("A") + idx - 1)
                elif 27 <= idx <= 52:
                    obj_at[(lx, ly)] = chr(ord("a") + idx - 27)
                else:
                    obj_at[(lx, ly)] = "?"

    level_map = elevation["level_map"] if elevation else {}
    ramp_tiles = elevation["ramp_tiles"] if elevation else {}

    lines = []
    behaviors_seen: dict[int, str] = {}

    for row in range(grid_h):
        line_chars = []
        for col in range(grid_w):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            key = (col, row)

            tile_levels = level_map.get(key, [])
            is_filtered_out = (
                filter_level is not None
                and elevation
                and not is_blocked
                and key not in obj_at
                and tile_levels
                and filter_level not in tile_levels
                and key not in ramp_tiles
            )

            if is_filtered_out:
                ch = '~'
            elif key in obj_at:
                ch = obj_at[key]
            elif is_blocked and behavior == 0:
                ch = '#'
            elif is_blocked and behavior in _BEHAVIOR_CHAR:
                ch = _BEHAVIOR_CHAR[behavior]
                behaviors_seen[behavior] = "blocked"
            elif is_blocked:
                ch = '#'
                behaviors_seen[behavior] = "blocked"
            elif elevation and key in ramp_tiles:
                ri = ramp_tiles[key]
                if filter_level is not None and filter_level not in (ri["from_level"], ri["to_level"]):
                    ch = '~'
                else:
                    ch = '\\' if ri["direction"] in ("south", "east") else '/'
            elif elevation and key in level_map and len(level_map[key]) > 1:
                ch = str(level_map[key][-1])  # bridge — show upper level
            elif elevation and behavior in (0x30, 0x31):
                ch = _BEHAVIOR_CHAR[behavior]
            elif elevation and key in level_map and (val == 0 or behavior in (0x00, 0x08)):
                ch = str(level_map[key][0])
            elif val == 0:
                ch = '.'
            elif behavior in _BEHAVIOR_CHAR:
                ch = _BEHAVIOR_CHAR[behavior]
                behaviors_seen[behavior] = "passable"
            else:
                ch = '?'
                behaviors_seen[behavior] = "passable"

            line_chars.append(ch)
        lines.append("".join(line_chars))

    # Compact key — only show behaviors actually seen on this map
    if behaviors_seen:
        key_parts = []
        for beh in sorted(behaviors_seen):
            name = BEHAVIORS.get(beh, f"0x{beh:02x}")
            ch = _BEHAVIOR_CHAR.get(beh, "?")
            key_parts.append(f"{ch}={name}")
        lines.append("Key: " + " ".join(key_parts))

    # Elevation summary (compact single line)
    if elevation:
        parts = [f"L{lv['level']}{'*' if player_level is not None and lv['level'] == player_level else ''}" for lv in elevation["levels"]]
        lines.append(f"Elevation: {' '.join(parts)}")

    return "\n".join(lines)


# ── Axis-ruler rendering ──

def _render_with_axes(
    grid_str: str, vp_x: int, vp_y: int, vp_w: int, vp_h: int,
) -> str:
    """Prefix a rendered grid with an X-axis ruler + per-row Y labels.

    The ruler shows the *last digit* of each column's absolute X coordinate
    (a visual anchor that survives tokenization better than spacing — see
    "Stuck in the Matrix", arxiv 2510.20198). The Y column uses the full
    absolute Y, right-aligned to 3 chars. Trailing lines from render_map
    (Key:..., Elevation:...) are passed through untouched.
    """
    lines = grid_str.split("\n")
    grid_rows = lines[:vp_h]
    trailing = lines[vp_h:]

    x_ruler = "".join(str((vp_x + i) % 10) for i in range(vp_w))
    out: list[str] = [f"    {x_ruler}"]
    for i, row in enumerate(grid_rows):
        out.append(f"{vp_y + i:3d} {row}")
    out.extend(trailing)
    return "\n".join(out)


# ── Interactibles: reachable POIs (dynamic objects + merged warps) ──

# Dynamic-object graphics ids that classify as non-NPC POIs.
_GFX_POKEBALL = 87
_GFX_BERRY = 100

# Adjacency offsets used to find an interaction tile next to a POI.
# (adj_dx, adj_dy, face_direction): `adj_dx/dy` is the displacement FROM
# the POI tile TO the interaction tile; `face_direction` is the direction
# the player must face to see the POI from that adjacent tile.
_INTERACTIBLE_ADJ = (
    (0, -1, "down"),   # adjacent tile is north of POI → face down
    (0, 1, "up"),      # south → face up
    (-1, 0, "right"),  # west → face right
    (1, 0, "left"),    # east → face left
)


def _merge_adjacent_warps(
    warps: list[dict[str, int]],
    reachable_tiles: dict[tuple[int, int], int],
    player_x: int, player_y: int,
    reach_info_3d: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Cluster warps that share a destination AND are 4-adjacent.

    Returns a list of cluster dicts with keys:
      - dest_map, dest_warp: destination identity
      - tiles: list of (x, y) for every constituent warp
      - interaction_xy: (x, y) of the representative tile (nearest
        reachable to the player; falls back to nearest-Manhattan if no
        constituent is reachable)
      - reachable: bool
      - metric: BFS steps when reachable, Manhattan distance otherwise
    """
    by_dest: dict[tuple[int, int], list[dict[str, int]]] = {}
    for w in warps:
        by_dest.setdefault((w["dest_map"], w["dest_warp"]), []).append(w)

    clusters: list[dict[str, Any]] = []
    for (dest_map, dest_warp), group in by_dest.items():
        # 4-connectivity union-find within the group.
        unmerged = list(group)
        while unmerged:
            seed = unmerged.pop(0)
            current = [seed]
            changed = True
            while changed:
                changed = False
                i = 0
                while i < len(unmerged):
                    w = unmerged[i]
                    if any(
                        abs(w["x"] - c["x"]) + abs(w["y"] - c["y"]) == 1
                        for c in current
                    ):
                        current.append(unmerged.pop(i))
                        changed = True
                    else:
                        i += 1

            # Pick the representative interaction tile.
            # On 3D maps, a warp is reachable only if the BFS reached its
            # tile at a level the tile actually has (level_map entry).
            # Falls back to plain 2D lookup when 3D info isn't available.
            best_reach: tuple[int, tuple[int, int]] | None = None
            best_manh: tuple[int, tuple[int, int]] | None = None
            for w in current:
                wx, wy = w["x"], w["y"]
                reach_s: int | None = None
                if reach_info_3d is not None:
                    elev = reach_info_3d["elevation"]
                    ox, oy = reach_info_3d["origin"]
                    reach3d = reach_info_3d["reach"]
                    level_map = elev["level_map"]
                    ramp_tiles = elev["ramp_tiles"]
                    lx, ly = wx - ox, wy - oy
                    tile_levels = level_map.get((lx, ly))
                    if tile_levels is None:
                        ri = ramp_tiles.get((lx, ly))
                        if ri is not None:
                            tile_levels = [ri["from_level"], ri["to_level"]]
                    if tile_levels is None:
                        # Tile not in BDHC → treat as any-level passable.
                        if (wx, wy) in reachable_tiles:
                            reach_s = reachable_tiles[(wx, wy)]
                    else:
                        for lv in tile_levels:
                            s3 = reach3d.get((wx, wy, lv))
                            if s3 is not None and (
                                reach_s is None or s3 < reach_s
                            ):
                                reach_s = s3
                elif (wx, wy) in reachable_tiles:
                    reach_s = reachable_tiles[(wx, wy)]

                if reach_s is not None:
                    if best_reach is None or reach_s < best_reach[0]:
                        best_reach = (reach_s, (wx, wy))
                d = abs(wx - player_x) + abs(wy - player_y)
                if best_manh is None or d < best_manh[0]:
                    best_manh = (d, (wx, wy))

            if best_reach is not None:
                clusters.append({
                    "dest_map": dest_map,
                    "dest_warp": dest_warp,
                    "tiles": [(w["x"], w["y"]) for w in current],
                    "interaction_xy": best_reach[1],
                    "reachable": True,
                    "metric": best_reach[0],
                })
            else:
                assert best_manh is not None
                clusters.append({
                    "dest_map": dest_map,
                    "dest_warp": dest_warp,
                    "tiles": [(w["x"], w["y"]) for w in current],
                    "interaction_xy": best_manh[1],
                    "reachable": False,
                    "metric": best_manh[0],
                })

    return clusters


def _classify_object(
    obj: dict[str, Any], map_id: int,
) -> tuple[str, int | None, dict[str, Any]]:
    """Decide the interactible kind for a dynamic object.

    Returns (kind, resolved_trainer_id_or_None, preview_dict).
    `preview_dict` always includes `object_index` for dispatch. For
    trainers, the caller (which has `emu` in scope) fills in the
    `defeated` field — this helper stops at identity data.
    """
    from renegade_mcp.trainer import (
        is_flavor_trainer,
        lookup_trainer_class,
        trainer_id_from_script,
    )

    idx = obj["index"]
    gfx_id = obj.get("graphics_id", 0)
    sprite_name = (obj.get("name", "") or "").strip()
    trainer_type = obj.get("trainer_type", 0)
    preview: dict[str, Any] = {"object_index": idx}

    if trainer_type > 0:
        tid = trainer_id_from_script(obj.get("script", 0))
        if tid is not None and is_flavor_trainer(map_id, tid):
            preview["flavor_npc"] = True
            return "npc", tid, preview
        if tid is not None:
            trainer_class = lookup_trainer_class(tid)
            preview["trainer_id"] = tid
            if trainer_class is not None:
                preview["trainer_class"] = trainer_class
            if sprite_name and trainer_class and sprite_name != trainer_class:
                preview["sprite_name"] = sprite_name
            return "trainer", tid, preview

    if gfx_id in SIGN_GFX_IDS:
        return "sign", None, preview
    if gfx_id == _GFX_POKEBALL:
        return "item", None, preview
    if gfx_id == _GFX_BERRY:
        # Soil objects store the MiscSaveBlock berry-patch index in data[0].
        # The actual patch state read happens in _build_interactibles where
        # `emu` is in scope.
        patch_id = obj.get("data0")
        if isinstance(patch_id, int) and 0 <= patch_id < 128:
            preview["patch_id"] = patch_id
        return "berry", None, preview
    if sprite_name:
        return "npc", None, preview
    return "object", None, preview


def _build_interactibles(
    emu: EmulatorClient,
    map_id: int,
    objects: list[dict[str, Any]],
    reachable_tiles: dict[tuple[int, int], int],
    player_x: int, player_y: int,
    reach_info_3d: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Construct (reachable, unreachable) interactibles lists.

    `reachable_tiles` must be keyed by GLOBAL tile coords. Objects and
    warps whose interaction tile is in `reachable_tiles` are sorted by
    BFS steps; the rest are reported unreachable with Manhattan distance.

    Entries carry: id, kind, label, x/y (POI), interaction_x/y, face,
    steps (or distance), preview.
    """
    from renegade_mcp.map_names import lookup_map_name
    from renegade_mcp.trainer import is_trainer_defeated

    reachable: list[dict[str, Any]] = []
    unreachable: list[dict[str, Any]] = []

    # --- Dynamic objects ---
    for obj in objects:
        idx = obj["index"]
        if idx == 0:
            continue  # player
        gx, gy = obj["x"], obj["y"]
        # Drayano left many unused zone_event entries in place (he disables
        # rather than deletes objects); the engine parks them at (0, 0).
        # They clutter `unreachable_interactibles` without being
        # actionable — filter them out regardless of kind.
        if gx == 0 and gy == 0:
            continue

        kind, tid, preview = _classify_object(obj, map_id)
        sprite_name = (obj.get("name", "") or "").strip()

        # Label — prefer authoritative trainer class, else sprite name, else generic.
        if kind == "trainer":
            trainer_class = preview.get("trainer_class")
            label = trainer_class or sprite_name or f"Trainer {tid}"
            # Fill in defeated bit now that we have emu in scope.
            if tid is not None:
                preview["defeated"] = is_trainer_defeated(emu, tid)
        elif kind == "sign":
            label = sprite_name or "Sign"
        elif kind == "item":
            label = sprite_name or "Item Ball"
        elif kind == "berry":
            # Resolve the soil's patch state now that emu is in scope.
            patch_id = preview.get("patch_id")
            patch_state: dict[str, Any] | None = None
            if isinstance(patch_id, int):
                from renegade_mcp.berry_patches import read_patch
                patch_state = read_patch(emu, patch_id)
            if patch_state is not None:
                preview["patch"] = patch_state
            if patch_state is None or not patch_state.get("planted"):
                label = sprite_name or "Empty Berry Patch"
            elif patch_state.get("harvestable"):
                label = (
                    f"{patch_state['berry']} Berry (ripe x{patch_state['yield']})"
                )
            else:
                label = (
                    f"{patch_state['berry']} Berry ({patch_state['growth_stage']})"
                )
        elif kind == "npc":
            label = sprite_name or f"NPC {idx}"
        else:
            label = sprite_name or f"Object {idx}"

        # Find best interaction tile.
        # On 3D maps, the adjacent tile is only a valid approach if the
        # BFS reached it at the object's own level — a ground-level tile
        # under a bridge trainer doesn't let the player interact with
        # someone standing 8 tiles above them in the Y axis.
        best: tuple[int, int, int, str] | None = None  # (steps, adj_x, adj_y, face)
        obj_level: int | None = None
        if reach_info_3d is not None:
            obj_level = reach_info_3d["object_levels"].get(idx)
        for adj_dx, adj_dy, face in _INTERACTIBLE_ADJ:
            adj_gx, adj_gy = gx + adj_dx, gy + adj_dy
            s: int | None = None
            if reach_info_3d is not None and obj_level is not None:
                s = reach_info_3d["reach"].get((adj_gx, adj_gy, obj_level))
            elif (adj_gx, adj_gy) in reachable_tiles:
                s = reachable_tiles[(adj_gx, adj_gy)]
            if s is not None and (best is None or s < best[0]):
                best = (s, adj_gx, adj_gy, face)

        entry: dict[str, Any] = {
            "id": f"obj:{idx}",
            "kind": kind,
            "label": label,
            "x": gx, "y": gy,
            "preview": preview,
        }
        if best is not None:
            s, adj_gx, adj_gy, face = best
            entry["interaction_x"] = adj_gx
            entry["interaction_y"] = adj_gy
            entry["face"] = face
            entry["steps"] = s
            reachable.append(entry)
        else:
            entry["distance"] = abs(gx - player_x) + abs(gy - player_y)
            unreachable.append(entry)

    # --- Warps (merged by destination + adjacency) ---
    all_warps = read_warps_from_rom(emu, map_id)
    clusters = _merge_adjacent_warps(
        all_warps, reachable_tiles, player_x, player_y,
        reach_info_3d=reach_info_3d,
    )
    warp_idx = 0
    for c in clusters:
        dest = lookup_map_name(c["dest_map"])
        dest_name = dest.get("name", f"Map {c['dest_map']}")
        ix, iy = c["interaction_xy"]
        preview = {
            "dest_map_id": c["dest_map"],
            "dest_map_name": dest_name,
            "dest_warp": c["dest_warp"],
        }
        if len(c["tiles"]) > 1:
            preview["merged_tile_count"] = len(c["tiles"])
        entry = {
            "id": f"warp:{warp_idx}",
            "kind": "warp",
            "label": f"to {dest_name}",
            "x": ix, "y": iy,
            "interaction_x": ix, "interaction_y": iy,
            "face": None,
            "preview": preview,
        }
        warp_idx += 1
        if c["reachable"]:
            entry["steps"] = c["metric"]
            reachable.append(entry)
        else:
            entry["distance"] = c["metric"]
            unreachable.append(entry)

    reachable.sort(key=lambda e: e["steps"])
    unreachable.sort(key=lambda e: e["distance"])
    return reachable, unreachable


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
