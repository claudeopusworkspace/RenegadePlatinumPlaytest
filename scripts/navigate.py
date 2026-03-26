#!/usr/bin/env python3
"""Walk a path in the game world, verifying each step.

Usage:
    python3 scripts/navigate.py <directions...>
    python3 scripts/navigate.py --to <x> <y>

Modes:
    Manual:  Provide directions as space-separated list of up/down/left/right
             (or u/d/l/r) with optional repeat counts (e.g., l20 u5 r3).
    Auto:    Use --to X Y to pathfind to a target tile on the current map.
             Reads terrain and dynamic objects, runs BFS for shortest path,
             and executes it step by step.

Examples:
    python3 scripts/navigate.py d d l l l
    python3 scripts/navigate.py l20 u5 r3
    python3 scripts/navigate.py --to 6 10

The script connects to the running MCP emulator via the IPC bridge,
moves one tile per direction (16 frames hold + 8 frames wait), and
verifies the player actually moved after each step. Stops early if
the position didn't change (collision, encounter, cutscene, etc.).
Always advances 120 frames at the end so any triggered events are visible.
"""
import re
import sys
from collections import deque

from game_state import SOCKET_PATH, get_map_state

sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect

# Player position memory layout
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

# BFS direction vectors: (dx, dy, direction_name)
BFS_MOVES = [
    (0, -1, "up"),
    (0, 1, "down"),
    (-1, 0, "left"),
    (1, 0, "right"),
]


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


def build_passability_grid(terrain, objects):
    """Build a 32x32 boolean grid: True = passable, False = blocked.

    Blocked if:
    - Terrain bit 15 is set (collision flag), UNLESS behavior is 0x69 (door)
    - An NPC (non-player object) occupies the tile

    Note: val=0x0000 is passable (indoor walkable floor). Only bit 15 blocks.
    """
    grid = [[True] * 32 for _ in range(32)]

    for row in range(32):
        for col in range(32):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            if is_blocked and behavior != 0x69:
                grid[row][col] = False

    # Block tiles occupied by NPCs (skip player at index 0)
    for obj in objects:
        if obj["index"] == 0:
            continue
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
            grid[ly][lx] = False

    return grid


def bfs_pathfind(passability, start_x, start_y, goal_x, goal_y):
    """BFS shortest path on a 32x32 grid.

    Returns list of direction strings (e.g., ["down", "left", "left"])
    or None if no path exists.
    """
    if not (0 <= start_x < 32 and 0 <= start_y < 32):
        return None
    if not (0 <= goal_x < 32 and 0 <= goal_y < 32):
        return None
    if (start_x, start_y) == (goal_x, goal_y):
        return []

    visited = set()
    visited.add((start_x, start_y))
    # Queue entries: (x, y, path_so_far)
    queue = deque([(start_x, start_y, [])])

    while queue:
        x, y, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < 32 and 0 <= ny < 32):
                continue
            if (nx, ny) in visited:
                continue
            if not passability[ny][nx]:
                continue

            new_path = path + [direction]
            if (nx, ny) == (goal_x, goal_y):
                return new_path

            visited.add((nx, ny))
            queue.append((nx, ny, new_path))

    return None


def execute_path(emu, directions):
    """Execute a list of directions, verifying each step. Returns (stopped_early, steps_taken)."""
    stopped_early = False

    for i, direction in enumerate(directions):
        old_map, old_x, old_y = read_position(emu)

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

    return stopped_early


def pathfind_mode(emu, target_x, target_y):
    """Read map state, pathfind to target, and execute."""
    state = get_map_state(emu)
    if state is None:
        print("Error: could not read map state (chunk resolution failed).")
        return True

    local_px = state["local_px"]
    local_py = state["local_py"]

    print(f"Start: map={state['map_id']}, ({state['px']}, {state['py']}) local=({local_px}, {local_py})")
    print(f"Target: ({target_x}, {target_y})")

    passability = build_passability_grid(state["terrain"], state["objects"])

    path = bfs_pathfind(passability, local_px, local_py, target_x, target_y)

    if path is None:
        print("\nNo path found! Target may be unreachable or blocked.")
        return True

    if len(path) == 0:
        print("\nAlready at target!")
        return False

    # Summarize the path compactly
    summary = summarize_path(path)
    print(f"Path: {summary} ({len(path)} steps)")
    print()

    return execute_path(emu, path)


def summarize_path(directions):
    """Compress a direction list into a readable summary (e.g., 'down x3 -> left x2')."""
    if not directions:
        return "(none)"
    parts = []
    current = directions[0]
    count = 1
    for d in directions[1:]:
        if d == current:
            count += 1
        else:
            parts.append(f"{current} x{count}" if count > 1 else current)
            current = d
            count = 1
    parts.append(f"{current} x{count}" if count > 1 else current)
    return " -> ".join(parts)


def main():
    args = sys.argv[1:]

    if not args:
        print("Usage:")
        print("  python3 scripts/navigate.py <directions...>     # manual mode")
        print("  python3 scripts/navigate.py --to <x> <y>        # pathfind mode")
        print()
        print("  directions: up/down/left/right (or u/d/l/r), optional repeat count (e.g., l20)")
        sys.exit(1)

    # Check for --to mode
    if args[0] == "--to":
        if len(args) != 3:
            print("Usage: python3 scripts/navigate.py --to <x> <y>")
            sys.exit(1)
        try:
            target_x = int(args[1])
            target_y = int(args[2])
        except ValueError:
            print("Error: --to requires integer x y coordinates.")
            sys.exit(1)

        emu = connect(SOCKET_PATH)
        stopped_early = pathfind_mode(emu, target_x, target_y)

        emu.advance_frames(SETTLE_FRAMES)
        final_map, final_x, final_y = read_position(emu)
        print(f"\nDone! Final: map={final_map}, ({final_x}, {final_y})")
        emu.close()

        if stopped_early:
            sys.exit(2)
        return

    # Manual direction mode
    directions = parse_directions(args)
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

    stopped_early = execute_path(emu, directions)

    emu.advance_frames(SETTLE_FRAMES)
    final_map, final_x, final_y = read_position(emu)
    print(f"\nDone! Final: map={final_map}, ({final_x}, {final_y})")
    emu.close()

    if stopped_early:
        sys.exit(2)


if __name__ == "__main__":
    main()
