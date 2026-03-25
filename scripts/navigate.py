#!/usr/bin/env python3
"""Walk a path in the game world, verifying each step.

Usage:
    python3 scripts/navigate.py <directions...>

    directions: space-separated list of up/down/left/right (or u/d/l/r)

Examples:
    python3 scripts/navigate.py down down left left left
    python3 scripts/navigate.py d d l l l
    python3 scripts/navigate.py right right up up up left

The script connects to the running MCP emulator via the IPC bridge,
moves one tile per direction (16 frames hold + 8 frames wait), and
verifies the player actually moved after each step. Stops early on
unexpected collision (position didn't change).
"""
import sys

sys.path.insert(0, "/workspace/DesmumeMCP")

from desmume_mcp.client import connect

# Player position memory layout (from watches/player_position.json)
POSITION_BASE = 0x0227F450
MAP_ID_OFFSET = 0
X_OFFSET = 8
Y_OFFSET = 12

# Movement timing
HOLD_FRAMES = 16  # frames to hold direction (1 tile)
WAIT_FRAMES = 8   # frames to wait after releasing

# Direction aliases
DIR_ALIASES = {"u": "up", "d": "down", "l": "left", "r": "right"}

SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"


def read_position(emu):
    """Read current map_id, x, y from memory."""
    map_id = emu.read_memory(POSITION_BASE + MAP_ID_OFFSET, size="long")
    x = emu.read_memory(POSITION_BASE + X_OFFSET, size="long")
    y = emu.read_memory(POSITION_BASE + Y_OFFSET, size="long")
    return map_id, x, y


def normalize_direction(d):
    """Normalize direction shorthand to full name."""
    d = d.lower().strip()
    return DIR_ALIASES.get(d, d)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/navigate.py <directions...>")
        print("  directions: up/down/left/right (or u/d/l/r)")
        sys.exit(1)

    directions = [normalize_direction(d) for d in sys.argv[1:]]
    valid = {"up", "down", "left", "right"}
    for d in directions:
        if d not in valid:
            print(f"Error: invalid direction '{d}'. Use up/down/left/right or u/d/l/r.")
            sys.exit(1)

    emu = connect(SOCKET_PATH)

    map_id, x, y = read_position(emu)
    print(f"Start: map={map_id}, ({x}, {y})")
    print(f"Path: {' -> '.join(directions)} ({len(directions)} steps)")
    print()

    for i, direction in enumerate(directions):
        old_map, old_x, old_y = read_position(emu)

        # Hold direction for HOLD_FRAMES, then wait
        emu.advance_frames(HOLD_FRAMES, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)

        new_map, new_x, new_y = read_position(emu)

        if (old_x, old_y) == (new_x, new_y) and old_map == new_map:
            print(f"  Step {i+1}/{len(directions)} ({direction}): BLOCKED at ({old_x}, {old_y})")
            print(f"\nStopped early — collision at step {i+1}.")
            print(f"Final: map={new_map}, ({new_x}, {new_y})")
            emu.close()
            sys.exit(2)

        if new_map != old_map:
            print(f"  Step {i+1}/{len(directions)} ({direction}): ({old_x}, {old_y}) -> ({new_x}, {new_y}) [MAP CHANGE: {old_map} -> {new_map}]")
        else:
            print(f"  Step {i+1}/{len(directions)} ({direction}): ({old_x}, {old_y}) -> ({new_x}, {new_y})")

    final_map, final_x, final_y = read_position(emu)
    print(f"\nDone! Final: map={final_map}, ({final_x}, {final_y})")
    emu.close()


if __name__ == "__main__":
    main()
