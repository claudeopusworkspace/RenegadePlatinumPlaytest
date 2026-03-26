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
import sys

from game_state import (
    BEHAVIORS, CHUNK_SIZE, FACING_ARROWS, FACING_NAMES, SOCKET_PATH,
    get_map_state,
)

sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect


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
    state = get_map_state(emu)

    if state is None:
        print("Could not resolve map chunk", file=sys.stderr)
        emu.close()
        sys.exit(1)

    facing_name = FACING_NAMES.get(state["facing"], "?")

    if state["chunked"]:
        chunk_cx = state["px"] // CHUNK_SIZE
        chunk_cy = state["py"] // CHUNK_SIZE
        header = (
            f"Map {state['map_id']} — Player at ({state['px']}, {state['py']}) "
            f"facing {facing_name}\n"
            f"Chunk ({chunk_cx}, {chunk_cy}) — "
            f"origin ({state['origin_x']}, {state['origin_y']}) — "
            f"local ({state['local_px']}, {state['local_py']})\n"
        )
        output = header + "\n"
        output += render_map(
            state["terrain"], state["objects"],
            state["local_px"], state["local_py"], state["facing"],
        )
        output += "\n\nObjects:"
        for obj in state["objects"]:
            label = "PLAYER" if obj["index"] == 0 else f"NPC {chr(ord('A') + obj['index'] - 1)}"
            lx, ly = obj["local_x"], obj["local_y"]
            gx, gy = obj["x"], obj["y"]
            in_chunk = 0 <= lx < 32 and 0 <= ly < 32
            marker = "" if in_chunk else " [other chunk]"
            output += f"\n  [{obj['index']}] {label}: local ({lx}, {ly}) global ({gx}, {gy}){marker}"
    else:
        output = f"Map {state['map_id']} — Player at ({state['px']}, {state['py']}) facing {facing_name}\n\n"
        output += render_map(
            state["terrain"], state["objects"],
            state["local_px"], state["local_py"], state["facing"],
        )
        output += "\n\nObjects:"
        for obj in state["objects"]:
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
