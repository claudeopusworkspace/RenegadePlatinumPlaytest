"""Manual walking and BFS pathfinding for overworld navigation.

Connects to the emulator to move the player one tile at a time,
verifying position after each step.
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING, Any

from renegade_mcp.battle import format_battle, read_battle
from renegade_mcp.dialogue import read_dialogue
from renegade_mcp.map_state import (
    CHUNK_SIZE,
    get_map_state,
    get_matrix_for_map,
    load_terrain_from_rom,
    read_objects,
    read_player_state,
)
from renegade_mcp.turn import _wait_for_action_prompt

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Memory addresses ──
POSITION_BASE = 0x0227F450

# ── Movement timing ──
HOLD_FRAMES = 16
WAIT_FRAMES = 8
SETTLE_FRAMES = 120

MAX_REPATHS = 5

# ── Direction handling ──
DIR_ALIASES = {"u": "up", "d": "down", "l": "left", "r": "right"}
BFS_MOVES = [(0, -1, "up"), (0, 1, "down"), (-1, 0, "left"), (1, 0, "right")]

# Ledge behaviors: direction you must be moving to cross them
LEDGE_DIRECTIONS = {
    0x38: "down", 0x39: "up", 0x3A: "left", 0x3B: "right",
}

# Door/warp tile behaviors and how to activate them.
# None = walk-into triggers warp automatically; string = press this direction after standing on tile.
DOOR_ACTIVATION: dict[int, str | None] = {
    0x69: None,     # Overworld building entrance (blocked, warp overrides collision)
    0x65: "down",   # Interior exit mat — stand on tile, press down
    0x6E: None,     # Auto-enter door — walk into it
    0x5F: "left",   # Stairs down — stand on tile, press left
    0x5E: "right",  # Stairs up — stand on tile, press right
}

DOOR_TRANSITION_POLLS = 30   # polls to wait for map transition (30 * 15 = 450 frames)
DOOR_POLL_FRAMES = 15


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
    emu: EmulatorClient, map_id: int, px: int, py: int, target_x: int, target_y: int,
) -> tuple | None:
    """Load multi-chunk terrain grid. Returns (terrain_info, origin_x, origin_y, w, h) or None."""
    result = get_matrix_for_map(emu, map_id)
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


# ── NPC tracking and dynamic repathing ──

def _read_npc_positions(emu: EmulatorClient) -> dict[int, tuple[int, int]]:
    """Read current NPC tile positions. Returns {obj_index: (global_x, global_y)}."""
    objects = read_objects(emu)
    return {obj["index"]: (obj["x"], obj["y"]) for obj in objects if obj["index"] != 0}


def _detect_npc_changes(
    prev: dict[int, tuple[int, int]],
    curr: dict[int, tuple[int, int]],
) -> list[dict]:
    """Compare NPC positions between steps. Returns list of change entries."""
    changes = []
    for idx in sorted(set(prev) | set(curr)):
        label = chr(ord("A") + idx - 1) if 1 <= idx <= 26 else f"obj{idx}"
        if idx in prev and idx in curr:
            if prev[idx] != curr[idx]:
                changes.append({
                    "npc": label,
                    "from": {"x": prev[idx][0], "y": prev[idx][1]},
                    "to": {"x": curr[idx][0], "y": curr[idx][1]},
                })
        elif idx in curr:
            changes.append({
                "npc": label,
                "appeared_at": {"x": curr[idx][0], "y": curr[idx][1]},
            })
        else:
            changes.append({
                "npc": label,
                "disappeared_from": {"x": prev[idx][0], "y": prev[idx][1]},
            })
    return changes


def _try_repath(
    ctx: dict,
    current_npcs: dict[int, tuple[int, int]],
    player_x: int,
    player_y: int,
) -> list[str] | None:
    """Attempt BFS repath with current NPC positions. Returns directions or None."""
    ox, oy = ctx["grid_ox"], ctx["grid_oy"]
    w, h = ctx["grid_w"], ctx["grid_h"]

    npc_set = set()
    for nx, ny in current_npcs.values():
        rx, ry = nx - ox, ny - oy
        if 0 <= rx < w and 0 <= ry < h:
            npc_set.add((rx, ry))

    return _bfs_pathfind(
        ctx["terrain_info"], npc_set,
        player_x - ox, player_y - oy,
        ctx["goal_x"], ctx["goal_y"],
        width=w, height=h,
    )


# ── Post-navigation encounter/dialogue detection ──

POST_NAV_POLL_FRAMES = 15
POST_NAV_MAX_POLLS = 20  # 20 * 15 = 300 frames


def _post_nav_check(emu: EmulatorClient) -> dict[str, Any] | None:
    """Check for battle encounter or overworld dialogue after navigation.

    Polls up to 300 frames (15 at a time). On each iteration, checks
    read_battle and read_dialogue BEFORE advancing, so frame 0 is checked.

    If a battle is detected, advances through the transition to the first
    action prompt (ability announcements, send-out text, etc.) and returns
    the battle state, intro log, and prompt info — ready for battle_turn.

    If overworld dialogue is detected, returns the dialogue text.

    Returns None if neither is detected within 300 frames.
    """
    for _ in range(POST_NAV_MAX_POLLS):
        # Check for battle encounter
        battlers = read_battle(emu)
        if battlers:
            prompt_result = _wait_for_action_prompt(emu)
            battle_state = read_battle(emu)
            result: dict[str, Any] = {
                "encounter": "battle",
                "battle_log": prompt_result["log"],
                "battle_state": battle_state,
                "battle_state_formatted": format_battle(battle_state),
                "prompt_ready": prompt_result["ready"],
            }
            if prompt_result.get("prompt_type"):
                result["prompt_type"] = prompt_result["prompt_type"]
            if prompt_result.get("state"):
                result["final_state"] = prompt_result["state"]
            return result

        # Check for overworld dialogue
        dialogue = read_dialogue(emu, region="overworld")
        if dialogue["region"] != "none":
            return {
                "encounter": "dialogue",
                "dialogue": dialogue,
            }

        emu.advance_frames(POST_NAV_POLL_FRAMES)

    return None


# ── Door transition ──


def _handle_door_transition(
    emu: EmulatorClient, behavior: int, original_map: int,
) -> dict[str, Any] | None:
    """Handle a door/warp tile after navigation reaches it.

    For walk-into doors (0x69, 0x6E), the warp may have already triggered.
    For step-on doors (0x65, 0x5F, 0x5E), presses the activation direction.
    Waits for map transition to complete and returns new position info.

    Returns dict with new map info, or None if no transition occurred.
    """
    activation = DOOR_ACTIVATION.get(behavior)

    # For doors that need a direction press, do it now
    if activation is not None:
        emu.advance_frames(HOLD_FRAMES, buttons=[activation])
        emu.advance_frames(WAIT_FRAMES)

    # Poll for map transition — map_id should change
    for _ in range(DOOR_TRANSITION_POLLS):
        new_map, new_x, new_y = _read_position(emu)
        if new_map != original_map:
            # Transition happened — settle and return new position
            emu.advance_frames(SETTLE_FRAMES)
            final_map, final_x, final_y = _read_position(emu)
            return {
                "door_entered": True,
                "door_behavior": f"0x{behavior:02X}",
                "new_map": final_map,
                "new_position": {"x": final_x, "y": final_y, "map": final_map},
            }
        emu.advance_frames(DOOR_POLL_FRAMES)

    return None


# ── Encounter seeking ──

SEEK_MAX_STEPS = 200
GRASS_BEHAVIOR = 0x02
OPPOSITE_DIR = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _find_pacing_pair(
    terrain: list, local_px: int, local_py: int,
    npc_set: set, cave: bool = False,
    width: int = 32, height: int = 32,
) -> tuple | None:
    """Find two adjacent tiles to pace between, plus path to reach them.

    For grass mode: both tiles must have behavior 0x02 (tall grass).
    For cave mode: any walkable non-ledge tiles.

    Returns (tile_a, tile_b, dir_a_to_b, path_to_a) or None.
    """
    def is_valid(x: int, y: int) -> bool:
        if not (0 <= x < width and 0 <= y < height):
            return False
        val = terrain[y][x]
        if val & 0x8000:
            return False
        if (x, y) in npc_set:
            return False
        behavior = val & 0x00FF
        if cave:
            return behavior not in LEDGE_DIRECTIONS
        return behavior == GRASS_BEHAVIOR

    def valid_neighbor(x: int, y: int) -> tuple | None:
        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if is_valid(nx, ny):
                return nx, ny, direction
        return None

    # Player already on a valid tile?
    if is_valid(local_px, local_py):
        nb = valid_neighbor(local_px, local_py)
        if nb:
            return (local_px, local_py), (nb[0], nb[1]), nb[2], []

    # BFS to nearest valid tile that has a valid neighbor
    visited = {(local_px, local_py)}
    queue: deque[tuple[int, int, list[str]]] = deque([(local_px, local_py, [])])

    while queue:
        x, y, path = queue.popleft()
        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited:
                continue
            visited.add((nx, ny))
            val = terrain[ny][nx]
            if val & 0x8000:
                continue
            new_path = path + [direction]
            if is_valid(nx, ny):
                nb = valid_neighbor(nx, ny)
                if nb:
                    return (nx, ny), (nb[0], nb[1]), nb[2], new_path
            queue.append((nx, ny, new_path))

    return None


def seek_encounter(emu: EmulatorClient, cave: bool = False) -> dict[str, Any]:
    """Walk back and forth in grass (or cave) until a wild encounter triggers.

    Finds the nearest pair of adjacent grass tiles (or any walkable tiles in
    cave mode), navigates there if needed, then paces between them. Checks
    for battle/dialogue whenever a step is blocked. Caps at 200 steps.

    Returns dict with result type, steps taken, and encounter data if found.
    """
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not read map state."}

    map_id = state["map_id"]
    local_px, local_py = state["local_px"], state["local_py"]
    terrain = state["terrain"]
    origin_x = state.get("origin_x", 0)
    origin_y = state.get("origin_y", 0)
    height = len(terrain)
    width = len(terrain[0]) if terrain else 32

    # Build NPC set in local coords
    npc_set: set[tuple[int, int]] = set()
    for obj in state.get("objects", []):
        if obj["index"] == 0:
            continue
        lx = obj.get("local_x", obj["x"]) - origin_x
        ly = obj.get("local_y", obj["y"]) - origin_y
        if 0 <= lx < width and 0 <= ly < height:
            npc_set.add((lx, ly))

    pair = _find_pacing_pair(terrain, local_px, local_py, npc_set,
                             cave=cave, width=width, height=height)
    if pair is None:
        kind = "walkable" if cave else "grass"
        return {"error": f"No adjacent {kind} tiles found nearby."}

    tile_a, tile_b, dir_a_to_b, path_to_a = pair
    dir_b_to_a = OPPOSITE_DIR[dir_a_to_b]
    steps_taken = 0

    # Walk to first pacing tile if needed
    for direction in path_to_a:
        if steps_taken >= SEEK_MAX_STEPS:
            break
        old_map, old_x, old_y = _read_position(emu)
        emu.advance_frames(HOLD_FRAMES, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)
        new_map, new_x, new_y = _read_position(emu)
        steps_taken += 1

        if (old_x, old_y, old_map) == (new_x, new_y, new_map):
            encounter = _post_nav_check(emu)
            if encounter is not None:
                return {"result": "encounter", "steps_taken": steps_taken,
                        "encounter": encounter}
            return {"result": "blocked", "steps_taken": steps_taken,
                    "position": {"x": new_x, "y": new_y, "map": new_map}}

    # Pace back and forth
    current_dir = dir_a_to_b

    while steps_taken < SEEK_MAX_STEPS:
        old_map, old_x, old_y = _read_position(emu)
        emu.advance_frames(HOLD_FRAMES, buttons=[current_dir])
        emu.advance_frames(WAIT_FRAMES)
        new_map, new_x, new_y = _read_position(emu)
        steps_taken += 1

        if (old_x, old_y, old_map) == (new_x, new_y, new_map):
            encounter = _post_nav_check(emu)
            if encounter is not None:
                return {"result": "encounter", "steps_taken": steps_taken,
                        "encounter": encounter}
            return {"result": "blocked", "steps_taken": steps_taken,
                    "position": {"x": new_x, "y": new_y, "map": new_map}}

        current_dir = dir_b_to_a if current_dir == dir_a_to_b else dir_a_to_b

    # Max steps — final check
    encounter = _post_nav_check(emu)
    if encounter is not None:
        return {"result": "encounter", "steps_taken": steps_taken,
                "encounter": encounter}

    final_map, final_x, final_y = _read_position(emu)
    return {"result": "max_steps", "steps_taken": steps_taken,
            "position": {"x": final_x, "y": final_y, "map": final_map}}


# ── Path execution ──

def _execute_path(
    emu: EmulatorClient,
    directions: list[str],
    track_npcs: bool = False,
    repath_ctx: dict | None = None,
) -> tuple[bool, int, int, list[dict]]:
    """Execute directions, verifying each step.

    When track_npcs is True, reads NPC positions after each step and logs changes.
    When repath_ctx is provided (implies track_npcs), attempts BFS repath when
    NPCs block or move into the planned path.

    Returns (stopped_early, steps_taken, repaths_used, log).
    """
    if repath_ctx is not None:
        track_npcs = True

    log: list[dict] = []
    steps_taken = 0
    repaths_used = 0
    prev_npcs = _read_npc_positions(emu) if track_npcs else {}

    i = 0
    while i < len(directions):
        direction = directions[i]
        old_map, old_x, old_y = _read_position(emu)

        emu.advance_frames(HOLD_FRAMES, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)

        new_map, new_x, new_y = _read_position(emu)
        steps_taken += 1

        entry: dict = {
            "step": steps_taken,
            "direction": direction,
            "from": {"x": old_x, "y": old_y, "map": old_map},
            "to": {"x": new_x, "y": new_y, "map": new_map},
        }

        # Track NPC movement
        if track_npcs:
            curr_npcs = _read_npc_positions(emu)
            changes = _detect_npc_changes(prev_npcs, curr_npcs)
            if changes:
                entry["npc_changes"] = changes
            prev_npcs = curr_npcs

        blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map

        if blocked:
            entry["blocked"] = True
            # Attempt repath around obstacle
            if repath_ctx is not None and repaths_used < MAX_REPATHS:
                new_path = _try_repath(repath_ctx, prev_npcs, new_x, new_y)
                if new_path is not None and len(new_path) > 0:
                    repaths_used += 1
                    entry["repathed"] = True
                    entry["new_path"] = _summarize_path(new_path)
                    log.append(entry)
                    directions = directions[:i] + new_path
                    continue  # Retry from same index with new path
            log.append(entry)
            return True, steps_taken, repaths_used, log

        if new_map != old_map:
            entry["map_change"] = True

        # Proactive repath when NPCs moved and steps remain
        if (repath_ctx is not None and entry.get("npc_changes")
                and repaths_used < MAX_REPATHS and i + 1 < len(directions)):
            new_path = _try_repath(repath_ctx, prev_npcs, new_x, new_y)
            if new_path is None:
                entry["repath_failed"] = True
                log.append(entry)
                return True, steps_taken, repaths_used, log
            remaining = directions[i + 1:]
            if new_path != remaining:
                repaths_used += 1
                entry["repathed"] = True
                entry["new_path"] = _summarize_path(new_path)
                directions = directions[:i + 1] + new_path

        log.append(entry)
        i += 1

    return False, steps_taken, repaths_used, log


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
    stopped_early, steps_taken, _, log = _execute_path(emu, directions, track_npcs=True)

    # Post-navigation: poll for encounter or dialogue (also serves as settle)
    encounter = _post_nav_check(emu)
    final_map, final_x, final_y = _read_position(emu)

    result: dict[str, Any] = {
        "summary": _summarize_path(directions),
        "total_directions": len(directions),
        "steps_taken": steps_taken,
        "stopped_early": stopped_early,
        "start": {"x": start_x, "y": start_y, "map": start_map},
        "final": {"x": final_x, "y": final_y, "map": final_map},
        "log": log,
    }

    if encounter is not None:
        result["encounter"] = encounter

    npc_steps = sum(1 for e in log if "npc_changes" in e)
    if npc_steps > 0:
        result["steps_with_npc_movement"] = npc_steps

    return result


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
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
        if mc_result is None:
            return {"error": "Could not load multi-chunk terrain."}

        combined_terrain, grid_ox, grid_oy, grid_w, grid_h = mc_result
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

        repath_ctx = {
            "terrain_info": combined_terrain,
            "goal_x": rel_tx,
            "goal_y": rel_ty,
            "grid_w": grid_w,
            "grid_h": grid_h,
            "grid_ox": grid_ox,
            "grid_oy": grid_oy,
        }
    else:
        if target_x > 31 or target_y > 31:
            target_x = target_x - origin_x
            target_y = target_y - origin_y

        terrain_info, npc_set = _build_terrain_info(state["terrain"], state["objects"])
        path = _bfs_pathfind(terrain_info, npc_set, local_px, local_py, target_x, target_y)

        repath_ctx = {
            "terrain_info": terrain_info,
            "goal_x": target_x,
            "goal_y": target_y,
            "grid_w": 32,
            "grid_h": 32,
            "grid_ox": origin_x,
            "grid_oy": origin_y,
        }

    # Check if target tile is a door/warp
    target_behavior = None
    if is_global and chunked:
        ti = combined_terrain
        tx_local, ty_local = rel_tx, rel_ty
    else:
        ti = terrain_info
        tx_local, ty_local = (target_x, target_y) if not is_global else (rel_tx, rel_ty)
    if 0 <= ty_local < len(ti) and 0 <= tx_local < len(ti[0]):
        _, target_behavior = ti[ty_local][tx_local]

    is_door = target_behavior in DOOR_ACTIVATION

    if path is None:
        return {
            "error": "No path found. Target may be unreachable or blocked.",
            "start": {"x": px, "y": py, "map": map_id},
            "target": {"x": target_x, "y": target_y},
        }

    if len(path) == 0:
        if is_door:
            # Already standing on the door tile — activate it
            door_result = _handle_door_transition(emu, target_behavior, map_id)
            result: dict[str, Any] = {
                "path_summary": "Already at door",
                "total_directions": 0,
                "steps_taken": 0,
                "stopped_early": False,
                "start": {"x": px, "y": py, "map": map_id},
            }
            if door_result:
                result.update(door_result)
                result["final"] = door_result["new_position"]
            else:
                result["final"] = {"x": px, "y": py, "map": map_id}
                result["note"] = "Door activation did not trigger a map transition."
            return result

        emu.advance_frames(SETTLE_FRAMES)
        return {
            "path_summary": "Already at target!",
            "total_directions": 0,
            "steps_taken": 0,
            "stopped_early": False,
            "start": {"x": px, "y": py, "map": map_id},
            "final": {"x": px, "y": py, "map": map_id},
        }

    stopped_early, steps_taken, repaths_used, log = _execute_path(
        emu, path, repath_ctx=repath_ctx,
    )

    # For door targets, check if the warp already triggered during path execution
    if is_door and not stopped_early:
        cur_map, cur_x, cur_y = _read_position(emu)
        if cur_map != map_id:
            # Warp already happened (walk-into door like 0x69)
            emu.advance_frames(SETTLE_FRAMES)
            final_map, final_x, final_y = _read_position(emu)
            result = {
                "path_summary": _summarize_path(path),
                "total_directions": len(path),
                "steps_taken": steps_taken,
                "stopped_early": False,
                "start": {"x": px, "y": py, "map": map_id},
                "target": {"x": target_x, "y": target_y},
                "final": {"x": final_x, "y": final_y, "map": final_map},
                "door_entered": True,
                "door_behavior": f"0x{target_behavior:02X}",
                "new_map": final_map,
                "log": log,
            }
            return result

        # Warp didn't trigger yet — activate the door
        door_result = _handle_door_transition(emu, target_behavior, map_id)
        result = {
            "path_summary": _summarize_path(path),
            "total_directions": len(path),
            "steps_taken": steps_taken,
            "stopped_early": False,
            "start": {"x": px, "y": py, "map": map_id},
            "target": {"x": target_x, "y": target_y},
            "log": log,
        }
        if door_result:
            result.update(door_result)
            result["final"] = door_result["new_position"]
        else:
            final_map, final_x, final_y = _read_position(emu)
            result["final"] = {"x": final_x, "y": final_y, "map": final_map}
            result["note"] = "Door activation did not trigger a map transition."
        return result

    # Non-door target: standard post-nav check
    encounter = _post_nav_check(emu)
    final_map, final_x, final_y = _read_position(emu)

    result = {
        "path_summary": _summarize_path(path),
        "total_directions": len(path),
        "steps_taken": steps_taken,
        "stopped_early": stopped_early,
        "start": {"x": px, "y": py, "map": map_id},
        "target": {"x": target_x, "y": target_y},
        "final": {"x": final_x, "y": final_y, "map": final_map},
        "log": log,
    }

    if encounter is not None:
        result["encounter"] = encounter
    if repaths_used > 0:
        result["repaths"] = repaths_used
    npc_steps = sum(1 for e in log if "npc_changes" in e)
    if npc_steps > 0:
        result["steps_with_npc_movement"] = npc_steps

    return result


# ── Interact with object ──

# Direction to face the target from each adjacent offset
_ADJACENT_OFFSETS = [
    (0, -1, "down"),   # tile above target → face down
    (0,  1, "up"),     # tile below target → face up
    (-1, 0, "right"),  # tile left of target → face right
    (1,  0, "left"),   # tile right of target → face left
]

INTERACT_DIALOGUE_WAIT = 60  # frames to wait for auto-interaction
INTERACT_A_WAIT = 60         # frames to wait after pressing A


def interact_with(emu: EmulatorClient, object_index: int) -> dict[str, Any]:
    """Navigate to an object/NPC and interact with it.

    Finds the target object by index, pathfinds to the best adjacent tile,
    faces the target, and attempts interaction. Returns dialogue if any.
    """
    # ── Read current state ──
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not read map state."}

    objects = state["objects"]
    target = next((o for o in objects if o["index"] == object_index), None)
    if target is None:
        return {"error": f"Object index {object_index} not found in current map objects."}

    target_x, target_y = target["x"], target["y"]
    target_name = target.get("name", f"Object {object_index}")
    map_id = state["map_id"]
    px, py = state["px"], state["py"]
    chunked = state["chunked"]

    # ── Build terrain and NPC set ──
    is_global = target_x > 31 or target_y > 31 or chunked

    if is_global and chunked:
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
        if mc_result is None:
            return {"error": "Could not load multi-chunk terrain."}

        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result

        # Build NPC set, excluding the target object
        npc_set = set()
        for obj in objects:
            if obj["index"] == 0 or obj["index"] == object_index:
                continue
            nx = obj["x"] - grid_ox
            ny = obj["y"] - grid_oy
            if 0 <= nx < grid_w and 0 <= ny < grid_h:
                npc_set.add((nx, ny))

        rel_px = px - grid_ox
        rel_py = py - grid_oy
        rel_tx = target_x - grid_ox
        rel_ty = target_y - grid_oy
        width, height = grid_w, grid_h
    else:
        origin_x = state.get("origin_x", 0)
        origin_y = state.get("origin_y", 0)
        terrain_info, npc_set = _build_terrain_info(state["terrain"], state["objects"])
        # Remove target from NPC set so adjacency checks work
        rel_tx = target_x - origin_x if target_x > 31 else target_x
        rel_ty = target_y - origin_y if target_y > 31 else target_y
        npc_set.discard((rel_tx, rel_ty))
        rel_px = state["local_px"]
        rel_py = state["local_py"]
        width, height = 32, 32
        grid_ox, grid_oy = origin_x, origin_y

    # ── Find shortest path to any adjacent tile ──
    candidates = []
    for dx, dy, face_dir in _ADJACENT_OFFSETS:
        adj_x, adj_y = rel_tx + dx, rel_ty + dy
        if not (0 <= adj_x < width and 0 <= adj_y < height):
            continue
        passable, behavior = terrain_info[adj_y][adj_x]
        if not passable:
            continue
        if (adj_x, adj_y) in npc_set:
            continue
        path = _bfs_pathfind(terrain_info, npc_set, rel_px, rel_py,
                             adj_x, adj_y, width=width, height=height)
        if path is not None:
            candidates.append((len(path), path, adj_x, adj_y, face_dir))

    # ── Fallback: try across-counter interaction (2 tiles away) ──
    if not candidates:
        for dx, dy, face_dir in _ADJACENT_OFFSETS:
            # Check if intermediate tile is a counter
            mid_x, mid_y = rel_tx + dx, rel_ty + dy
            far_x, far_y = rel_tx + dx * 2, rel_ty + dy * 2
            if not (0 <= mid_x < width and 0 <= mid_y < height):
                continue
            if not (0 <= far_x < width and 0 <= far_y < height):
                continue
            _, mid_behavior = terrain_info[mid_y][mid_x]
            if mid_behavior != 0x80:  # not a counter tile
                continue
            far_passable, _ = terrain_info[far_y][far_x]
            if not far_passable or (far_x, far_y) in npc_set:
                continue
            path = _bfs_pathfind(terrain_info, npc_set, rel_px, rel_py,
                                 far_x, far_y, width=width, height=height)
            if path is not None:
                candidates.append((len(path), path, far_x, far_y, face_dir))

    if not candidates:
        return {
            "error": f"No reachable tile adjacent to {target_name} at ({target_x}, {target_y}). "
                     "Fully surrounded by obstacles.",
            "target": {"index": object_index, "name": target_name, "x": target_x, "y": target_y},
        }

    # Pick shortest path
    candidates.sort(key=lambda c: c[0])
    _, best_path, dest_x, dest_y, face_dir = candidates[0]

    # ── Execute path ──
    nav_result: dict[str, Any] = {
        "target": {"index": object_index, "name": target_name, "x": target_x, "y": target_y},
        "destination": {"x": dest_x + grid_ox, "y": dest_y + grid_oy},
        "face_direction": face_dir,
    }

    if len(best_path) > 0:
        repath_ctx = {
            "terrain_info": terrain_info,
            "goal_x": dest_x,
            "goal_y": dest_y,
            "grid_w": width,
            "grid_h": height,
            "grid_ox": grid_ox,
            "grid_oy": grid_oy,
        }
        stopped_early, steps_taken, repaths_used, log = _execute_path(
            emu, best_path, repath_ctx=repath_ctx,
        )
        nav_result["path_summary"] = _summarize_path(best_path)
        nav_result["steps_taken"] = steps_taken
        if stopped_early:
            encounter = _post_nav_check(emu)
            if encounter:
                nav_result["encounter"] = encounter
                nav_result["interrupted"] = True
                return nav_result
            nav_result["stopped_early"] = True
            return nav_result
    else:
        nav_result["path_summary"] = "Already adjacent"
        nav_result["steps_taken"] = 0

    # ── Face the target ──
    _, _, _, cur_facing = read_player_state(emu)
    desired_facing = {"up": 0, "down": 1, "left": 2, "right": 3}[face_dir]
    if cur_facing != desired_facing:
        emu.advance_frames(HOLD_FRAMES, buttons=[face_dir])
        emu.advance_frames(WAIT_FRAMES)
        nav_result["turned_to_face"] = face_dir

    # ── Check for auto-interaction (signs auto-trigger when faced) ──
    emu.advance_frames(INTERACT_DIALOGUE_WAIT)
    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] != "none":
        nav_result["dialogue"] = dialogue
        return nav_result

    # ── Press A to interact ──
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(INTERACT_A_WAIT)

    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] != "none":
        nav_result["dialogue"] = dialogue
        nav_result["pressed_a"] = True
        return nav_result

    # ── No dialogue found ──
    nav_result["dialogue"] = None
    nav_result["note"] = f"{target_name} did not produce any dialogue when interacted with."
    return nav_result
