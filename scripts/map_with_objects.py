#!/usr/bin/env python3
"""Render the current map with terrain, dynamic objects, and player state.

Connects to the running emulator via the IPC bridge and reads everything
automatically — no manual arguments needed.

Usage:
    python3 scripts/map_with_objects.py [output_file]

If output_file is omitted, prints to stdout.
"""
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
    0xA0: "berry_patch",
}


def read_terrain(emu):
    """Read the 32x32 terrain collision grid from RAM."""
    vals = emu.read_memory_range(TERRAIN_ADDR, size="short", count=1024)
    grid = []
    for row in range(32):
        grid.append(vals[row * 32:(row + 1) * 32])
    return grid


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
        if tile_x > 1000 or tile_y > 1000:
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


def render_map(terrain, objects, player_x, player_y, facing):
    """Render an ASCII map combining terrain and dynamic objects."""

    # Build object lookup: (x, y) -> label
    obj_at = {}
    for obj in objects:
        if 0 <= obj["x"] < 32 and 0 <= obj["y"] < 32:
            if obj["index"] == 0:
                obj_at[(obj["x"], obj["y"])] = FACING_ARROWS.get(facing, "P")
            else:
                obj_at[(obj["x"], obj["y"])] = chr(ord("A") + obj["index"] - 1)

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
        if 0 <= obj["x"] < 32 and 0 <= obj["y"] < 32:
            min_row = min(min_row, obj["y"])
            max_row = max(max_row, obj["y"])
            min_col = min(min_col, obj["x"])
            max_col = max(max_col, obj["x"])

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

    # Object list
    lines.append("")
    lines.append("Objects:")
    for obj in objects:
        label = "PLAYER" if obj["index"] == 0 else f"NPC {chr(ord('A') + obj['index'] - 1)}"
        lines.append(f"  [{obj['index']}] {label}: ({obj['x']}, {obj['y']})")

    return "\n".join(lines)


def main():
    emu = connect(SOCKET_PATH)

    map_id, px, py, facing = read_player_state(emu)
    terrain = read_terrain(emu)
    objects = read_objects(emu)

    facing_name = FACING_NAMES.get(facing, "?")
    output = f"Map {map_id} — Player at ({px}, {py}) facing {facing_name}\n\n"
    output += render_map(terrain, objects, px, py, facing)

    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            f.write(output + "\n")
        print(f"Written to {sys.argv[1]}")
    else:
        print(output)

    emu.close()


if __name__ == "__main__":
    main()
