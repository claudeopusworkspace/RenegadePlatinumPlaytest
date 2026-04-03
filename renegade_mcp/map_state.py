"""Terrain, dynamic objects, and player state reading + ASCII map rendering.

Terrain is always loaded from ROM via the zone header → matrix → land_data
chain. RAM terrain at 0x0231D1E4 is unreliable (garbled after menu
interactions indoors) and only used as a last-resort fallback.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from renegade_mcp.map_names import lookup_map_name

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Memory addresses ──
TERRAIN_ADDR = 0x0231D1E4
TERRAIN_SIZE = 2048  # 32*32*2

PLAYER_POS_BASE = 0x0227F450
# Player facing: MapObject[0].facingDir (0x022A1A38 + 0x28)
PLAYER_FACING_ADDR = 0x022A1A60
# Player height: MapObject[0].pos.y (fx32, 0x022A1A38 + 0x74)
PLAYER_POS_Y_FX32 = 0x022A1AAC

# Zone header table in ARM9 (Platinum US / Renegade Platinum).
# Each entry is 24 bytes; first u16 is the matrix_id for that zone.
ZONE_HEADER_BASE = 0x020E601E
ZONE_HEADER_STRIDE = 24

OBJ_ARRAY_FPX_BASE = 0x022A1AA8
OBJ_STRUCT_BASE = OBJ_ARRAY_FPX_BASE - 0x70  # True start of MapObject[0]
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
    0x80: "counter", 0xA9: "tree_tile",
}

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
    vals = emu.read_memory_range(TERRAIN_ADDR, size="short", count=1024)
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


def resolve_terrain_from_rom(emu: "EmulatorClient", map_id: int, px: int, py: int) -> tuple:
    """Resolve terrain from ROM via zone header → matrix → land_data.

    Works for both indoor (single-chunk) and overworld (multi-chunk) maps.
    Returns (grid, origin_x, origin_y) or (None, 0, 0) on failure.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None, 0, 0

    w, h, _header_ids, terrain_ids = parse_matrix(matrix_path)

    chunk_x = px // CHUNK_SIZE
    chunk_y = py // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y


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
    raw = emu.read_memory(PLAYER_POS_Y_FX32, size="long")
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


# ── Dynamic objects ──

def read_objects(emu: EmulatorClient) -> list[dict[str, Any]]:
    """Scan the overworld object array and return active objects with identity info.

    For each active entry, reads the MapObject struct header to get graphicsID,
    movementType, localID, trainerType, and script — enabling identification of
    what each object actually is (NPC, item ball, briefcase, boulder, etc.).
    """
    objects = []
    consecutive_empty = 0

    for i in range(OBJ_MAX_ENTRIES):
        struct_base = OBJ_STRUCT_BASE + (i * OBJ_STRIDE)

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

        fpx_addr = OBJ_ARRAY_FPX_BASE + (i * OBJ_STRIDE)
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
    map_id = emu.read_memory(PLAYER_POS_BASE, size="long")
    x = emu.read_memory(PLAYER_POS_BASE + 8, size="long")
    y = emu.read_memory(PLAYER_POS_BASE + 12, size="long")
    facing = emu.read_memory(PLAYER_FACING_ADDR, size="long")
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
    terrain, origin_x, origin_y = resolve_terrain_from_rom(emu, map_id, px, py)
    chunked = origin_x > 0 or origin_y > 0

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
    """Render an ASCII map combining terrain and dynamic objects.

    When elevation data is provided (from analyze_elevation), passable tiles
    show their height level number instead of '.' or '_', ramp tiles show
    descent direction, and bridge tiles show both levels.

    When filter_level is set, only tiles at that level are shown normally;
    tiles at other levels are dimmed to '~'.
    """
    obj_at = {}
    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
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

    # Unpack elevation data
    level_map = elevation["level_map"] if elevation else {}
    ramp_tiles = elevation["ramp_tiles"] if elevation else {}

    # Find map bounds
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
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
            min_row = min(min_row, ly)
            max_row = max(max_row, ly)
            min_col = min(min_col, lx)
            max_col = max(max_col, lx)

    min_row = max(0, min_row - 1)
    max_row = min(31, max_row + 1)
    min_col = max(0, min_col - 1)
    max_col = min(31, max_col + 1)

    lines = []

    header = "     "
    for col in range(min_col, max_col + 1):
        header += f"{col:>3}"
    lines.append(header)
    lines.append("    " + "-" * ((max_col - min_col + 1) * 3 + 1))

    behaviors_seen = {}

    for row in range(min_row, max_row + 1):
        line = f"{row:>3} |"
        for col in range(min_col, max_col + 1):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            key = (col, row)

            # Level filter: dim tiles not at the requested level
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
                cell = "  ~"
            elif key in obj_at:
                cell = f"  {obj_at[key]}"
            elif is_blocked and behavior == 0:
                cell = "  #"
            elif is_blocked and behavior != 0:
                cell = f" {behavior:02x}"
                behaviors_seen[behavior] = "blocked"
            elif elevation and key in ramp_tiles:
                # Ramp tile — show descent direction
                ri = ramp_tiles[key]
                d = ri["direction"]
                # Dim ramps that don't connect to filtered level
                if filter_level is not None and filter_level not in (ri["from_level"], ri["to_level"]):
                    cell = "  ~"
                else:
                    cell = "  \\" if d in ("south", "east") else "  /"
            elif elevation and key in level_map and len(level_map[key]) > 1:
                # Bridge — show upper level with bridge marker
                cell = f" {level_map[key][-1]}*"
            elif elevation and behavior == 0x30:
                cell = "  ]"  # blocks eastward movement
            elif elevation and behavior == 0x31:
                cell = "  ["  # blocks westward movement
            elif elevation and key in level_map and (val == 0 or behavior in (0x00, 0x08)):
                # Plain ground/cave/void tile with elevation → show level number
                cell = f"  {level_map[key][0]}"
            elif val == 0:
                cell = "  ."
            elif behavior == 0x00:
                cell = "  _"
            elif behavior == 0x08:
                cell = "   "
            else:
                cell = f" {behavior:02x}"
                behaviors_seen[behavior] = "passable"

            line += cell
        lines.append(line)

    # Legend
    lines.append("")
    lines.append("Legend:")
    lines.append("  ^v<> = player (facing direction)")
    lines.append("  A-Z, a-z = NPC/dynamic object")
    if elevation:
        lines.append("  0-9  = elevation level (passable)  #  = wall")
        lines.append("  / \\  = ramp (descent direction)    n* = bridge (level n, passable below)")
        lines.append("  ] [  = directional block (can't move east/west respectively)")
        if filter_level is not None:
            lines.append(f"  ~    = other level (filtered to L{filter_level})")
    else:
        lines.append("  .    = void  #  = wall  _  = walkable ground")
    lines.append("  xx   = tile behavior (hex)")

    if behaviors_seen:
        lines.append("")
        lines.append("Behaviors:")
        for beh, passability in sorted(behaviors_seen.items()):
            name = BEHAVIORS.get(beh, "unknown")
            lines.append(f"  {beh:02x} = {passability} ({name})")

    # Elevation summary
    if elevation:
        lines.append("")
        lines.append(f"Elevation: {len(elevation['levels'])} levels")
        for lv in elevation["levels"]:
            marker = " <- YOU" if player_level is not None and lv["level"] == player_level else ""
            lines.append(f"  L{lv['level']} = h{lv['height']}{marker}")
        if elevation["ramps"]:
            ramp_strs = []
            for r in elevation["ramps"]:
                cr = r["col_range"]
                rr = r["row_range"]
                cols = f"{cr[0]}" if cr[1] - cr[0] == 1 else f"{cr[0]}-{cr[1] - 1}"
                rows = f"{rr[0]}" if rr[1] - rr[0] == 1 else f"{rr[0]}-{rr[1] - 1}"
                ramp_strs.append(f"({cols},{rows})L{r['from_level']}->L{r['to_level']}")
            lines.append("  Ramps: " + "  ".join(ramp_strs))

    return "\n".join(lines)


def view_map(emu: EmulatorClient, level: int = -1) -> dict[str, Any]:
    """Get full map view with ASCII rendering and metadata.

    Args:
        level: Filter to show only this elevation level (-1 = show all).
    """
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not resolve map chunk", "map": "", "player": {}, "objects": []}

    facing_name = FACING_NAMES.get(state["facing"], "?")

    # Load elevation data from BDHC
    elevation = None
    player_level = None
    land_id = get_land_data_id(emu, state["map_id"], state["px"], state["py"])
    if land_id is not None:
        bdhc = parse_bdhc(land_id)
        if bdhc is not None:
            elevation = analyze_elevation(bdhc, state["terrain"])
            if elevation is not None:
                player_h = round(read_player_height(emu))
                player_level = elevation["height_to_level"].get(player_h)

    filter_level = level if level >= 0 else None

    map_str = render_map(
        state["terrain"], state["objects"],
        state["local_px"], state["local_py"], state["facing"],
        elevation=elevation, player_level=player_level,
        filter_level=filter_level,
    )

    # Build header
    elev_str = ""
    if elevation and player_level is not None:
        elev_str = f" — Level {player_level} (h={round(read_player_height(emu))})"
    if state["chunked"]:
        chunk_cx = state["px"] // CHUNK_SIZE
        chunk_cy = state["py"] // CHUNK_SIZE
        header = (
            f"Map {state['map_id']} — Player at ({state['px']}, {state['py']}) "
            f"facing {facing_name}{elev_str}\n"
            f"Chunk ({chunk_cx}, {chunk_cy}) — "
            f"origin ({state['origin_x']}, {state['origin_y']}) — "
            f"local ({state['local_px']}, {state['local_py']})"
        )
    else:
        header = f"Map {state['map_id']} — Player at ({state['px']}, {state['py']}) facing {facing_name}{elev_str}"

    # Object list
    obj_info = []
    for obj in state["objects"]:
        idx = obj["index"]
        if 1 <= idx <= 26:
            letter = chr(ord("A") + idx - 1)
        elif 27 <= idx <= 52:
            letter = chr(ord("a") + idx - 27)
        else:
            letter = f"#{idx}"
        name = obj.get("name", "")
        if idx == 0:
            label = "PLAYER"
        elif name:
            label = f"{name} ({letter})"
        else:
            label = f"NPC {letter}"
        entry: dict[str, Any] = {
            "index": idx,
            "label": label,
            "x": obj["x"], "y": obj["y"],
            "local_x": obj["local_x"], "local_y": obj["local_y"],
        }
        if "movement_type" in obj:
            entry["movement"] = obj["movement_type"]
        if obj.get("trainer_type", 0) > 0:
            entry["trainer"] = True
            # Check defeat flag via script field → trainer ID
            from renegade_mcp.trainer import trainer_id_from_script, is_trainer_defeated
            tid = trainer_id_from_script(obj.get("script", 0))
            if tid is not None:
                entry["trainer_id"] = tid
                entry["defeated"] = is_trainer_defeated(emu, tid)
                if entry["defeated"]:
                    entry["label"] += " [defeated]"
        obj_info.append(entry)

    # Warp destinations within displayed grid
    origin_x = state["origin_x"]
    origin_y = state["origin_y"]
    terrain = state["terrain"]
    grid_h = len(terrain)
    grid_w = len(terrain[0]) if grid_h > 0 else 0

    all_warps = read_warps_from_rom(emu, state["map_id"])
    warp_info = []
    for w in all_warps:
        lx = w["x"] - origin_x
        ly = w["y"] - origin_y
        if 0 <= lx < grid_w and 0 <= ly < grid_h:
            dest = lookup_map_name(w["dest_map"])
            warp_info.append({
                "x": w["x"], "y": w["y"],
                "dest_name": dest["name"],
                "dest_map_id": w["dest_map"],
            })

    result = {
        "map": header + "\n\n" + map_str,
        "map_id": state["map_id"],
        "player": {
            "x": state["px"], "y": state["py"],
            "local_x": state["local_px"], "local_y": state["local_py"],
            "facing": facing_name,
        },
        "origin": {"x": state["origin_x"], "y": state["origin_y"]},
        "chunked": state["chunked"],
        "objects": obj_info,
        "warps": warp_info,
    }
    if elevation is not None:
        result["elevation"] = {
            "levels": elevation["levels"],
            "player_level": player_level,
            "ramps": elevation["ramps"],
        }
    return result
