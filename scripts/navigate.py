#!/usr/bin/env python3
"""Walk a path in the game world, verifying each step.

Usage:
    python3 scripts/navigate.py <directions...>

    directions: space-separated list of up/down/left/right (or u/d/l/r)
                optionally followed by a repeat count (e.g., l20 = left 20 times)

Examples:
    python3 scripts/navigate.py down down left left left
    python3 scripts/navigate.py d d l l l
    python3 scripts/navigate.py l20 u5 r3
    python3 scripts/navigate.py right right up up up left

The script connects to the running MCP emulator via the IPC bridge,
moves one tile per direction (16 frames hold + 8 frames wait), and
verifies the player actually moved after each step. Stops early if
the position didn't change (collision, encounter, cutscene, etc.).
Always advances 120 frames at the end so any triggered events are visible.
"""
import re
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
SETTLE_FRAMES = 120  # frames to advance at end so events become visible

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


def parse_directions(args):
    """Parse direction args, expanding repeat counts (e.g., 'l20' -> 20x left)."""
    directions = []
    pattern = re.compile(r'^([a-z]+)(\d+)$')
    for arg in args:
        arg = arg.lower().strip()
        m = pattern.match(arg)
        if m:
            d = normalize_direction(m.group(1))
            count = int(m.group(2))
            directions.extend([d] * count)
        else:
            directions.append(normalize_direction(arg))
    return directions


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/navigate.py <directions...>")
        print("  directions: up/down/left/right (or u/d/l/r), optional repeat count (e.g., l20)")
        sys.exit(1)

    directions = parse_directions(sys.argv[1:])
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

    stopped_early = False
    for i, direction in enumerate(directions):
        old_map, old_x, old_y = read_position(emu)

        # Hold direction for HOLD_FRAMES, then wait
        emu.advance_frames(HOLD_FRAMES, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)

        new_map, new_x, new_y = read_position(emu)

        if (old_x, old_y) == (new_x, new_y) and old_map == new_map:
            print(f"  Step {i+1}/{len(directions)} ({direction}): stopped at ({old_x}, {old_y})")
            print(f"\nStopped early at step {i+1} — position unchanged (collision, encounter, or event).")
            stopped_early = True
            break

        if new_map != old_map:
            print(f"  Step {i+1}/{len(directions)} ({direction}): ({old_x}, {old_y}) -> ({new_x}, {new_y}) [MAP CHANGE: {old_map} -> {new_map}]")
        else:
            print(f"  Step {i+1}/{len(directions)} ({direction}): ({old_x}, {old_y}) -> ({new_x}, {new_y})")

    # Always settle so any triggered events (encounters, cutscenes) become visible
    emu.advance_frames(SETTLE_FRAMES)

    final_map, final_x, final_y = read_position(emu)
    print(f"\nDone! Final: map={final_map}, ({final_x}, {final_y})")
    emu.close()

    if stopped_early:
        sys.exit(2)


if __name__ == "__main__":
    main()
