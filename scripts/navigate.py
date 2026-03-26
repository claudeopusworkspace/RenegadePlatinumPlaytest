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

             Coordinates can be local (0-31) or global. Global coordinates
             are auto-detected when > 31 and converted to local coords.
             Cross-chunk pathfinding loads a 3x3 grid of adjacent chunks.

Examples:
    python3 scripts/navigate.py d d l l l
    python3 scripts/navigate.py l20 u5 r3
    python3 scripts/navigate.py --to 6 10          # local coords
    python3 scripts/navigate.py --to 116 885       # global coords (auto-detected)

The script connects to the running MCP emulator via the IPC bridge,
moves one tile per direction (16 frames hold + 8 frames wait), and
verifies the player actually moved after each step. Stops early if
the position didn't change (collision, encounter, cutscene, etc.).
Always advances 120 frames at the end so any triggered events are visible.

Ledge tiles (0x38-0x3B) are treated as one-way passable in the correct
direction: 0x38=south, 0x39=north, 0x3A=west, 0x3B=east.
"""
import re
import sys
from collections import deque

from game_state import (SOCKET_PATH, get_map_state, find_matrix_for_map,
                        load_terrain_from_rom, needs_chunk_lookup,
                        read_terrain_from_ram, read_objects, read_player_state,
                        CHUNK_SIZE)

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


# Ledge behaviors: direction you must be moving to cross them
LEDGE_DIRECTIONS = {
    0x38: "down",   # ledge_S — jump south
    0x39: "up",     # ledge_N — jump north
    0x3A: "left",   # ledge_W — jump west
    0x3B: "right",  # ledge_E — jump east
}


def build_terrain_info(terrain, objects, width=32, height=32, obj_offset_x=0, obj_offset_y=0):
    """Build terrain info grid: (passable, behavior) per tile.

    Returns:
        grid[row][col] = (passable: bool, behavior: int)
        npc_set: set of (x, y) tiles blocked by NPCs
    """
    grid = [[(True, 0)] * width for _ in range(height)]

    for row in range(min(height, len(terrain))):
        for col in range(min(width, len(terrain[row]) if row < len(terrain) else 0)):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            # Passable if: not blocked, OR is a door (0x69), OR is a ledge (0x38-0x3B)
            passable = (not is_blocked) or behavior == 0x69 or behavior in LEDGE_DIRECTIONS
            grid[row][col] = (passable, behavior)

    # NPC positions
    npc_set = set()
    for obj in objects:
        if obj["index"] == 0:
            continue
        lx = obj.get("local_x", obj["x"]) - obj_offset_x
        ly = obj.get("local_y", obj["y"]) - obj_offset_y
        if 0 <= lx < width and 0 <= ly < height:
            npc_set.add((lx, ly))

    return grid, npc_set


def bfs_pathfind(terrain_info, npc_set, start_x, start_y, goal_x, goal_y, width=32, height=32):
    """BFS shortest path with ledge awareness.

    Ledge tiles (0x38-0x3B) are only passable when approached from the
    correct direction. The BFS tracks the movement direction when entering
    each tile.

    Returns list of direction strings or None if no path exists.
    """
    if not (0 <= start_x < width and 0 <= start_y < height):
        return None
    if not (0 <= goal_x < width and 0 <= goal_y < height):
        return None
    if (start_x, start_y) == (goal_x, goal_y):
        return []

    visited = set()
    visited.add((start_x, start_y))
    queue = deque([(start_x, start_y, [])])

    while queue:
        x, y, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited:
                continue
            if (nx, ny) in npc_set:
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                continue

            # Ledge check: can only enter ledge tile from the matching direction
            if behavior in LEDGE_DIRECTIONS:
                required_dir = LEDGE_DIRECTIONS[behavior]
                if direction != required_dir:
                    continue

            new_path = path + [direction]
            if (nx, ny) == (goal_x, goal_y):
                return new_path

            visited.add((nx, ny))
            queue.append((nx, ny, new_path))

    return None


def build_multi_chunk_terrain(map_id, px, py, target_x, target_y):
    """Load a multi-chunk terrain grid covering both player and target.

    Returns (terrain_info, npc_set, grid_origin_x, grid_origin_y, grid_w, grid_h)
    or None on failure.
    """
    result = find_matrix_for_map(map_id)
    if result is None:
        return None

    matrix_id, mw, mh, header_ids, terrain_ids = result

    # Determine which chunks we need (player chunk + target chunk + neighbors)
    player_chunk_x = px // CHUNK_SIZE
    player_chunk_y = py // CHUNK_SIZE
    target_chunk_x = target_x // CHUNK_SIZE
    target_chunk_y = target_y // CHUNK_SIZE

    # Load a rectangular region of chunks covering both positions + 1 tile border
    min_cx = max(0, min(player_chunk_x, target_chunk_x) - 1)
    max_cx = min(mw - 1, max(player_chunk_x, target_chunk_x) + 1)
    min_cy = max(0, min(player_chunk_y, target_chunk_y) - 1)
    max_cy = min(mh - 1, max(player_chunk_y, target_chunk_y) + 1)

    # Cap at 5x5 chunks (160x160 tiles) to keep BFS fast
    if max_cx - min_cx > 4:
        mid = (player_chunk_x + target_chunk_x) // 2
        min_cx = max(0, mid - 2)
        max_cx = min(mw - 1, mid + 2)
    if max_cy - min_cy > 4:
        mid = (player_chunk_y + target_chunk_y) // 2
        min_cy = max(0, mid - 2)
        max_cy = min(mh - 1, mid + 2)

    num_cx = max_cx - min_cx + 1
    num_cy = max_cy - min_cy + 1
    grid_w = num_cx * CHUNK_SIZE
    grid_h = num_cy * CHUNK_SIZE
    grid_origin_x = min_cx * CHUNK_SIZE
    grid_origin_y = min_cy * CHUNK_SIZE

    # Build combined terrain grid
    combined = [[(False, 0)] * grid_w for _ in range(grid_h)]

    for cy in range(min_cy, max_cy + 1):
        for cx in range(min_cx, max_cx + 1):
            land_id = terrain_ids[cy][cx]
            if land_id == 0xFFFF:
                continue

            chunk_terrain = load_terrain_from_rom(land_id)
            if chunk_terrain is None:
                continue

            # Copy into combined grid
            base_x = (cx - min_cx) * CHUNK_SIZE
            base_y = (cy - min_cy) * CHUNK_SIZE
            for row in range(CHUNK_SIZE):
                for col in range(CHUNK_SIZE):
                    val = chunk_terrain[row][col]
                    is_blocked = (val & 0x8000) != 0
                    behavior = val & 0x00FF
                    passable = (not is_blocked) or behavior == 0x69 or behavior in LEDGE_DIRECTIONS
                    combined[base_y + row][base_x + col] = (passable, behavior)

    return combined, grid_origin_x, grid_origin_y, grid_w, grid_h


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
    """Read map state, pathfind to target, and execute.

    Supports both local (0-31) and global coordinates. Global coordinates
    are auto-detected and handled with multi-chunk terrain loading.
    """
    state = get_map_state(emu)
    if state is None:
        print("Error: could not read map state (chunk resolution failed).")
        return True

    map_id = state["map_id"]
    px, py = state["px"], state["py"]
    local_px = state["local_px"]
    local_py = state["local_py"]
    chunked = state["chunked"]
    origin_x = state.get("origin_x", 0)
    origin_y = state.get("origin_y", 0)

    # Detect if target is in global or local coordinates
    is_global = target_x > 31 or target_y > 31 or chunked

    if is_global and chunked:
        # Global coordinates on a multi-chunk map — use multi-chunk BFS
        print(f"Start: map={map_id}, global=({px}, {py}), chunk=({origin_x},{origin_y})")
        print(f"Target: global=({target_x}, {target_y})")

        result = build_multi_chunk_terrain(map_id, px, py, target_x, target_y)
        if result is None:
            print("\nError: could not load multi-chunk terrain.")
            return True

        combined_terrain, grid_ox, grid_oy, grid_w, grid_h = result
        npc_set = set()
        for obj in state["objects"]:
            if obj["index"] == 0:
                continue
            nx = obj["x"] - grid_ox
            ny = obj["y"] - grid_oy
            if 0 <= nx < grid_w and 0 <= ny < grid_h:
                npc_set.add((nx, ny))

        # Convert player and target to grid-relative coordinates
        rel_px = px - grid_ox
        rel_py = py - grid_oy
        rel_tx = target_x - grid_ox
        rel_ty = target_y - grid_oy

        print(f"Grid: {grid_w}x{grid_h} tiles (origin {grid_ox},{grid_oy})")

        path = bfs_pathfind(combined_terrain, npc_set, rel_px, rel_py,
                            rel_tx, rel_ty, width=grid_w, height=grid_h)
    else:
        # Local coordinates (indoor map or explicit local)
        # If global coords given for a chunked map but target is in same chunk,
        # convert to local
        if target_x > 31 or target_y > 31:
            target_x = target_x - origin_x
            target_y = target_y - origin_y

        print(f"Start: map={map_id}, ({px}, {py}) local=({local_px}, {local_py})")
        print(f"Target: ({target_x}, {target_y})")

        terrain_info, npc_set = build_terrain_info(state["terrain"], state["objects"])
        path = bfs_pathfind(terrain_info, npc_set, local_px, local_py,
                            target_x, target_y)

    if path is None:
        print("\nNo path found! Target may be unreachable or blocked.")
        return True

    if len(path) == 0:
        print("\nAlready at target!")
        return False

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
