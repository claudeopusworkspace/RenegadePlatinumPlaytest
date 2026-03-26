"""Shared game state reading — terrain, objects, player position.

Used by map_with_objects.py (visualization) and navigate.py (pathfinding).
All functions take an `emu` connection from desmume_mcp.client.connect().
"""

import os
import struct
import sys

sys.path.insert(0, "/workspace/DesmumeMCP")

# === Memory addresses ===
TERRAIN_ADDR = 0x0231D1E4     # 32x32 grid of u16, row-major
TERRAIN_SIZE = 2048            # 32*32*2

PLAYER_POS_BASE = 0x0227F450  # map_id(+0), x(+8), y(+12)
PLAYER_FACING_ADDR = 0x02335346

# Object array: each entry is 0x128 bytes apart
OBJ_ARRAY_FPX_BASE = 0x022A1AA8  # Entry 0's fixed-point x
OBJ_STRIDE = 0x128
OBJ_MAX_ENTRIES = 16

SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"

# === ROM data paths ===
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMDATA_DIR = os.path.join(PROJECT_ROOT, "romdata")
LAND_DATA_DIR = os.path.join(ROMDATA_DIR, "land_data")
MATRIX_DIR = os.path.join(ROMDATA_DIR, "map_matrix")
CHUNK_SIZE = 32

# === Display constants ===
FACING_ARROWS = {0: "^", 1: "v", 2: "<", 3: ">"}
FACING_NAMES = {0: "up", 1: "down", 2: "left", 3: "right"}

BEHAVIORS = {
    0x00: "ground",
    0x02: "tall_grass",
    0x03: "very_tall_grass",
    0x08: "cave_floor",
    0x10: "water",
    0x13: "waterfall",
    0x15: "sea",
    0x20: "ice",
    0x21: "sand",
    0x38: "ledge_S",
    0x39: "ledge_N",
    0x3A: "ledge_W",
    0x3B: "ledge_E",
    0x5E: "stairs_up",
    0x5F: "stairs_down",
    0x62: "warp",
    0x65: "door",
    0x69: "door2",
    0x6B: "warp3",
    0x80: "counter",
    0xA9: "tree_tile",
}


# === Terrain reading ===

def read_terrain_from_ram(emu):
    """Read the 32x32 terrain collision grid from RAM."""
    vals = emu.read_memory_range(TERRAIN_ADDR, size="short", count=1024)
    grid = []
    for row in range(32):
        grid.append(vals[row * 32:(row + 1) * 32])
    return grid


def is_terrain_empty(grid):
    """Check if the terrain grid is all zeros (overworld mode)."""
    for row in grid:
        for val in row:
            if val != 0:
                return False
    return True


def needs_chunk_lookup(ram_terrain, px, py):
    """Determine if we need ROM-based chunk lookup."""
    if px >= CHUNK_SIZE or py >= CHUNK_SIZE:
        return True
    return is_terrain_empty(ram_terrain)


# === ROM chunk system ===

def parse_matrix(matrix_path):
    """Parse a map matrix file.

    Returns (width, height, header_ids_2d_or_None, terrain_ids_2d).
    """
    with open(matrix_path, "rb") as f:
        data = f.read()

    w = data[0]
    h = data[1]
    has_headers = data[2]
    has_heights = data[3]
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


def find_matrix_for_map(map_id):
    """Search all matrix files to find which one contains the given map_id.

    Returns (matrix_id, width, height, header_ids, terrain_ids) or None.
    """
    if not os.path.exists(MATRIX_DIR):
        return None

    for fname in sorted(os.listdir(MATRIX_DIR)):
        if not fname.endswith(".bin"):
            continue
        matrix_id = int(fname.split(".")[0])
        path = os.path.join(MATRIX_DIR, fname)

        w, h, header_ids, terrain_ids = parse_matrix(path)

        if header_ids is None:
            continue

        for row in range(h):
            for col in range(w):
                if header_ids[row][col] == map_id:
                    return matrix_id, w, h, header_ids, terrain_ids

    return None


def load_terrain_from_rom(land_data_id):
    """Load a 32x32 terrain grid from a land_data ROM file."""
    path = os.path.join(LAND_DATA_DIR, f"{land_data_id:04d}.bin")
    if not os.path.exists(path):
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


def resolve_chunk(map_id, global_x, global_y):
    """Given a map ID and global coords, find the chunk and load its terrain.

    Returns (terrain_grid, chunk_origin_x, chunk_origin_y, matrix_id) or
    (None, 0, 0, None) on failure.
    """
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


# === Dynamic objects ===

def read_objects(emu):
    """Scan the overworld object array and return active objects."""
    objects = []
    consecutive_empty = 0

    for i in range(OBJ_MAX_ENTRIES):
        fpx_addr = OBJ_ARRAY_FPX_BASE + (i * OBJ_STRIDE)
        fpy_addr = fpx_addr + 8

        fpx = emu.read_memory(fpx_addr, size="long")
        fpy = emu.read_memory(fpy_addr, size="long")

        tile_x = (fpx >> 16) & 0xFFFF
        tile_y = (fpy >> 16) & 0xFFFF

        if fpx == 0 and fpy == 0:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            continue

        if tile_x > 10000 or tile_y > 10000:
            consecutive_empty = 0
            continue

        consecutive_empty = 0
        objects.append({
            "index": i,
            "x": tile_x,
            "y": tile_y,
            "fpx": fpx,
            "fpy": fpy,
        })

    return objects


# === Player state ===

def read_player_state(emu):
    """Read player position and facing direction."""
    map_id = emu.read_memory(PLAYER_POS_BASE, size="long")
    x = emu.read_memory(PLAYER_POS_BASE + 8, size="long")
    y = emu.read_memory(PLAYER_POS_BASE + 12, size="long")

    facing = emu.read_memory(PLAYER_FACING_ADDR, size="byte")

    return map_id, x, y, facing


# === High-level: get current map terrain + objects ===

def get_map_state(emu):
    """Read the full map state: terrain grid, objects, player position.

    Returns a dict with:
        terrain: 32x32 grid of u16 values
        objects: list of object dicts with local_x, local_y added
        map_id, px, py, facing: player state
        origin_x, origin_y: chunk origin (0,0 for indoor maps)
        chunked: bool — whether this is a multi-chunk map
    """
    map_id, px, py, facing = read_player_state(emu)
    ram_terrain = read_terrain_from_ram(emu)
    objects = read_objects(emu)
    chunked = needs_chunk_lookup(ram_terrain, px, py)

    if chunked:
        terrain, origin_x, origin_y, matrix_id = resolve_chunk(map_id, px, py)
        if terrain is None:
            return None
        local_px = px - origin_x
        local_py = py - origin_y
        for obj in objects:
            obj["local_x"] = obj["x"] - origin_x
            obj["local_y"] = obj["y"] - origin_y
    else:
        terrain = ram_terrain
        origin_x, origin_y = 0, 0
        local_px, local_py = px, py
        for obj in objects:
            obj["local_x"] = obj["x"]
            obj["local_y"] = obj["y"]

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
