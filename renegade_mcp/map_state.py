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

# ── Memory layout constants ──
TERRAIN_SIZE = 2048  # 32*32*2

# Zone header table in ARM9 (Platinum US / Renegade Platinum).
# Each entry is 24 bytes; first u16 is the matrix_id for that zone.
# ARM9 address — fixed across all emulators, no shift.
from renegade_mcp.addresses import ZONE_HEADER_BASE, ZONE_HEADER_STRIDE

OBJ_STRIDE = 0x128
OBJ_MAX_ENTRIES = 64

# ── ROM data paths (relative to CWD = project root) ──
ROMDATA_DIR = Path("romdata")
LAND_DATA_DIR = ROMDATA_DIR / "land_data"
MATRIX_DIR = ROMDATA_DIR / "map_matrix"
ZONE_EVENT_DIR = ROMDATA_DIR / "zone_event"
CHUNK_SIZE = 32

# Zone event struct sizes (bytes)
_BG_EVENT_SIZE = 20
_OBJ_EVENT_SIZE = 32
_WARP_EVENT_SIZE = 12

# Offset from ZONE_HEADER_BASE to eventsArchiveID within the zone header.
# ZONE_HEADER_BASE points to mapMatrixID (+0x02 in the C struct), so
# eventsArchiveID (+0x10 in the C struct) is at relative offset +0x0E.
_EVENTS_ARCHIVE_OFFSET = 0x0E

# ── Display constants ──
FACING_ARROWS = {0: "^", 1: "v", 2: "<", 3: ">"}
FACING_NAMES = {0: "up", 1: "down", 2: "left", 3: "right"}

BEHAVIORS = {
    0x00: "ground", 0x02: "tall_grass", 0x03: "very_tall_grass",
    0x08: "cave_floor", 0x10: "water", 0x13: "waterfall", 0x15: "sea",
    0x20: "ice", 0x21: "sand",
    0x30: "block_E", 0x31: "block_W",
    0x38: "ledge_S", 0x39: "ledge_N", 0x3A: "ledge_W", 0x3B: "ledge_E",
    0x5E: "stairs_E", 0x5F: "stairs_W",
    0x62: "warp_E", 0x63: "warp_W", 0x64: "warp_N", 0x65: "warp_S",
    0x67: "warp_panel", 0x69: "door",
    0x6A: "escalator", 0x6B: "escalator",
    0x6C: "side_E", 0x6D: "side_W", 0x6E: "side_N", 0x6F: "side_S",
    # Bridge tiles (0x70-0x7D) — from decomp map_tile_behaviors.h
    0x70: "bridge_start", 0x71: "bridge",
    0x72: "bridge_over_cave", 0x73: "bridge_over_water",
    0x74: "bridge_over_sand", 0x75: "bridge_over_snow",
    0x76: "bike_bridge_NS", 0x77: "bike_bridge_NS_enc",
    0x78: "bike_bridge_NS_water", 0x79: "bike_bridge_NS_sand",
    0x7A: "bike_bridge_EW", 0x7B: "bike_bridge_EW_enc",
    0x7C: "bike_bridge_EW_water", 0x7D: "bike_bridge_EW_sand",
    0x80: "counter",
    # Snow/mud tiles (0xA0-0xA9) — from decomp map_tile_behaviors.h
    0xA0: "berry_patch",
    0xA1: "snow_deep", 0xA2: "snow_deeper", 0xA3: "snow_deepest",
    0xA4: "mud", 0xA5: "mud_deep", 0xA6: "mud_grass", 0xA7: "mud_deep_grass",
    0xA8: "snow_shallow", 0xA9: "snow_shadows",
    # Bike slope/ramp tiles (0xD7-0xDB) — from decomp map_tile_behaviors.h
    0xD7: "bike_ramp_E", 0xD8: "bike_ramp_W",
    0xD9: "bike_slope_top", 0xDA: "bike_slope_bottom", 0xDB: "bike_parking",
}

# Behavior bytes that indicate cycling road bridge tiles (forced downhill slide
# when FLAG_ON_CYCLING_ROAD is set). Used by navigation to detect/refuse sliding.
BIKE_BRIDGE_BEHAVIORS = frozenset({0x70, 0x71, 0x76, 0x77, 0x78, 0x79,
                                    0x7A, 0x7B, 0x7C, 0x7D})

# Cycling road flag — set by gate scripts, forces bike + downhill slide
FLAG_ON_CYCLING_ROAD = 2453


def is_on_cycling_road(emu: "EmulatorClient", target_x: int = -1, target_y: int = -1) -> bool:
    """Check if player or target is on cycling road bridge tiles while cycling.

    The cycling road (Route 206) forces downhill sliding when the player is
    on the bicycle and standing on bridge tiles (behaviors 0x70/0x71). Detection
    uses tile behavior + cycling state rather than script flags, since the runtime
    flag (PlayerAvatar.unk_00) isn't in save RAM.

    When target coordinates are provided, also checks if the path between player
    and target would cross bridge body tiles (0x71) — catches the case where the
    player is just above the bridge but the target is on it.
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
        if behavior in BIKE_BRIDGE_BEHAVIORS:
            return True

    # Check target tile if provided
    if target_x >= 0 and target_y >= 0:
        tlx = target_x - ox
        tly = target_y - oy
        if 0 <= tly < len(terrain) and 0 <= tlx < len(terrain[tly]):
            t_behavior = terrain[tly][tlx] & 0x00FF
            if t_behavior in BIKE_BRIDGE_BEHAVIORS:
                return True

        # Check if any tile in the Y range between player and target is a bridge
        # body tile (0x71) at the player's X column — catches approaching from above
        min_y = min(ly, tly)
        max_y = max(ly, tly)
        check_x = lx  # scan along player's column
        for scan_y in range(min_y, max_y + 1):
            if 0 <= scan_y < len(terrain) and 0 <= check_x < len(terrain[scan_y]):
                scan_b = terrain[scan_y][check_x] & 0x00FF
                if scan_b == 0x71:  # bridge body = auto-slide
                    return True

    return False


# ── Object graphics name lookup ──
GFX_DATA_FILE = Path("data/obj_event_gfx.txt")


def _load_gfx_names() -> dict[int, str]:
    """Load graphicsID → name mapping from data file."""
    names = {}
    if not GFX_DATA_FILE.exists():
        return names
    for line in GFX_DATA_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            gfx_id = int(parts[0])
        except ValueError:
            continue
        raw = parts[1].strip()
        # Strip prefix and convert to readable name
        clean = raw.removeprefix("OBJ_EVENT_GFX_").replace("_", " ").title()
        names[gfx_id] = clean
    return names


GFX_NAMES: dict[int, str] = _load_gfx_names()

MOVEMENT_TYPES = {
    0: "none", 1: "look_around", 2: "walk_around",
    3: "wander", 15: "stationary",
}


# ── Terrain reading ──

def read_terrain_from_ram(emu: EmulatorClient) -> list[list[int]]:
    """Read the 32x32 terrain collision grid from RAM."""
    from renegade_mcp.addresses import addr
    vals = emu.read_memory_range(addr("TERRAIN_ADDR"), size="short", count=1024)
    return [vals[row * 32 : (row + 1) * 32] for row in range(32)]


def is_terrain_empty(grid: list[list[int]]) -> bool:
    """Check if the terrain grid is all zeros (overworld mode)."""
    return all(val == 0 for row in grid for val in row)


def needs_chunk_lookup(ram_terrain: list[list[int]], px: int, py: int) -> bool:
    """Determine if we need ROM-based chunk lookup."""
    return px >= CHUNK_SIZE or py >= CHUNK_SIZE or is_terrain_empty(ram_terrain)


# ── ROM chunk system ──

def parse_matrix(matrix_path: str | Path) -> tuple[int, int, list | None, list]:
    """Parse a map matrix file. Returns (width, height, header_ids_2d_or_None, terrain_ids_2d)."""
    with open(matrix_path, "rb") as f:
        data = f.read()

    w, h = data[0], data[1]
    has_headers, has_heights = data[2], data[3]
    name_len = data[4]
    offset = 5 + name_len

    header_ids = None
    if has_headers:
        header_ids = []
        for row in range(h):
            row_ids = []
            for col in range(w):
                idx = offset + (row * w + col) * 2
                val = struct.unpack_from("<H", data, idx)[0]
                row_ids.append(val)
            header_ids.append(row_ids)
        offset += w * h * 2

    if has_heights:
        offset += w * h

    terrain_ids = []
    for row in range(h):
        row_ids = []
        for col in range(w):
            idx = offset + (row * w + col) * 2
            val = struct.unpack_from("<H", data, idx)[0]
            row_ids.append(val)
        terrain_ids.append(row_ids)

    return w, h, header_ids, terrain_ids


def find_matrix_for_map(map_id: int) -> tuple | None:
    """Search all matrix files for the given map_id.

    Returns (matrix_id, width, height, header_ids, terrain_ids) or None.
    """
    if not MATRIX_DIR.exists():
        return None

    for fname in sorted(os.listdir(MATRIX_DIR)):
        if not fname.endswith(".bin"):
            continue
        matrix_id = int(fname.split(".")[0])
        path = MATRIX_DIR / fname

        w, h, header_ids, terrain_ids = parse_matrix(path)
        if header_ids is None:
            continue

        for row in range(h):
            for col in range(w):
                if header_ids[row][col] == map_id:
                    return matrix_id, w, h, header_ids, terrain_ids

    return None


def load_terrain_from_rom(land_data_id: int) -> list[list[int]] | None:
    """Load a 32x32 terrain grid from a land_data ROM file."""
    path = LAND_DATA_DIR / f"{land_data_id:04d}.bin"
    if not path.exists():
        return None

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 0x10 + TERRAIN_SIZE:
        return None

    terrain_size = struct.unpack_from("<I", data, 0)[0]
    if terrain_size != TERRAIN_SIZE:
        return None

    grid = []
    for row in range(32):
        row_data = []
        for col in range(32):
            idx = 0x10 + (row * 32 + col) * 2
            val = struct.unpack_from("<H", data, idx)[0]
            row_data.append(val)
        grid.append(row_data)

    return grid


def resolve_chunk(map_id: int, global_x: int, global_y: int) -> tuple:
    """Resolve terrain for a global coordinate. Returns (grid, origin_x, origin_y, matrix_id) or (None, 0, 0, None)."""
    result = find_matrix_for_map(map_id)
    if result is None:
        return None, 0, 0, None

    matrix_id, w, h, header_ids, terrain_ids = result

    chunk_x = global_x // CHUNK_SIZE
    chunk_y = global_y // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0, None

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0, None

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y, matrix_id


def get_matrix_for_map(emu: "EmulatorClient", map_id: int) -> tuple | None:
    """Look up matrix data for a map via the zone header table.

    Returns (matrix_id, width, height, header_ids, terrain_ids) or None.
    Much faster than find_matrix_for_map() which scans all files.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None

    w, h, header_ids, terrain_ids = parse_matrix(matrix_path)
    return matrix_id, w, h, header_ids, terrain_ids


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


# Sign graphics IDs that auto-trigger dialogue when the player steps onto the
# tile directly south while facing north.
SIGN_GFX_IDS = {91, 93, 94, 95, 96}  # Map Signpost, Signboard, Arrow, Gym, Trainer Tips

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
) -> dict[tuple[int, int], int]:
    """BFS flood-fill from (start_x, start_y). Returns {(x,y): steps} for all reachable tiles."""
    dist: dict[tuple[int, int], int] = {(start_x, start_y): 0}
    queue: deque[tuple[int, int, int]] = deque([(start_x, start_y, 0)])

    while queue:
        x, y, d = queue.popleft()
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


def resolve_terrain_from_rom(emu: "EmulatorClient", map_id: int, px: int, py: int) -> tuple:
    """Resolve terrain from ROM via zone header → matrix → land_data.

    Works for both indoor (single-chunk) and overworld (multi-chunk) maps.
    Returns (grid, origin_x, origin_y, matrix_w, matrix_h) or
    (None, 0, 0, 1, 1) on failure.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None, 0, 0, 1, 1

    w, h, _header_ids, terrain_ids = parse_matrix(matrix_path)

    chunk_x = px // CHUNK_SIZE
    chunk_y = py // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0, 1, 1

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0, 1, 1

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y, w, h


# ── BDHC elevation system ──

def parse_bdhc(land_data_id: int) -> dict | None:
    """Parse BDHC (elevation plate) data from a land_data ROM file.

    Returns dict with points, normals, constants, plates — or None if no
    meaningful BDHC data exists.
    """
    path = LAND_DATA_DIR / f"{land_data_id:04d}.bin"
    if not path.exists():
        return None

    data = path.read_bytes()
    if len(data) < 0x10:
        return None

    map_props_size = struct.unpack_from("<I", data, 0x04)[0]
    map_model_size = struct.unpack_from("<I", data, 0x08)[0]
    bdhc_size = struct.unpack_from("<I", data, 0x0C)[0]

    if bdhc_size == 0:
        return None

    off = 0x0810 + map_props_size + map_model_size
    if off + 0x10 > len(data) or data[off:off + 4] != b"BDHC":
        return None

    points_count = struct.unpack_from("<H", data, off + 0x04)[0]
    normals_count = struct.unpack_from("<H", data, off + 0x06)[0]
    constants_count = struct.unpack_from("<H", data, off + 0x08)[0]
    plates_count = struct.unpack_from("<H", data, off + 0x0A)[0]

    p = off + 0x10
    points = []
    for _ in range(points_count):
        x = struct.unpack_from("<i", data, p)[0] / 4096.0
        z = struct.unpack_from("<i", data, p + 4)[0] / 4096.0
        points.append((x, z))
        p += 8

    normals = []
    for _ in range(normals_count):
        nx = struct.unpack_from("<i", data, p)[0] / 4096.0
        ny = struct.unpack_from("<i", data, p + 4)[0] / 4096.0
        nz = struct.unpack_from("<i", data, p + 8)[0] / 4096.0
        normals.append((nx, ny, nz))
        p += 12

    constants = []
    for _ in range(constants_count):
        d = struct.unpack_from("<i", data, p)[0] / 4096.0
        constants.append(d)
        p += 4

    plates = []
    for _ in range(plates_count):
        p1 = struct.unpack_from("<H", data, p)[0]
        p2 = struct.unpack_from("<H", data, p + 2)[0]
        ni = struct.unpack_from("<H", data, p + 4)[0]
        ci = struct.unpack_from("<H", data, p + 6)[0]
        plates.append({"p1": p1, "p2": p2, "normal": ni, "constant": ci})
        p += 8

    return {"points": points, "normals": normals, "constants": constants, "plates": plates}


def get_land_data_id(emu: "EmulatorClient", map_id: int, px: int, py: int) -> int | None:
    """Resolve the land_data file ID for a map position via zone header chain."""
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None

    w, h, _, terrain_ids = parse_matrix(matrix_path)
    chunk_x = px // CHUNK_SIZE
    chunk_y = py // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None

    land_id = terrain_ids[chunk_y][chunk_x]
    return None if land_id == 0xFFFF else land_id


def read_player_height(emu: "EmulatorClient") -> float:
    """Read the player's current Y height from MapObject[0].pos.y (fx32)."""
    from renegade_mcp.addresses import addr
    raw = emu.read_memory(addr("OBJ_ARRAY_FPX_BASE") + 4, size="long")
    if raw >= 0x80000000:
        raw -= 0x100000000
    return raw / 4096.0


def _tile_to_bdhc(col: int, row: int) -> tuple[float, float]:
    """Convert tile center to BDHC coordinate space (origin = map center)."""
    return (col + 0.5) * 16 - 256, (row + 0.5) * 16 - 256


def analyze_elevation(bdhc: dict, terrain: list[list[int]]) -> dict | None:
    """Analyze BDHC data to build per-tile elevation levels.

    Returns None for flat maps (single height). Otherwise returns dict with
    level_map, ramp_tiles, ramps, and levels for rendering.
    """
    plates = bdhc["plates"]
    pts = bdhc["points"]
    norms = bdhc["normals"]
    consts = bdhc["constants"]

    # Step 1: Collect discrete heights from flat plates only
    flat_heights: set[int] = set()
    for plate in plates:
        nx, ny, nz = norms[plate["normal"]]
        if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny) > 0.01:
            d = consts[plate["constant"]]
            flat_heights.add(round(-d / ny))

    if len(flat_heights) <= 1:
        return None

    sorted_heights = sorted(flat_heights)
    h2l = {h: i for i, h in enumerate(sorted_heights)}

    # Step 2: Map tiles to levels from flat plates
    level_map: dict[tuple[int, int], list[int]] = {}

    for row in range(32):
        for col in range(32):
            if terrain[row][col] & 0x8000:
                continue
            x, z = _tile_to_bdhc(col, row)
            levels: set[int] = set()
            for plate in plates:
                x1, z1 = pts[plate["p1"]]
                x2, z2 = pts[plate["p2"]]
                if not (min(x1, x2) <= x <= max(x1, x2) and min(z1, z2) <= z <= max(z1, z2)):
                    continue
                nx, ny, nz = norms[plate["normal"]]
                if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny) > 0.01:
                    d = consts[plate["constant"]]
                    h = round(-d / ny)
                    if h in h2l:
                        levels.add(h2l[h])
            if levels:
                level_map[(col, row)] = sorted(levels)

    # Step 3: Identify ramp plates and mark tiles
    ramp_tiles: dict[tuple[int, int], dict] = {}
    ramps: list[dict] = []

    for plate in plates:
        nx, ny, nz = norms[plate["normal"]]
        if abs(nx) < 0.01 and abs(nz) < 0.01:
            continue
        if abs(ny) < 0.01:
            continue

        x1, z1 = pts[plate["p1"]]
        x2, z2 = pts[plate["p2"]]
        d = consts[plate["constant"]]

        # Heights at plate corners to find connected levels
        corners = [
            (min(x1, x2), min(z1, z2)), (min(x1, x2), max(z1, z2)),
            (max(x1, x2), min(z1, z2)), (max(x1, x2), max(z1, z2)),
        ]
        corner_heights = [round(-(nx * cx + nz * cz + d) / ny) for cx, cz in corners]
        h_max, h_min = max(corner_heights), min(corner_heights)

        from_level = h2l.get(h_max)
        to_level = h2l.get(h_min)
        if from_level is None or to_level is None:
            continue

        direction = ("south" if nz > 0 else "north") if abs(nz) >= abs(nx) else ("east" if nx > 0 else "west")

        col_min = int((min(x1, x2) + 256) / 16)
        col_max = int((max(x1, x2) + 256) / 16)
        row_min = int((min(z1, z2) + 256) / 16)
        row_max = int((max(z1, z2) + 256) / 16)

        ramp_info = {
            "ramp_index": len(ramps),
            "col_range": (col_min, col_max),
            "row_range": (row_min, row_max),
            "from_level": from_level,
            "to_level": to_level,
            "direction": direction,
        }
        ramps.append(ramp_info)

        for r in range(row_min, row_max):
            for c in range(col_min, col_max):
                if not (terrain[r][c] & 0x8000):
                    ramp_tiles[(c, r)] = ramp_info

    levels_info = [{"level": h2l[h], "height": h} for h in sorted_heights]

    return {
        "level_map": level_map,
        "ramp_tiles": ramp_tiles,
        "ramps": ramps,
        "levels": levels_info,
        "height_to_level": h2l,
    }


# ── Viewport helpers ──

def _compute_viewport_bounds(
    px: int, py: int,
    matrix_w: int, matrix_h: int,
    terrain_ids: list[list[int]],
    terrain: list[list[int]],
    origin_x: int, origin_y: int,
    objects: list[dict],
    chunked: bool,
    viewport_size: int = 32,
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

    For each active entry, reads the MapObject struct header to get graphicsID,
    movementType, localID, trainerType, and script — enabling identification of
    what each object actually is (NPC, item ball, briefcase, boulder, etc.).
    """
    from renegade_mcp.addresses import addr
    obj_fpx_base = addr("OBJ_ARRAY_FPX_BASE")
    obj_struct_base = obj_fpx_base - 0x70  # True start of MapObject[0]

    objects = []
    consecutive_empty = 0

    for i in range(OBJ_MAX_ENTRIES):
        struct_base = obj_struct_base + (i * OBJ_STRIDE)

        # Read struct header first: status, unk, localID, mapID, graphicsID,
        # movementType, trainerType, flag, script (9 longs from struct base)
        header = emu.read_memory_range(struct_base, size="long", count=9)
        status = header[0] if header else 0

        # Use status field for empty detection — position (0,0) doesn't mean
        # empty (some objects are loaded at origin before being placed)
        if status == 0:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            continue
        consecutive_empty = 0

        fpx_addr = obj_fpx_base + (i * OBJ_STRIDE)
        fpy_addr = fpx_addr + 8

        fpx = emu.read_memory(fpx_addr, size="long")
        fpy = emu.read_memory(fpy_addr, size="long")

        tile_x = (fpx >> 16) & 0xFFFF
        tile_y = (fpy >> 16) & 0xFFFF

        if tile_x > 10000 or tile_y > 10000:
            continue

        obj: dict[str, Any] = {
            "index": i, "x": tile_x, "y": tile_y, "fpx": fpx, "fpy": fpy,
        }

        if len(header) >= 9:
            gfx_id = header[4]
            obj["local_id"] = header[2]
            obj["graphics_id"] = gfx_id
            obj["name"] = GFX_NAMES.get(gfx_id, f"Unknown ({gfx_id})")
            obj["movement_type"] = MOVEMENT_TYPES.get(header[5], f"type_{header[5]}")
            obj["trainer_type"] = header[6]
            obj["script"] = header[8]

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

    Symbols: ^v<> player, A-Za-z NPCs, # wall, _ walkable, . void,
    ≈ water, " grass, 0-9 elevation, /\\ ramps, ][ directional blocks.
    Hex behaviors mapped to single chars with a key when present.

    The terrain grid IS the viewport — render it all, no cropping needed.
    Objects' local_x/local_y are viewport-relative. Elevation keys are
    also viewport-relative when provided.
    """
    # 1-char behavior symbols for common hex behaviors
    _BEHAVIOR_CHAR: dict[int, str] = {
        0x02: '"', 0x03: '"',  # grass
        0x10: '≈', 0x13: '≈', 0x15: '≈',  # water
        0x20: '=', 0x21: ',',  # ice, sand
        0x30: ']', 0x31: '[',  # directional blocks
        0x38: 'v', 0x39: '^', 0x3A: '<', 0x3B: '>',  # ledges (reuse arrows)
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
            elif behavior == 0x00:
                ch = '_'
            elif behavior == 0x08:
                ch = ' '
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


def view_map(emu: EmulatorClient, level: int = -1) -> dict[str, Any]:
    """Get player-centered ASCII map with terrain, NPCs, and warps.

    Indoor/small maps: compact content-fitted rendering (no void padding).
    Overworld maps: 32x32 viewport centered on the player, loading adjacent
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
            return {"error": "Could not resolve map chunk", "map": "", "player": {}, "objects": []}
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
            return {"error": "Could not resolve terrain", "map": "", "player": {}, "objects": []}
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
    elev_str = f" L{player_elev}" if elevation and player_elev is not None else ""
    header = f"Map {map_id} ({px},{py}) {facing_name}{elev_str}  origin:({vp_x},{vp_y}) {vp_w}x{vp_h}"

    # Object list (compact: index, name, position, trainer status)
    obj_info = []
    for obj in visible_objects:
        idx = obj["index"]
        if idx == 0:
            continue  # Player is already in the player field
        name = obj.get("name", "")
        entry: dict[str, Any] = {
            "index": idx,
            "x": obj["x"], "y": obj["y"],
        }
        if name:
            entry["name"] = name
        if obj.get("trainer_type", 0) > 0:
            from renegade_mcp.trainer import trainer_id_from_script, is_trainer_defeated
            tid = trainer_id_from_script(obj.get("script", 0))
            if tid is not None:
                entry["trainer"] = True
                entry["trainer_id"] = tid
                entry["defeated"] = is_trainer_defeated(emu, tid)
        obj_info.append(entry)

    # BFS flood-fill from player for reachability + step counts
    npc_positions: set[tuple[int, int]] = set()
    for obj in visible_objects:
        if obj["index"] == 0:
            continue
        npc_positions.add((obj["local_x"], obj["local_y"]))

    reachable_tiles = _bfs_flood_fill(
        vp_terrain, player_grid_x, player_grid_y,
        npc_positions, vp_w, vp_h,
    )

    # Annotate each object with reachability (min BFS steps to any adjacent tile)
    for o in obj_info:
        lx, ly = o["x"] - vp_x, o["y"] - vp_y
        best_steps = None
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            adj = (lx + dx, ly + dy)
            if adj in reachable_tiles:
                s = reachable_tiles[adj]
                if best_steps is None or s < best_steps:
                    best_steps = s
        if best_steps is not None:
            o["reachable"] = True
            o["steps"] = best_steps
        else:
            o["reachable"] = False
            o["distance"] = abs(o["x"] - px) + abs(o["y"] - py)

    # Sort: reachable first (by steps), then unreachable (by Manhattan distance)
    obj_info.sort(key=lambda o: (not o.get("reachable", False), o.get("steps", 0) if o.get("reachable") else o.get("distance", 0)))

    # Warp destinations within viewport
    all_warps = read_warps_from_rom(emu, map_id)
    warp_info = []
    for w in all_warps:
        if vp_x <= w["x"] < vp_x + vp_w and vp_y <= w["y"] < vp_y + vp_h:
            dest = lookup_map_name(w["dest_map"])
            warp_info.append({
                "x": w["x"], "y": w["y"],
                "dest": dest["name"],
            })

    result: dict[str, Any] = {
        "map": header + "\n\n" + map_str,
        "map_id": map_id,
        "player": {
            "x": px, "y": py,
            "facing": facing_name,
            "grid_x": player_grid_x,
            "grid_y": player_grid_y,
        },
        "objects": obj_info,
        "warps": warp_info,
    }
    if elevation is not None and player_elev is not None:
        result["player"]["elevation"] = player_elev
    return result
