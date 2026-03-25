#!/usr/bin/env python3
"""Render the current map with terrain, dynamic objects, and player state.

Connects to the running emulator via the IPC bridge and reads everything
automatically — no manual arguments needed.

For indoor maps, reads terrain directly from RAM.
For overworld maps (where RAM terrain is empty), loads terrain from ROM
data using the map matrix/chunk system.

Usage:
    python3 scripts/map_with_objects.py [output_file]

If output_file is omitted, prints to stdout.
"""
import os
import struct
import sys

sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect

# === Memory addresses ===
TERRAIN_ADDR = 0x0231D1E4     # 32x32 grid of u16, row-major
TERRAIN_SIZE = 2048            # 32*32*2

PLAYER_POS_BASE = 0x0227F450  # map_id(+0), x(+8), y(+12)
PLAYER_FACING_ADDR = 0x02335346

# Object array: each entry is 0x128 bytes apart
# Fixed-point x at offset 0x022A1AA8 for entry 0 (player)
OBJ_ARRAY_FPX_BASE = 0x022A1AA8  # Entry 0's fixed-point x
OBJ_STRIDE = 0x128
OBJ_MAX_ENTRIES = 16  # Scan up to 16 entries

SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"

# === ROM data paths ===
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMDATA_DIR = os.path.join(PROJECT_ROOT, "romdata")
LAND_DATA_DIR = os.path.join(ROMDATA_DIR, "land_data")
MATRIX_DIR = os.path.join(ROMDATA_DIR, "map_matrix")
CHUNK_SIZE = 32  # Tiles per chunk edge

# Facing direction arrows and names
FACING_ARROWS = {0: "^", 1: "v", 2: "<", 3: ">"}
FACING_NAMES = {0: "up", 1: "down", 2: "left", 3: "right"}

# Tile behavior names
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


def parse_matrix(matrix_path):
    """Parse a map matrix file. Returns (width, height, terrain_ids_2d)."""
    with open(matrix_path, "rb") as f:
        data = f.read()

    w = data[0]
    h = data[1]
    has_headers = data[2]
    has_heights = data[3]
    name_len = data[4]
    offset = 5 + name_len

    # Skip header IDs if present
    if has_headers:
        offset += w * h * 2
    # Skip height values if present
    if has_heights:
        offset += w * h

    # Read terrain file IDs
    terrain_ids = []
    for row in range(h):
        row_ids = []
        for col in range(w):
            idx = offset + (row * w + col) * 2
            val = struct.unpack_from("<H", data, idx)[0]
            row_ids.append(val)
        terrain_ids.append(row_ids)

    return w, h, terrain_ids


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


def resolve_overworld_chunk(global_x, global_y, matrix_id=0):
    """Given global coords, find the chunk and load its terrain from ROM.

    Returns (terrain_grid, chunk_origin_x, chunk_origin_y) or (None, 0, 0).
    """
    matrix_path = os.path.join(MATRIX_DIR, f"{matrix_id:04d}.bin")
    if not os.path.exists(matrix_path):
        return None, 0, 0

    w, h, terrain_ids = parse_matrix(matrix_path)

    chunk_x = global_x // CHUNK_SIZE
    chunk_y = global_y // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y


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

        # Skip sentinel entries (0xFFFF)
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


def read_player_state(emu):
    """Read player position and facing direction."""
    map_id = emu.read_memory(PLAYER_POS_BASE, size="long")
    x = emu.read_memory(PLAYER_POS_BASE + 8, size="long")
    y = emu.read_memory(PLAYER_POS_BASE + 12, size="long")

    facing = emu.read_memory(PLAYER_FACING_ADDR, size="byte")

    return map_id, x, y, facing


def render_map(terrain, objects, player_local_x, player_local_y, facing):
    """Render an ASCII map combining terrain and dynamic objects.

    All coordinates are expected in chunk-local space (0-31).
    """

    # Build object lookup: (x, y) -> label
    obj_at = {}
    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
            if obj["index"] == 0:
                obj_at[(lx, ly)] = FACING_ARROWS.get(facing, "P")
            else:
                obj_at[(lx, ly)] = chr(ord("A") + obj["index"] - 1)

    # Find map bounds (non-zero terrain region)
    min_row, max_row = 31, 0
    min_col, max_col = 31, 0
    for row in range(32):
        for col in range(32):
            val = terrain[row][col]
            if val != 0:
                min_row = min(min_row, row)
                max_row = max(max_row, row)
                min_col = min(min_col, col)
                max_col = max(max_col, col)

    # Include object positions in bounds
    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
            min_row = min(min_row, ly)
            max_row = max(max_row, ly)
            min_col = min(min_col, lx)
            max_col = max(max_col, lx)

    # Add 1 tile padding
    min_row = max(0, min_row - 1)
    max_row = min(31, max_row + 1)
    min_col = max(0, min_col - 1)
    max_col = min(31, max_col + 1)

    lines = []

    # Header
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

            # Dynamic object takes precedence
            if (col, row) in obj_at:
                cell = f"  {obj_at[(col, row)]}"
            elif val == 0:
                cell = "  ."
            elif is_blocked and behavior == 0:
                cell = "  #"
            elif is_blocked and behavior != 0:
                cell = f" {behavior:02x}"
                behaviors_seen[behavior] = "blocked"
            elif behavior == 0x00:
                cell = "  _"
            elif behavior == 0x08:
                cell = "   "  # indoor walkable floor
            else:
                cell = f" {behavior:02x}"
                behaviors_seen[behavior] = "passable"

            line += cell
        lines.append(line)

    # Legend
    lines.append("")
    lines.append("Legend:")
    lines.append("  ^v<> = player (facing direction)")
    lines.append("  A-Z  = NPC/dynamic object (A=obj1, B=obj2, ...)")
    lines.append("  .    = void")
    lines.append("  #    = wall")
    lines.append("  _    = walkable ground (outdoor)")
    lines.append("  (space) = walkable floor (indoor)")
    lines.append("  xx   = tile behavior (hex)")

    if behaviors_seen:
        lines.append("")
        lines.append("Behaviors:")
        for beh, passability in sorted(behaviors_seen.items()):
            name = BEHAVIORS.get(beh, "unknown")
            lines.append(f"  {beh:02x} = {passability} ({name})")

    return "\n".join(lines)


def main():
    emu = connect(SOCKET_PATH)

    map_id, px, py, facing = read_player_state(emu)
    ram_terrain = read_terrain_from_ram(emu)
    objects = read_objects(emu)

    facing_name = FACING_NAMES.get(facing, "?")
    overworld = is_terrain_empty(ram_terrain)

    if overworld:
        terrain, origin_x, origin_y = resolve_overworld_chunk(px, py)
        if terrain is None:
            print(f"Map {map_id} — Player at ({px}, {py}) — "
                  f"could not load overworld chunk", file=sys.stderr)
            sys.exit(1)

        local_px = px - origin_x
        local_py = py - origin_y
        chunk_cx = px // CHUNK_SIZE
        chunk_cy = py // CHUNK_SIZE

        # Convert objects to local coords, keep only those in this chunk
        local_objects = []
        for obj in objects:
            lx = obj["x"] - origin_x
            ly = obj["y"] - origin_y
            obj["local_x"] = lx
            obj["local_y"] = ly
            obj["global_x"] = obj["x"]
            obj["global_y"] = obj["y"]
            local_objects.append(obj)

        header = (f"Map {map_id} — Player at ({px}, {py}) facing {facing_name}\n"
                  f"Overworld chunk ({chunk_cx}, {chunk_cy}) — "
                  f"origin ({origin_x}, {origin_y}) — "
                  f"local ({local_px}, {local_py})\n")
        output = header + "\n"
        output += render_map(terrain, local_objects, local_px, local_py, facing)

        # Append object list with both local and global coords
        output += "\n\nObjects:"
        for obj in local_objects:
            label = "PLAYER" if obj["index"] == 0 else f"NPC {chr(ord('A') + obj['index'] - 1)}"
            lx, ly = obj["local_x"], obj["local_y"]
            gx, gy = obj["global_x"], obj["global_y"]
            in_chunk = 0 <= lx < 32 and 0 <= ly < 32
            marker = "" if in_chunk else " [other chunk]"
            output += f"\n  [{obj['index']}] {label}: local ({lx}, {ly}) global ({gx}, {gy}){marker}"
    else:
        # Indoor map: coords are already local to the 32x32 grid
        for obj in objects:
            obj["local_x"] = obj["x"]
            obj["local_y"] = obj["y"]
            obj["global_x"] = obj["x"]
            obj["global_y"] = obj["y"]

        output = f"Map {map_id} — Player at ({px}, {py}) facing {facing_name}\n\n"
        output += render_map(ram_terrain, objects, px, py, facing)

        # Object list
        output += "\n\nObjects:"
        for obj in objects:
            label = "PLAYER" if obj["index"] == 0 else f"NPC {chr(ord('A') + obj['index'] - 1)}"
            output += f"\n  [{obj['index']}] {label}: ({obj['x']}, {obj['y']})"

    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            f.write(output + "\n")
        print(f"Written to {sys.argv[1]}")
    else:
        print(output)

    emu.close()


if __name__ == "__main__":
    main()
