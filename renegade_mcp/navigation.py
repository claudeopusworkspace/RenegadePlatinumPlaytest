"""Manual walking and BFS pathfinding for overworld navigation.

Connects to the emulator to move the player one tile at a time,
verifying position after each step.
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING, Any

from renegade_mcp.map_state import (
    CHUNK_SIZE,
    find_matrix_for_map,
    get_map_state,
    load_terrain_from_rom,
)

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Memory addresses ──
POSITION_BASE = 0x0227F450

# ── Movement timing ──
HOLD_FRAMES = 16
WAIT_FRAMES = 8
SETTLE_FRAMES = 120

# ── Direction handling ──
DIR_ALIASES = {"u": "up", "d": "down", "l": "left", "r": "right"}
BFS_MOVES = [(0, -1, "up"), (0, 1, "down"), (-1, 0, "left"), (1, 0, "right")]

# Ledge behaviors: direction you must be moving to cross them
LEDGE_DIRECTIONS = {
    0x38: "down", 0x39: "up", 0x3A: "left", 0x3B: "right",
}


def _read_position(emu: EmulatorClient) -> tuple[int, int, int]:
    """Read current map_id, x, y from memory."""
    map_id = emu.read_memory(POSITION_BASE, size="long")
    x = emu.read_memory(POSITION_BASE + 8, size="long")
    y = emu.read_memory(POSITION_BASE + 12, size="long")
    return map_id, x, y


def _normalize_direction(d: str) -> str:
    d = d.lower().strip()
    return DIR_ALIASES.get(d, d)


def parse_directions(args_str: str) -> list[str]:
    """Parse direction string, expanding repeat counts (e.g., 'l20 u5 r3')."""
    args = args_str.strip().split()
    directions = []
    pattern = re.compile(r"^([a-z]+)(\d+)$")
    for arg in args:
        arg = arg.lower().strip()
        m = pattern.match(arg)
        if m:
            d = _normalize_direction(m.group(1))
            count = int(m.group(2))
            directions.extend([d] * count)
        else:
            directions.append(_normalize_direction(arg))
    return directions


def _build_terrain_info(
    terrain: list, objects: list, width: int = 32, height: int = 32,
    obj_offset_x: int = 0, obj_offset_y: int = 0,
) -> tuple[list, set]:
    """Build terrain passability grid and NPC positions."""
    grid = [[(True, 0)] * width for _ in range(height)]

    for row in range(min(height, len(terrain))):
        for col in range(min(width, len(terrain[row]) if row < len(terrain) else 0)):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            passable = (not is_blocked) or behavior == 0x69 or behavior in LEDGE_DIRECTIONS
            grid[row][col] = (passable, behavior)

    npc_set = set()
    for obj in objects:
        if obj["index"] == 0:
            continue
        lx = obj.get("local_x", obj["x"]) - obj_offset_x
        ly = obj.get("local_y", obj["y"]) - obj_offset_y
        if 0 <= lx < width and 0 <= ly < height:
            npc_set.add((lx, ly))

    return grid, npc_set


def _bfs_pathfind(
    terrain_info: list, npc_set: set,
    start_x: int, start_y: int, goal_x: int, goal_y: int,
    width: int = 32, height: int = 32,
) -> list[str] | None:
    """BFS shortest path with ledge awareness. Returns direction list or None."""
    if not (0 <= start_x < width and 0 <= start_y < height):
        return None
    if not (0 <= goal_x < width and 0 <= goal_y < height):
        return None
    if (start_x, start_y) == (goal_x, goal_y):
        return []

    visited = {(start_x, start_y)}
    queue = deque([(start_x, start_y, [])])

    while queue:
        x, y, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited or (nx, ny) in npc_set:
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                continue

            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue

            new_path = path + [direction]
            if (nx, ny) == (goal_x, goal_y):
                return new_path

            visited.add((nx, ny))
            queue.append((nx, ny, new_path))

    return None


def _build_multi_chunk_terrain(
    map_id: int, px: int, py: int, target_x: int, target_y: int,
) -> tuple | None:
    """Load multi-chunk terrain grid. Returns (terrain_info, npc_set, origin_x, origin_y, w, h) or None."""
    result = find_matrix_for_map(map_id)
    if result is None:
        return None

    matrix_id, mw, mh, header_ids, terrain_ids = result

    player_chunk_x = px // CHUNK_SIZE
    player_chunk_y = py // CHUNK_SIZE
    target_chunk_x = target_x // CHUNK_SIZE
    target_chunk_y = target_y // CHUNK_SIZE

    min_cx = max(0, min(player_chunk_x, target_chunk_x) - 1)
    max_cx = min(mw - 1, max(player_chunk_x, target_chunk_x) + 1)
    min_cy = max(0, min(player_chunk_y, target_chunk_y) - 1)
    max_cy = min(mh - 1, max(player_chunk_y, target_chunk_y) + 1)

    # Cap at 5x5 chunks
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

    combined = [[(False, 0)] * grid_w for _ in range(grid_h)]

    for cy in range(min_cy, max_cy + 1):
        for cx in range(min_cx, max_cx + 1):
            land_id = terrain_ids[cy][cx]
            if land_id == 0xFFFF:
                continue

            chunk_terrain = load_terrain_from_rom(land_id)
            if chunk_terrain is None:
                continue

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


def _summarize_path(directions: list[str]) -> str:
    """Compress direction list into readable summary."""
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


def _execute_path(emu: EmulatorClient, directions: list[str]) -> tuple[bool, int, list[dict]]:
    """Execute directions, verifying each step. Returns (stopped_early, steps_taken, log)."""
    log = []
    steps_taken = 0

    for i, direction in enumerate(directions):
        old_map, old_x, old_y = _read_position(emu)

        emu.advance_frames(HOLD_FRAMES, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)

        new_map, new_x, new_y = _read_position(emu)
        steps_taken = i + 1

        entry = {
            "step": i + 1,
            "direction": direction,
            "from": {"x": old_x, "y": old_y, "map": old_map},
            "to": {"x": new_x, "y": new_y, "map": new_map},
        }

        if (old_x, old_y) == (new_x, new_y) and old_map == new_map:
            entry["blocked"] = True
            log.append(entry)
            return True, steps_taken, log

        if new_map != old_map:
            entry["map_change"] = True

        log.append(entry)

    return False, steps_taken, log


# ── Public API ──

def navigate_manual(emu: EmulatorClient, directions_str: str) -> dict[str, Any]:
    """Walk a manual path. Returns result dict with steps taken and final position."""
    directions = parse_directions(directions_str)

    valid = {"up", "down", "left", "right"}
    invalid = [d for d in directions if d not in valid]
    if invalid:
        return {"error": f"Invalid direction(s): {invalid}. Use up/down/left/right or u/d/l/r."}

    if not directions:
        return {"error": "No directions provided."}

    start_map, start_x, start_y = _read_position(emu)
    stopped_early, steps_taken, log = _execute_path(emu, directions)

    emu.advance_frames(SETTLE_FRAMES)
    final_map, final_x, final_y = _read_position(emu)

    return {
        "summary": _summarize_path(directions),
        "total_directions": len(directions),
        "steps_taken": steps_taken,
        "stopped_early": stopped_early,
        "start": {"x": start_x, "y": start_y, "map": start_map},
        "final": {"x": final_x, "y": final_y, "map": final_map},
        "log": log,
    }


def navigate_to(emu: EmulatorClient, target_x: int, target_y: int) -> dict[str, Any]:
    """Pathfind to target tile using BFS. Returns result dict."""
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not read map state (chunk resolution failed)."}

    map_id = state["map_id"]
    px, py = state["px"], state["py"]
    local_px, local_py = state["local_px"], state["local_py"]
    chunked = state["chunked"]
    origin_x = state.get("origin_x", 0)
    origin_y = state.get("origin_y", 0)

    is_global = target_x > 31 or target_y > 31 or chunked

    if is_global and chunked:
        result = _build_multi_chunk_terrain(map_id, px, py, target_x, target_y)
        if result is None:
            return {"error": "Could not load multi-chunk terrain."}

        combined_terrain, grid_ox, grid_oy, grid_w, grid_h = result
        npc_set = set()
        for obj in state["objects"]:
            if obj["index"] == 0:
                continue
            nx = obj["x"] - grid_ox
            ny = obj["y"] - grid_oy
            if 0 <= nx < grid_w and 0 <= ny < grid_h:
                npc_set.add((nx, ny))

        rel_px = px - grid_ox
        rel_py = py - grid_oy
        rel_tx = target_x - grid_ox
        rel_ty = target_y - grid_oy

        path = _bfs_pathfind(combined_terrain, npc_set, rel_px, rel_py,
                             rel_tx, rel_ty, width=grid_w, height=grid_h)
    else:
        if target_x > 31 or target_y > 31:
            target_x = target_x - origin_x
            target_y = target_y - origin_y

        terrain_info, npc_set = _build_terrain_info(state["terrain"], state["objects"])
        path = _bfs_pathfind(terrain_info, npc_set, local_px, local_py, target_x, target_y)

    if path is None:
        return {
            "error": "No path found. Target may be unreachable or blocked.",
            "start": {"x": px, "y": py, "map": map_id},
            "target": {"x": target_x, "y": target_y},
        }

    if len(path) == 0:
        emu.advance_frames(SETTLE_FRAMES)
        return {
            "path_summary": "Already at target!",
            "total_directions": 0,
            "steps_taken": 0,
            "stopped_early": False,
            "start": {"x": px, "y": py, "map": map_id},
            "final": {"x": px, "y": py, "map": map_id},
        }

    stopped_early, steps_taken, log = _execute_path(emu, path)

    emu.advance_frames(SETTLE_FRAMES)
    final_map, final_x, final_y = _read_position(emu)

    return {
        "path_summary": _summarize_path(path),
        "total_directions": len(path),
        "steps_taken": steps_taken,
        "stopped_early": stopped_early,
        "start": {"x": px, "y": py, "map": map_id},
        "target": {"x": target_x, "y": target_y},
        "final": {"x": final_x, "y": final_y, "map": final_map},
        "log": log,
    }
