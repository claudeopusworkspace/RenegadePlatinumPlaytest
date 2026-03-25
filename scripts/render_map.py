#!/usr/bin/env python3
"""Render the current map's collision grid with player position.

Usage (standalone, from a RAM dump):
    python3 render_map.py <terrain_dump.bin> <x> <y> <facing> [output_file]

The intended workflow from the MCP tools:
    1. read_watch("player_position") -> map_id, x, y
    2. read_watch("player_facing") -> facing direction
    3. dump_memory(address=0x0231D1E4, size=2048, file_path="terrain.bin")
    4. python3 scripts/render_map.py terrain.bin <x> <y> <facing> nav_view.txt
    5. Read nav_view.txt for the rendered map
"""
import struct
import sys

FACING_ARROWS = {0: "^", 1: "v", 2: "<", 3: ">"}
FACING_NAMES = {0: "up", 1: "down", 2: "left", 3: "right"}

# Tile behavior names (common ones from pret/pokeplatinum decompilation)
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
    0x80: "counter",
    0xA0: "berry_patch",
}


def render_terrain(terrain_bytes, player_x, player_y, facing):
    """Render a 32x32 terrain grid as a text map."""
    lines = []

    # Determine the bounding box of non-void tiles to trim output
    min_x, max_x, min_y, max_y = 31, 0, 31, 0
    for y in range(32):
        for x in range(32):
            val = struct.unpack_from("<H", terrain_bytes, (y * 32 + x) * 2)[0]
            if val != 0x0000:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

    # Add 1 tile of padding around the bounding box
    min_x = max(0, min_x - 1)
    max_x = min(31, max_x + 1)
    min_y = max(0, min_y - 1)
    max_y = min(31, max_y + 1)

    # Also ensure player is in view
    min_x = min(min_x, player_x - 1)
    max_x = max(max_x, player_x + 1)
    min_y = min(min_y, player_y - 1)
    max_y = max(max_y, player_y + 1)

    arrow = FACING_ARROWS.get(facing, "?")
    facing_name = FACING_NAMES.get(facing, "?")
    lines.append(f"Player at ({player_x}, {player_y}) facing {facing_name}")
    lines.append("")

    # Column headers
    header = "    "
    for x in range(min_x, max_x + 1):
        header += f"{x:3d}"
    lines.append(header)
    lines.append("    " + "---" * (max_x - min_x + 1))

    for y in range(min_y, max_y + 1):
        row = f"{y:2d} |"
        for x in range(min_x, max_x + 1):
            val = struct.unpack_from("<H", terrain_bytes, (y * 32 + x) * 2)[0]
            collision = (val >> 15) & 1
            behavior = val & 0xFF

            if x == player_x and y == player_y:
                row += f"  {arrow}"
            elif val == 0x0000:
                row += "  ."
            elif collision:
                if behavior == 0:
                    row += "  #"
                else:
                    row += f" {behavior:02x}"
            else:
                if behavior == 0x00:
                    row += "  _"
                elif behavior == 0x08:
                    row += "   "  # indoor walkable floor
                else:
                    row += f" {behavior:02x}"
        lines.append(row)

    lines.append("")
    lines.append("Legend:")
    lines.append(f"  {arrow}  = player (facing {facing_name})")
    lines.append("  .  = void (outside map)")
    lines.append("  #  = wall (impassable)")
    lines.append("  _  = walkable ground")
    lines.append("     = walkable floor (indoor)")
    lines.append("  xx = tile behavior (hex)")

    # List unique non-trivial behaviors present
    seen = set()
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            val = struct.unpack_from("<H", terrain_bytes, (y * 32 + x) * 2)[0]
            if val != 0x0000 and val != 0x8000:
                behavior = val & 0xFF
                if behavior != 0x00 and behavior != 0x08:
                    collision = "blocked" if val & 0x8000 else "passable"
                    name = BEHAVIORS.get(behavior, "")
                    seen.add((behavior, collision, name))

    if seen:
        lines.append("")
        lines.append("Behaviors on this map:")
        for beh, col, name in sorted(seen):
            label = f" ({name})" if name else ""
            lines.append(f"  {beh:02x} = {col}{label}")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 5:
        print(f"Usage: {sys.argv[0]} <terrain.bin> <x> <y> <facing> [output_file]")
        sys.exit(1)

    terrain_path = sys.argv[1]
    px = int(sys.argv[2])
    py = int(sys.argv[3])
    facing = int(sys.argv[4])
    output_path = sys.argv[5] if len(sys.argv) > 5 else None

    with open(terrain_path, "rb") as f:
        terrain = f.read(2048)

    result = render_terrain(terrain, px, py, facing)

    if output_path:
        with open(output_path, "w") as f:
            f.write(result + "\n")
        print(f"Written to {output_path}")
    else:
        print(result)


if __name__ == "__main__":
    main()
