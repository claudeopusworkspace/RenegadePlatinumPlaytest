"""Manual walking and BFS pathfinding for overworld navigation.

Connects to the emulator to move the player one tile at a time,
verifying position after each step.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from renegade_mcp.battle import format_battle, read_battle
from renegade_mcp.dialogue import (
    CTX_RUNNING, CTX_WAITING,
    _find_script_manager, _read_context_state, _read_script_state,
    advance_dialogue, read_dialogue,
)
from renegade_mcp.map_names import lookup_map_name
from renegade_mcp.party import read_party
from renegade_mcp.trainer import read_trainer_status
from renegade_mcp.map_state import (
    BIKE_BRIDGE_BEHAVIORS,
    CHUNK_SIZE,
    SIGN_GFX_IDS,
    analyze_elevation,
    get_land_data_id,
    get_map_state,
    get_matrix_for_map,
    is_on_cycling_road,
    load_terrain_from_rom,
    parse_bdhc,
    read_objects,
    read_player_height,
    read_player_state,
    read_sign_tiles_from_rom,
)
from renegade_mcp.turn import _wait_for_action_prompt

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Memory addresses (resolved at runtime) ──

# ── Movement timing ──
HOLD_FRAMES = 16       # walking: 1 tile per press
BIKE_HOLD_FRAMES = 4   # cycling: bike moves 1 tile per ~4 frames
WAIT_FRAMES = 8
SETTLE_FRAMES = 120
SLOW_TERRAIN_RETRIES = 3  # Re-press attempts on apparent block (deep snow, ice)


def _get_move_hold(emu: EmulatorClient) -> int:
    """Return the per-tile hold frames based on whether the player is cycling."""
    from renegade_mcp.addresses import addr
    cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
    return BIKE_HOLD_FRAMES if cycling else HOLD_FRAMES

MAX_REPATHS = 15

# ── Direction handling ──
DIR_ALIASES = {"u": "up", "d": "down", "l": "left", "r": "right"}
BFS_MOVES = [(0, -1, "up"), (0, 1, "down"), (-1, 0, "left"), (1, 0, "right")]

# Ledge behaviors: direction you must be moving to cross them
LEDGE_DIRECTIONS = {
    0x38: "down", 0x39: "up", 0x3A: "left", 0x3B: "right",
}

# Water tiles — impassable until Surf is available
WATER_BEHAVIORS = {0x10, 0x15}  # river, sea (surfable)
WATERFALL_BEHAVIOR = 0x13
ROCK_CLIMB_BEHAVIORS = {0x4A, 0x4B}  # N-S, E-W

# All terrain-based obstacles (water + waterfall + rock climb)
TERRAIN_OBSTACLES = WATER_BEHAVIORS | {WATERFALL_BEHAVIOR} | ROCK_CLIMB_BEHAVIORS

# ── HM obstacle objects (identified by graphics_id in zone_event data) ──
# These are map objects (like NPCs) that can be cleared with field moves.
HM_OBSTACLES: dict[int, dict[str, str]] = {
    85: {"type": "strength_boulder", "move": "Strength",   "badge": "Mine"},
    86: {"type": "rock_smash",       "move": "Rock Smash", "badge": "Coal"},
    87: {"type": "cut_tree",         "move": "Cut",        "badge": "Forest"},
}

# Obstacles that can be auto-cleared (interact → yes → gone)
CLEARABLE_OBSTACLES = {86, 87}  # rock_smash, cut_tree
# Obstacles that are never auto-handled (puzzle-dependent)
PUZZLE_OBSTACLES = {85}  # strength_boulder

# Badge name → bit index in the badge bitmask
BADGE_BITS: dict[str, int] = {
    "Coal": 0, "Forest": 1, "Cobble": 2, "Fen": 3,
    "Relic": 4, "Mine": 5, "Icicle": 6, "Beacon": 7,
}

# Terrain obstacle → required move + badge
TERRAIN_OBSTACLE_INFO: dict[int, dict[str, str]] = {
    0x10: {"type": "water",       "move": "Surf",       "badge": "Fen"},
    0x15: {"type": "water",       "move": "Surf",       "badge": "Fen"},
    0x13: {"type": "waterfall",   "move": "Waterfall",  "badge": "Beacon"},
    0x4A: {"type": "rock_climb",  "move": "Rock Climb", "badge": "Icicle"},
    0x4B: {"type": "rock_climb",  "move": "Rock Climb", "badge": "Icicle"},
}

# Door/warp tile behaviors and how to activate them.
# None = walk-into triggers warp automatically; string = press this direction after standing on tile.
DOOR_ACTIVATION: dict[int, str | None] = {
    0x69: None,     # DOOR — building entrance (walk into from any direction)
    0x6E: None,     # WARP_NORTH — walk into
    0x65: "down",   # WARP_ENTRANCE_SOUTH — stand on tile, press down
    0x5F: "left",   # WARP_STAIRS_WEST — stand on tile, press left
    0x5E: "right",  # WARP_STAIRS_EAST — stand on tile, press right
    0x67: None,     # WARP_PANEL — teleport pad (step on, auto warp)
    0x6A: None,     # ESCALATOR_FLIP_FACE — step on, auto
    0x6B: None,     # ESCALATOR — step on, auto
}

# Directional walk-into warps: warp triggers when stepping ONTO the tile
# while moving in the specified direction. These tiles have collision flags
# but are passable from the correct approach direction.
# Behavior → required movement direction
DIRECTIONAL_WARP: dict[int, str] = {
    0x62: "right",  # WARP_ENTRANCE_EAST — walk east into cave
    0x63: "left",   # WARP_ENTRANCE_WEST — walk west into cave
    0x64: "up",     # WARP_ENTRANCE_NORTH — walk north into cave
    0x6C: "right",  # WARP_EAST — side entry, walk east
    0x6D: "left",   # WARP_WEST — side entry, walk west
    0x6F: "down",   # WARP_SOUTH — side entry, walk south
}

# All warp behaviors that should be passable despite collision flags
WARP_PASSABLE = {0x69} | set(DIRECTIONAL_WARP.keys())

# Directional blocks: behavior on SOURCE tile → direction that is blocked.
# These are platform-edge tiles that prevent stepping off elevated surfaces.
DIRECTIONAL_BLOCKS: dict[int, str] = {
    0x30: "right",  # block_E — can't step east off platform
    0x31: "left",   # block_W — can't step west off platform
}

# ── 3D pathfinding constants ──
_3D_MAX_DEPTH = 5       # max ramp transitions in a single path search
_3D_TIMEOUT = 300       # wall-clock seconds before aborting 3D search

DOOR_TRANSITION_POLLS = 30   # polls to wait for map transition (30 * 15 = 450 frames)
DOOR_POLL_FRAMES = 15


def _tile_behavior_hint(behavior: int) -> str:
    """Return a human-readable hint for common impassable tile behaviors."""
    hints: dict[int, str] = {
        0x10: "water (needs Surf)",
        0x15: "water (needs Surf)",
        0x13: "waterfall (needs Waterfall)",
        0x4A: "rock climb wall (needs Rock Climb)",
        0x4B: "rock climb wall (needs Rock Climb)",
        0x69: "door/warp (may be locked)",
        0x65: "warp entrance",
    }
    if behavior in hints:
        return hints[behavior]
    return f"behavior 0x{behavior:02X}"


# ── Behavior chars for failure diagrams (subset of map_state._BEHAVIOR_CHAR) ──
_DIAG_CHAR: dict[int, str] = {
    0x02: '"', 0x03: '"',  # grass
    0x10: '≈', 0x13: '≈', 0x15: '≈',  # water
    0x38: 'v', 0x39: '^', 0x3A: '<', 0x3B: '>',  # ledges
    0x69: 'D', 0x6E: 'D',  # doors
}


def _bfs_reachable(
    terrain_info: list, npc_set: set,
    start_x: int, start_y: int,
    width: int, height: int,
) -> set[tuple[int, int]]:
    """Flood-fill BFS from start. Returns set of all reachable (x, y) tiles."""
    if not (0 <= start_x < width and 0 <= start_y < height):
        return set()
    visited = {(start_x, start_y)}
    queue = deque([(start_x, start_y)])
    while queue:
        x, y = queue.popleft()
        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited or (nx, ny) in npc_set:
                continue
            passable, behavior = terrain_info[ny][nx]
            if not passable:
                continue
            if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                continue
            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue
            visited.add((nx, ny))
            queue.append((nx, ny))
    return visited


def _find_nearest_reachable(
    reachable: set[tuple[int, int]], target_x: int, target_y: int,
) -> tuple[int, int] | None:
    """Find the reachable tile closest to target by Manhattan distance."""
    if not reachable:
        return None
    best = None
    best_dist = float("inf")
    for rx, ry in reachable:
        d = abs(rx - target_x) + abs(ry - target_y)
        if d < best_dist:
            best_dist = d
            best = (rx, ry)
    return best


def _render_failure_diagram(
    terrain_info: list, npc_set: set,
    player_x: int, player_y: int,
    target_x: int, target_y: int,
    nearest: tuple[int, int] | None,
    width: int, height: int,
    radius: int = 4,
) -> str:
    """Render a small ASCII grid centered on the target for failure diagnosis.

    Shows: @ player, X target, * nearest reachable, # wall, . passable, ≈ water, etc.
    """
    cx, cy = target_x, target_y
    min_x = max(0, cx - radius)
    max_x = min(width - 1, cx + radius)
    min_y = max(0, cy - radius)
    max_y = min(height - 1, cy + radius)

    lines = []
    for y in range(min_y, max_y + 1):
        row = []
        for x in range(min_x, max_x + 1):
            if (x, y) == (player_x, player_y):
                row.append("@")
            elif (x, y) == (target_x, target_y):
                row.append("X")
            elif nearest and (x, y) == nearest:
                row.append("*")
            elif (x, y) in npc_set:
                row.append("N")
            elif 0 <= y < len(terrain_info) and 0 <= x < len(terrain_info[0]):
                passable, behavior = terrain_info[y][x]
                if not passable:
                    row.append(_DIAG_CHAR.get(behavior, "#"))
                else:
                    row.append(_DIAG_CHAR.get(behavior, "."))
            else:
                row.append(" ")
        lines.append("".join(row))

    return "\n".join(lines)


def _get_field_move_availability(emu: EmulatorClient) -> dict[str, bool]:
    """Check which field moves are usable (party has move + badge).

    Returns dict mapping move name → available (e.g. {"Rock Smash": True}).
    """
    party = read_party(emu)
    trainer = read_trainer_status(emu)
    badge_byte = trainer.get("badge_raw", 0)

    # Collect all move names across party
    party_moves: set[str] = set()
    for mon in party:
        for mn in mon.get("move_names", []):
            if mn and mn != "-":
                party_moves.add(mn)

    # All field moves we care about
    field_moves = {
        "Rock Smash": "Coal", "Cut": "Forest", "Strength": "Mine",
        "Surf": "Fen", "Waterfall": "Beacon", "Rock Climb": "Icicle",
    }

    result = {}
    for move, badge in field_moves.items():
        has_move = move in party_moves
        has_badge = bool(badge_byte & (1 << BADGE_BITS[badge]))
        result[move] = has_move and has_badge

    return result


def _read_position(emu: EmulatorClient) -> tuple[int, int, int]:
    """Read current map_id, x, y from memory."""
    from renegade_mcp.addresses import addr
    pos_base = addr("PLAYER_POS_BASE")
    map_id = emu.read_memory(pos_base, size="long")
    x = emu.read_memory(pos_base + 8, size="long")
    y = emu.read_memory(pos_base + 12, size="long")
    return map_id, x, y


def _pos_with_map(x: int, y: int, map_id: int) -> dict[str, Any]:
    """Build a compact position dict with map name."""
    info = lookup_map_name(map_id)
    return {"x": x, "y": y, "map": info["name"], "map_id": map_id}


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
) -> tuple[list, set, dict]:
    """Build terrain passability grid, NPC positions, and obstacle map.

    Returns:
        grid: 2D list of (passable, behavior) tuples
        npc_set: set of (x, y) for truly impassable objects (NPCs + strength boulders)
        obstacle_map: dict of (x, y) → obstacle info for clearable HM obstacles
    """
    grid = [[(True, 0)] * width for _ in range(height)]

    for row in range(min(height, len(terrain))):
        for col in range(min(width, len(terrain[row]) if row < len(terrain) else 0)):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            passable = (
                ((not is_blocked) or behavior in WARP_PASSABLE or behavior in LEDGE_DIRECTIONS)
                and behavior not in TERRAIN_OBSTACLES
            )
            grid[row][col] = (passable, behavior)

    npc_set = set()
    obstacle_map: dict[tuple[int, int], dict] = {}
    for obj in objects:
        if obj["index"] == 0:
            continue
        lx = obj.get("local_x", obj["x"]) - obj_offset_x
        ly = obj.get("local_y", obj["y"]) - obj_offset_y
        if not (0 <= lx < width and 0 <= ly < height):
            continue

        gfx_id = obj.get("graphics_id", 0)
        if gfx_id in CLEARABLE_OBSTACLES:
            info = HM_OBSTACLES[gfx_id]
            obstacle_map[(lx, ly)] = {
                "type": info["type"],
                "move": info["move"],
                "badge": info["badge"],
                "gfx_id": gfx_id,
                "global_x": obj["x"],
                "global_y": obj["y"],
            }
        elif gfx_id in PUZZLE_OBSTACLES:
            # Strength boulders go in npc_set — never auto-cleared
            npc_set.add((lx, ly))
        else:
            npc_set.add((lx, ly))

    return grid, npc_set, obstacle_map


# ── 3D elevation helpers ──

def _height_to_level(
    height: float, elevation: dict,
    tile_x: int | None = None, tile_y: int | None = None,
) -> int | None:
    """Convert player height (fx32 float) to a level index.

    Exact match first. If tile coords are given, checks whether the tile has
    explicit level data (ramp or level_map). Falls back to mid-ramp range
    matching (preferring narrowest range) and finally nearest level by height.
    """
    h = round(height)
    level = elevation["height_to_level"].get(h)
    if level is not None:
        return level

    # If tile coords provided, use the tile's own elevation data
    if tile_x is not None and tile_y is not None:
        key = (tile_x, tile_y)
        if key in elevation["ramp_tiles"]:
            ri = elevation["ramp_tiles"][key]
            # Player is on this ramp — pick the end closer to their height
            levels_info = elevation["levels"]
            hbl: dict[int, int] = {lv["level"]: lv["height"] for lv in levels_info}
            fh = hbl.get(ri["from_level"], 0)
            th = hbl.get(ri["to_level"], 0)
            if abs(h - fh) <= abs(h - th):
                return ri["from_level"]
            return ri["to_level"]
        if key in elevation["level_map"]:
            tile_levels = elevation["level_map"][key]
            if tile_levels:
                # Pick the level whose defined height is closest to player height
                levels_info = elevation["levels"]
                hbl = {lv["level"]: lv["height"] for lv in levels_info}
                return min(tile_levels, key=lambda lv: abs(hbl.get(lv, 0) - h))

    # Player might be mid-ramp — check ramp height ranges, prefer narrowest
    levels_info = elevation["levels"]
    height_by_level: dict[int, int] = {lv["level"]: lv["height"] for lv in levels_info}
    best_ramp_level = None
    best_span = float("inf")
    for ramp in elevation["ramps"]:
        from_h = height_by_level.get(ramp["from_level"])
        to_h = height_by_level.get(ramp["to_level"])
        if from_h is not None and to_h is not None:
            lo, hi = min(from_h, to_h), max(from_h, to_h)
            span = hi - lo
            if lo <= h <= hi and span < best_span:
                best_span = span
                # Pick the ramp end closer to the player's height
                if abs(h - from_h) <= abs(h - to_h):
                    best_ramp_level = ramp["from_level"]
                else:
                    best_ramp_level = ramp["to_level"]
    if best_ramp_level is not None:
        return best_ramp_level

    # Final fallback: nearest defined level by height
    if levels_info:
        return min(levels_info, key=lambda lv: abs(lv["height"] - h))["level"]

    return None


def _get_tile_level(x: int, y: int, elevation: dict) -> list[int]:
    """Get which elevation levels a tile belongs to.

    Ramp tiles return both connected levels. Tiles with no elevation data
    return [] (treated as any-level by the BFS).
    """
    key = (x, y)
    if key in elevation["ramp_tiles"]:
        ri = elevation["ramp_tiles"][key]
        return [ri["from_level"], ri["to_level"]]
    if key in elevation["level_map"]:
        return elevation["level_map"][key]
    return []


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

    goal = (goal_x, goal_y)

    while queue:
        x, y, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited:
                continue
            if (nx, ny) in npc_set and (nx, ny) != goal:
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                continue

            # Directional warps only allow entry from the correct direction
            if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                continue

            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue

            new_path = path + [direction]
            if (nx, ny) == goal:
                return new_path

            visited.add((nx, ny))
            queue.append((nx, ny, new_path))

    return None


def _bfs_pathfind_obstacles(
    terrain_info: list, npc_set: set, obstacle_map: dict,
    start_x: int, start_y: int, goal_x: int, goal_y: int,
    field_moves: dict[str, bool],
    width: int = 32, height: int = 32,
) -> tuple[list[str] | None, list[dict]]:
    """BFS that treats clearable obstacles as passable when skills are available.

    Returns (path, obstacles_crossed) where obstacles_crossed is a list of
    obstacle info dicts for each obstacle the path passes through.
    Returns (None, []) if no path found even with obstacles.
    """
    if not (0 <= start_x < width and 0 <= start_y < height):
        return None, []
    if not (0 <= goal_x < width and 0 <= goal_y < height):
        return None, []
    if (start_x, start_y) == (goal_x, goal_y):
        return [], []

    visited = {(start_x, start_y)}
    # Each queue entry: (x, y, path, obstacles_on_path)
    queue: deque[tuple[int, int, list[str], list[dict]]] = deque(
        [(start_x, start_y, [], [])]
    )

    while queue:
        x, y, path, obs_on_path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited:
                continue

            new_obs = list(obs_on_path)

            # Check if this tile is a clearable object obstacle
            if (nx, ny) in obstacle_map:
                ob = obstacle_map[(nx, ny)]
                if field_moves.get(ob["move"], False):
                    new_obs.append(ob)
                else:
                    continue  # skill not available, treat as blocked
            elif (nx, ny) in npc_set and (nx, ny) != (goal_x, goal_y):
                continue  # regular NPC or strength boulder
            else:
                # Normal terrain check
                passable, behavior = terrain_info[ny][nx]
                if not passable:
                    # Check if it's a terrain obstacle we can handle
                    if behavior in TERRAIN_OBSTACLE_INFO:
                        tinfo = TERRAIN_OBSTACLE_INFO[behavior]
                        if field_moves.get(tinfo["move"], False):
                            new_obs.append({
                                "type": tinfo["type"],
                                "move": tinfo["move"],
                                "badge": tinfo["badge"],
                                "x": nx, "y": ny,
                            })
                        else:
                            continue  # can't handle this terrain obstacle
                    else:
                        continue  # truly impassable

                # Directional warp check
                if passable and behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                    continue
                # Ledge direction check
                if passable and behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                    continue

            new_path = path + [direction]
            if (nx, ny) == (goal_x, goal_y):
                return new_path, new_obs

            visited.add((nx, ny))
            queue.append((nx, ny, new_path, new_obs))

    return None, []


# ── Level-constrained BFS (3D pathfinding) ──

def _bfs_pathfind_level(
    terrain_info: list, npc_set: set, elevation: dict,
    start_x: int, start_y: int, goal_x: int, goal_y: int,
    current_level: int, width: int = 32, height: int = 32,
) -> tuple[list[str] | None, dict[int, tuple[list[str], tuple[int, int], int]]]:
    """BFS pathfind restricted to a single elevation level.

    Returns (path_to_goal, reachable_ramps) where:
    - path_to_goal: direction list or None if goal unreachable on this level
    - reachable_ramps: {ramp_index: (path_to_ramp, (rx, ry), other_level)}
      for each ramp reachable from start on current_level
    """
    if not (0 <= start_x < width and 0 <= start_y < height):
        return None, {}
    if not (0 <= goal_x < width and 0 <= goal_y < height):
        return None, {}
    if (start_x, start_y) == (goal_x, goal_y):
        return [], {}

    level_map = elevation["level_map"]
    ramp_tiles = elevation["ramp_tiles"]

    def _tile_on_level(tx: int, ty: int, level: int) -> bool:
        key = (tx, ty)
        if key in ramp_tiles:
            ri = ramp_tiles[key]
            return level in (ri["from_level"], ri["to_level"])
        if key in level_map:
            return level in level_map[key]
        # No elevation data → accessible on any level
        return True

    goal = (goal_x, goal_y)
    visited = {(start_x, start_y)}
    queue: deque[tuple[int, int, list[str]]] = deque([(start_x, start_y, [])])
    reachable_ramps: dict[int, tuple[list[str], tuple[int, int], int]] = {}

    while queue:
        x, y, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited:
                continue
            if (nx, ny) in npc_set and (nx, ny) != goal:
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                continue

            # Directional warp check
            if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                continue
            # Ledge direction check
            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue
            # Directional block on SOURCE tile (0x30 blocks east, 0x31 blocks west)
            _, src_behavior = terrain_info[y][x]
            if src_behavior in DIRECTIONAL_BLOCKS and DIRECTIONAL_BLOCKS[src_behavior] == direction:
                continue

            # Level constraint
            if not _tile_on_level(nx, ny, current_level):
                continue

            new_path = path + [direction]
            visited.add((nx, ny))

            # Record ramp transitions to other levels
            ramp_key = (nx, ny)
            if ramp_key in ramp_tiles:
                ri = ramp_tiles[ramp_key]
                ramp_idx = ri["ramp_index"]
                if ramp_idx not in reachable_ramps:
                    if ri["from_level"] == current_level:
                        other = ri["to_level"]
                    elif ri["to_level"] == current_level:
                        other = ri["from_level"]
                    else:
                        other = None
                    if other is not None and other != current_level:
                        reachable_ramps[ramp_idx] = (new_path, (nx, ny), other)

            if (nx, ny) == (goal_x, goal_y):
                return new_path, reachable_ramps

            queue.append((nx, ny, new_path))

    return None, reachable_ramps


_DIR_DELTAS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def _bfs_pathfind_3d(
    terrain_info: list, npc_set: set, elevation: dict,
    start_x: int, start_y: int, goal_x: int, goal_y: int,
    start_level: int, width: int = 32, height: int = 32,
) -> list[str] | None:
    """Hierarchical 3D BFS: pathfind across elevation levels via ramp transitions.

    Tries direct BFS on the start level. If the goal is unreachable, brute-forces
    through reachable ramps: BFS to ramp → transition level → recurse.
    Depth-capped at _3D_MAX_DEPTH, wall-clock timeout at _3D_TIMEOUT seconds.
    """
    goal_levels = _get_tile_level(goal_x, goal_y, elevation)
    deadline = time.monotonic() + _3D_TIMEOUT

    def _search(
        sx: int, sy: int, level: int, depth: int, visited_ramps: frozenset[int],
    ) -> list[str] | None:
        if depth > _3D_MAX_DEPTH:
            return None
        if time.monotonic() > deadline:
            return None

        direct_path, reachable_ramps = _bfs_pathfind_level(
            terrain_info, npc_set, elevation,
            sx, sy, goal_x, goal_y,
            level, width=width, height=height,
        )

        if direct_path is not None:
            return direct_path

        if not reachable_ramps:
            return None

        # Sort ramps: toward target level first, then Manhattan to goal, then path length
        def _ramp_priority(item: tuple) -> tuple:
            ramp_idx, (path_to_ramp, _, other_level) = item
            toward_goal = 0 if (goal_levels and other_level in goal_levels) else 1
            # Use ramp midpoint for distance heuristic
            ri = None
            for r in elevation["ramps"]:
                if r["ramp_index"] == ramp_idx:
                    ri = r
                    break
            if ri:
                mid_c = (ri["col_range"][0] + ri["col_range"][1]) / 2
                mid_r = (ri["row_range"][0] + ri["row_range"][1]) / 2
                dist = abs(mid_c - goal_x) + abs(mid_r - goal_y)
            else:
                dist = 999.0
            return (toward_goal, dist, len(path_to_ramp))

        candidates = [
            (idx, data) for idx, data in reachable_ramps.items()
            if idx not in visited_ramps
        ]
        candidates.sort(key=_ramp_priority)

        best_path: list[str] | None = None

        for ramp_idx, (path_to_ramp, (rx, ry), other_level) in candidates:
            if time.monotonic() > deadline:
                break

            new_visited = visited_ramps | {ramp_idx}
            continuation = _search(rx, ry, other_level, depth + 1, new_visited)

            if continuation is not None:
                full_path = path_to_ramp + continuation
                if best_path is None or len(full_path) < len(best_path):
                    best_path = full_path

        return best_path

    return _search(start_x, start_y, start_level, 0, frozenset())


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
                    passable = (
                        ((not is_blocked) or behavior in WARP_PASSABLE or behavior in LEDGE_DIRECTIONS)
                        and behavior not in TERRAIN_OBSTACLES
                    )
                    combined[base_y + row][base_x + col] = (passable, behavior)

    return combined, grid_origin_x, grid_origin_y, grid_w, grid_h


def _build_multi_chunk_elevation(
    emu: EmulatorClient, map_id: int,
    terrain_info: list, grid_ox: int, grid_oy: int, grid_w: int, grid_h: int,
) -> dict | None:
    """Load BDHC for each chunk in the terrain grid, build combined elevation data.

    Returns elevation dict compatible with _bfs_pathfind_3d, or None if flat.
    """
    from renegade_mcp.map_state import (
        _tile_to_bdhc, get_matrix_for_map, parse_bdhc,
    )

    result = get_matrix_for_map(emu, map_id)
    if result is None:
        return None

    _matrix_id, mw, mh, _header_ids, terrain_ids = result

    min_cx = grid_ox // CHUNK_SIZE
    min_cy = grid_oy // CHUNK_SIZE
    num_cx = grid_w // CHUNK_SIZE
    num_cy = grid_h // CHUNK_SIZE

    # Pass 1: Load all BDHC data and collect flat heights
    chunk_bdhcs: dict[tuple[int, int], dict] = {}
    all_flat_heights: set[int] = set()

    for cy in range(min_cy, min_cy + num_cy):
        for cx in range(min_cx, min_cx + num_cx):
            if cy >= mh or cx >= mw:
                continue
            land_id = terrain_ids[cy][cx]
            if land_id == 0xFFFF:
                continue
            bdhc = parse_bdhc(land_id)
            if bdhc is None:
                continue

            chunk_bdhcs[(cx, cy)] = bdhc

            for plate in bdhc["plates"]:
                nx, ny, nz = bdhc["normals"][plate["normal"]]
                if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny) > 0.01:
                    d = bdhc["constants"][plate["constant"]]
                    all_flat_heights.add(round(-d / ny))

    if len(all_flat_heights) <= 1:
        return None  # Flat terrain across all loaded chunks

    sorted_heights = sorted(all_flat_heights)
    h2l = {h: i for i, h in enumerate(sorted_heights)}

    # Pass 2: Map tiles to levels across all chunks
    level_map: dict[tuple[int, int], list[int]] = {}
    ramp_tiles: dict[tuple[int, int], dict] = {}
    ramps: list[dict] = []

    for (cx, cy), bdhc in chunk_bdhcs.items():
        base_x = (cx - min_cx) * CHUNK_SIZE
        base_y = (cy - min_cy) * CHUNK_SIZE

        plates = bdhc["plates"]
        pts = bdhc["points"]
        norms = bdhc["normals"]
        consts = bdhc["constants"]

        # Flat plates → tile level assignments
        for row in range(CHUNK_SIZE):
            for col in range(CHUNK_SIZE):
                gx = base_x + col
                gy = base_y + row
                if gx >= grid_w or gy >= grid_h:
                    continue
                passable, _ = terrain_info[gy][gx]
                if not passable:
                    continue

                x, z = _tile_to_bdhc(col, row)
                levels: set[int] = set()
                for plate in plates:
                    x1, z1 = pts[plate["p1"]]
                    x2, z2 = pts[plate["p2"]]
                    if not (min(x1, x2) <= x <= max(x1, x2)
                            and min(z1, z2) <= z <= max(z1, z2)):
                        continue
                    nx, ny, nz = norms[plate["normal"]]
                    if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny) > 0.01:
                        d = consts[plate["constant"]]
                        h = round(-d / ny)
                        if h in h2l:
                            levels.add(h2l[h])
                if levels:
                    level_map[(gx, gy)] = sorted(levels)

        # Ramp plates
        for plate in plates:
            nx, ny, nz = norms[plate["normal"]]
            if abs(nx) < 0.01 and abs(nz) < 0.01:
                continue
            if abs(ny) < 0.01:
                continue

            x1, z1 = pts[plate["p1"]]
            x2, z2 = pts[plate["p2"]]
            d = consts[plate["constant"]]

            corners = [
                (min(x1, x2), min(z1, z2)), (min(x1, x2), max(z1, z2)),
                (max(x1, x2), min(z1, z2)), (max(x1, x2), max(z1, z2)),
            ]
            corner_heights = [
                round(-(nx * cx_ + nz * cz + d) / ny) for cx_, cz in corners
            ]
            h_max, h_min = max(corner_heights), min(corner_heights)

            from_level = h2l.get(h_max)
            to_level = h2l.get(h_min)
            if from_level is None or to_level is None:
                continue

            direction = (
                ("south" if nz > 0 else "north")
                if abs(nz) >= abs(nx) else ("east" if nx > 0 else "west")
            )

            col_min = int((min(x1, x2) + 256) / 16)
            col_max = int((max(x1, x2) + 256) / 16)
            row_min = int((min(z1, z2) + 256) / 16)
            row_max = int((max(z1, z2) + 256) / 16)

            ramp_info = {
                "ramp_index": len(ramps),
                "col_range": (base_x + col_min, base_x + col_max),
                "row_range": (base_y + row_min, base_y + row_max),
                "from_level": from_level,
                "to_level": to_level,
                "direction": direction,
            }
            ramps.append(ramp_info)

            for r in range(row_min, row_max):
                for c in range(col_min, col_max):
                    gx = base_x + c
                    gy = base_y + r
                    if 0 <= gx < grid_w and 0 <= gy < grid_h:
                        passable, _ = terrain_info[gy][gx]
                        if passable:
                            ramp_tiles[(gx, gy)] = ramp_info

    levels_info = [{"level": h2l[h], "height": h} for h in sorted_heights]

    return {
        "level_map": level_map,
        "ramp_tiles": ramp_tiles,
        "ramps": ramps,
        "levels": levels_info,
        "height_to_level": h2l,
    }


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

    npc_set = set(ctx.get("sign_tiles", set()))
    npc_set.update(ctx.get("dynamic_blocks", set()))
    for nx, ny in current_npcs.values():
        rx, ry = nx - ox, ny - oy
        if 0 <= rx < w and 0 <= ry < h:
            npc_set.add((rx, ry))

    sx = player_x - ox
    sy = player_y - oy

    # Use 3D BFS when elevation data is available
    elevation = ctx.get("elevation")
    if elevation is not None:
        emu = ctx["emu"]
        from renegade_mcp.map_state import read_player_height
        player_level = _height_to_level(
            read_player_height(emu), elevation,
            tile_x=sx, tile_y=sy,
        )
        if player_level is not None:
            path_3d = _bfs_pathfind_3d(
                ctx["terrain_info"], npc_set, elevation,
                sx, sy, ctx["goal_x"], ctx["goal_y"],
                player_level, width=w, height=h,
            )
            if path_3d is not None:
                return path_3d
            # 3D BFS failed (disconnected level, dynamic terrain) — fall through to 2D

    return _bfs_pathfind(
        ctx["terrain_info"], npc_set,
        sx, sy, ctx["goal_x"], ctx["goal_y"],
        width=w, height=h,
    )


# ── Auto-flee for wild encounters during navigation ──

MAX_FLEE_ENCOUNTERS = 10  # safety cap to prevent infinite loops
POST_BATTLE_SETTLE = 300  # frames to wait after battle ends before resuming nav

_BATTLE_OVER = {"BATTLE_ENDED"}
_FAINT_STATES = {"FAINT_SWITCH", "FAINT_FORCED"}


def _flee_wild_battle(emu: EmulatorClient) -> dict[str, Any]:
    """Flee a wild battle, retrying on failure. Returns success/failure info.

    Mirrors auto_grind._run_battle pattern but simplified for navigation use.
    """
    from renegade_mcp.turn import battle_turn as _battle_turn

    max_attempts = 10
    for attempt in range(max_attempts):
        result = _battle_turn(emu, run=True)
        state = result.get("final_state", "")

        if state in _BATTLE_OVER:
            return {"success": True, "attempts": attempt + 1}

        if state == "WAIT_FOR_ACTION":
            # Escape failed, enemy got a free turn — retry
            continue

        if state in _FAINT_STATES:
            return {"success": False, "reason": "fainted", "state": state}

        return {"success": False, "reason": f"unexpected state: {state}"}

    return {"success": False, "reason": "max flee attempts reached"}


def _try_flee_encounter(
    emu: EmulatorClient, encounter: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """If encounter is a wild battle, flee it and return to overworld.

    Returns (encounter_or_none, flee_entry_or_none).
    - Wild battle fled successfully: (None, flee_log_entry) — encounter cleared.
    - Wild battle flee failed: (original encounter, flee_log_entry with failure).
    - Trainer battle or dialogue: (original encounter, None) — unchanged.
    - No encounter: (None, None).
    """
    if encounter is None:
        return None, None

    if encounter.get("encounter") != "battle":
        # Dialogue/cutscene — pass through unchanged
        return encounter, None

    if encounter.get("dialogue"):
        # Trainer battle — can't flee, pass through
        return encounter, None

    # Wild battle — extract species and flee
    species = "unknown"
    for b in (encounter.get("battle_state") or []):
        if b.get("side") == "enemy":
            species = b.get("species", "unknown")
            break

    flee_result = _flee_wild_battle(emu)
    flee_entry: dict[str, Any] = {"type": "wild", "species": species}

    if flee_result["success"]:
        flee_entry["fled"] = True
        flee_entry["attempts"] = flee_result["attempts"]
        emu.advance_frames(POST_BATTLE_SETTLE)
        return None, flee_entry
    else:
        flee_entry["fled"] = False
        flee_entry["reason"] = flee_result["reason"]
        return encounter, flee_entry


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
            # Validate: text buffer can contain stale data during NPC approach
            # animations. Only trust it when msgBox=1 (dialogue box visible).
            mgr = _find_script_manager(emu)
            if mgr is not None:
                ss = _read_script_state(emu, mgr)
                if not ss["is_msg_box_open"]:
                    # msgBox=0: text is pre-positioned, not yet displayed.
                    # If a script is running, keep polling — dialogue will
                    # appear once the approach animation finishes.
                    if ss["ctx0_ptr"]:
                        ctx0 = _read_context_state(emu, ss["ctx0_ptr"])
                        if ctx0["state"] in (CTX_RUNNING, CTX_WAITING):
                            emu.advance_frames(POST_NAV_POLL_FRAMES)
                            continue
                    # No active script — stale buffer data, skip.
                    emu.advance_frames(POST_NAV_POLL_FRAMES)
                    continue

            # msgBox is open — real dialogue. Auto-advance.
            adv_result = advance_dialogue(emu)

            # After dialogue, check if it transitioned into a battle
            battlers = read_battle(emu)
            if battlers:
                prompt_result = _wait_for_action_prompt(emu)
                battle_state = read_battle(emu)
                result: dict[str, Any] = {
                    "encounter": "battle",
                    "dialogue": adv_result,
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

            return {
                "encounter": "dialogue",
                "dialogue": adv_result,
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
    For directional warps (0x62, 0x63, etc.), walks in the required direction.
    Waits for map transition to complete and returns new position info.

    Returns dict with new map info, or None if no transition occurred.
    """
    activation = DOOR_ACTIVATION.get(behavior)
    if activation is None:
        activation = DIRECTIONAL_WARP.get(behavior)

    # For doors/warps that need a direction press, do it now
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
                "new_position": _pos_with_map(final_x, final_y, final_map),
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
    hold = _get_move_hold(emu)

    # Walk to first pacing tile if needed
    for direction in path_to_a:
        if steps_taken >= SEEK_MAX_STEPS:
            break
        old_map, old_x, old_y = _read_position(emu)
        emu.advance_frames(hold, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)
        new_map, new_x, new_y = _read_position(emu)
        steps_taken += 1

        if (old_x, old_y, old_map) == (new_x, new_y, new_map):
            encounter = _post_nav_check(emu)
            if encounter is not None:
                return {"result": "encounter", "steps_taken": steps_taken,
                        "encounter": encounter}
            return {"result": "blocked", "steps_taken": steps_taken,
                    "position": _pos_with_map(new_x, new_y, new_map)}

    # Pace back and forth
    current_dir = dir_a_to_b

    while steps_taken < SEEK_MAX_STEPS:
        old_map, old_x, old_y = _read_position(emu)
        emu.advance_frames(hold, buttons=[current_dir])
        emu.advance_frames(WAIT_FRAMES)
        new_map, new_x, new_y = _read_position(emu)
        steps_taken += 1

        if (old_x, old_y, old_map) == (new_x, new_y, new_map):
            encounter = _post_nav_check(emu)
            if encounter is not None:
                return {"result": "encounter", "steps_taken": steps_taken,
                        "encounter": encounter}
            return {"result": "blocked", "steps_taken": steps_taken,
                    "position": _pos_with_map(new_x, new_y, new_map)}

        current_dir = dir_b_to_a if current_dir == dir_a_to_b else dir_a_to_b

    # Max steps — final check
    encounter = _post_nav_check(emu)
    if encounter is not None:
        return {"result": "encounter", "steps_taken": steps_taken,
                "encounter": encounter}

    final_map, final_x, final_y = _read_position(emu)
    return {"result": "max_steps", "steps_taken": steps_taken,
            "position": _pos_with_map(final_x, final_y, final_map)}


# ── Cycling road movement ──
# Route 206 bridge body tiles (0x71) auto-slide the player south at ~4f/tile.
# Timings from empirical testing (melonDS JIT):
#   South: passive slide at ~4 frames/tile, no input needed
#   North: ~8 frames/tile with UP held (first step slides south, then north takes over)
#   East/West: ~4 frames/tile lateral, but each lateral step also slides 1 tile south
CYCLING_ROAD_SLIDE_RATE = 4      # frames per tile when sliding south
CYCLING_ROAD_UPHILL_HOLD = 12    # frames to hold UP per tile (padded for safety)
CYCLING_ROAD_LATERAL_HOLD = 4    # frames to hold LEFT/RIGHT per tile
CYCLING_ROAD_POLL_INTERVAL = 2   # frames between position checks
CYCLING_ROAD_MAX_WAIT = 600      # max frames to wait for a slide to complete (~10 sec)


def _get_current_tile_behavior(emu: EmulatorClient) -> int:
    """Read the terrain behavior byte at the player's current tile."""
    from renegade_mcp.map_state import get_map_state
    state = get_map_state(emu)
    if state is None:
        return 0
    terrain = state["terrain"]
    lx, ly = state["local_px"], state["local_py"]
    if 0 <= ly < len(terrain) and 0 <= lx < len(terrain[ly]):
        return terrain[ly][lx] & 0x00FF
    return 0


def _navigate_cycling_road(
    emu: EmulatorClient, target_x: int, target_y: int,
) -> dict[str, Any]:
    """Navigate on the cycling road where auto-slide is active.

    Strategy — order matters because every action on bridge body tiles drifts south:
      1. Normal bike steps until we reach bridge body tiles (0x71)
      2. North (uphill): hold UP continuously, polling position
      3. Lateral (east/west): hold direction, accept south drift per step
      4. South: let auto-slide carry us (no input), or normal step on non-bridge
    Final Y adjustment after lateral moves to correct south drift.
    """
    start_map, start_x, start_y = _read_position(emu)
    cur_x, cur_y = start_x, start_y
    steps_log: list[str] = []
    total_frames = 0
    max_iters = 200

    for _ in range(max_iters):
        if cur_x == target_x and cur_y == target_y:
            break

        dx = target_x - cur_x
        dy = target_y - cur_y
        behavior = _get_current_tile_behavior(emu)
        on_bridge = (behavior == 0x71)

        # ── Phase: Normal ground movement (not on bridge body) ──
        if not on_bridge:
            if dy > 0:
                # Step south onto or toward bridge
                emu.advance_frames(BIKE_HOLD_FRAMES, buttons=["down"])
                emu.advance_frames(WAIT_FRAMES)
                total_frames += BIKE_HOLD_FRAMES + WAIT_FRAMES
            elif dy < 0:
                emu.advance_frames(BIKE_HOLD_FRAMES, buttons=["up"])
                emu.advance_frames(WAIT_FRAMES)
                total_frames += BIKE_HOLD_FRAMES + WAIT_FRAMES
            elif dx != 0:
                btn = "left" if dx < 0 else "right"
                emu.advance_frames(BIKE_HOLD_FRAMES, buttons=[btn])
                emu.advance_frames(WAIT_FRAMES)
                total_frames += BIKE_HOLD_FRAMES + WAIT_FRAMES
            else:
                break

            _, new_x, new_y = _read_position(emu)
            if (new_x, new_y) != (cur_x, cur_y):
                steps_log.append(f"step ({cur_x},{cur_y})→({new_x},{new_y})")
            cur_x, cur_y = new_x, new_y
            continue

        # ── Phase: On bridge body — uphill first (before lateral) ──
        if dy < 0:
            # Hold UP continuously until target Y or stall
            wait = 0
            while cur_y > target_y and wait < CYCLING_ROAD_MAX_WAIT:
                emu.advance_frames(4, buttons=["up"])
                wait += 4
                total_frames += 4
                _, new_x, new_y = _read_position(emu)
                if new_y != cur_y:
                    steps_log.append(f"up ({cur_x},{cur_y})→({new_x},{new_y})")
                    cur_x, cur_y = new_x, new_y
            continue

        # ── Phase: On bridge body — lateral moves ──
        if dx != 0:
            # Press direction for exactly 4 frames (1 bike tile), then poll.
            # Don't add idle settle frames — that causes south slide.
            btn = "left" if dx < 0 else "right"
            emu.advance_frames(4, buttons=[btn])
            total_frames += 4
            # Poll until lateral movement registers (may take a few frames)
            for _ in range(8):
                _, new_x, new_y = _read_position(emu)
                if new_x != cur_x:
                    break
                emu.advance_frames(1, buttons=[btn])
                total_frames += 1
            _, new_x, new_y = _read_position(emu)
            if (new_x, new_y) != (cur_x, cur_y):
                steps_log.append(f"{btn} ({cur_x},{cur_y})→({new_x},{new_y})")
            cur_x, cur_y = new_x, new_y
            continue

        # ── Phase: On bridge body — southbound (auto-slide) ──
        if dy > 0:
            wait = 0
            while cur_y < target_y and wait < CYCLING_ROAD_MAX_WAIT:
                emu.advance_frames(CYCLING_ROAD_POLL_INTERVAL)
                wait += CYCLING_ROAD_POLL_INTERVAL
                total_frames += CYCLING_ROAD_POLL_INTERVAL
                _, new_x, new_y = _read_position(emu)
                if new_y != cur_y:
                    steps_log.append(f"slide ({cur_x},{cur_y})→({new_x},{new_y})")
                    cur_x, cur_y = new_x, new_y
                    if _get_current_tile_behavior(emu) != 0x71:
                        break
            continue

        # Should not reach here
        break

    final_map, final_x, final_y = _read_position(emu)
    reached = (final_x == target_x and final_y == target_y)

    result: dict[str, Any] = {
        "cycling_road": True,
        "reached_target": reached,
        "steps_log": steps_log,
        "total_frames": total_frames,
        "start": _pos_with_map(start_x, start_y, start_map),
        "final": _pos_with_map(final_x, final_y, final_map),
    }
    if not reached:
        result["note"] = (
            f"Stopped at ({final_x},{final_y}), target was ({target_x},{target_y}). "
            f"Possible obstacle (trainer NPC, wall, or end of bridge)."
        )
    return result


# ── Path execution ──

def _execute_path(
    emu: EmulatorClient,
    directions: list[str],
    track_npcs: bool = False,
    repath_ctx: dict | None = None,
    hold_frames: int = HOLD_FRAMES,
) -> tuple[bool, int, int, dict]:
    """Execute directions, verifying each step.

    When repath_ctx is provided, tracks NPC positions and attempts BFS repath
    when NPCs block or move into the planned path.

    Args:
        hold_frames: Frames to hold per step (16 walking, 8 cycling).

    Returns (stopped_early, steps_taken, repaths_used, nav_info).
    nav_info contains compact summary data (map_change, blocked_at, npc_moves).
    """
    if repath_ctx is not None:
        track_npcs = True

    steps_taken = 0
    repaths_used = 0
    npc_move_count = 0
    map_changed = False
    prev_npcs = _read_npc_positions(emu) if track_npcs else {}
    nav_info: dict = {}

    i = 0
    while i < len(directions):
        direction = directions[i]
        old_map, old_x, old_y = _read_position(emu)

        emu.advance_frames(hold_frames, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)

        new_map, new_x, new_y = _read_position(emu)

        blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map
        if blocked:
            # Slow terrain (deep snow, ice) may not complete a step within
            # hold_frames + WAIT_FRAMES. Retry with full press cycles —
            # the first press may have only turned the character, or the
            # animation may still be in progress.
            for _ in range(SLOW_TERRAIN_RETRIES):
                emu.advance_frames(hold_frames, buttons=[direction])
                emu.advance_frames(WAIT_FRAMES)
                new_map, new_x, new_y = _read_position(emu)
                blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map
                if not blocked:
                    break
        if not blocked:
            steps_taken += 1

        # Track NPC movement (needed for repathing)
        has_npc_changes = False
        if track_npcs:
            curr_npcs = _read_npc_positions(emu)
            changes = _detect_npc_changes(prev_npcs, curr_npcs)
            if changes:
                has_npc_changes = True
                npc_move_count += 1
            prev_npcs = curr_npcs

        if blocked:
            # Mark the blocked destination so future repaths avoid it.
            # Handles dynamic terrain (gym puzzles, rotated clock hands)
            # where ROM says passable but the game's 3D collision blocks.
            if repath_ctx is not None:
                dx, dy = _DIR_DELTAS.get(direction, (0, 0))
                bx = old_x + dx - repath_ctx["grid_ox"]
                by = old_y + dy - repath_ctx["grid_oy"]
                repath_ctx.setdefault("dynamic_blocks", set()).add((bx, by))

            # Check if this is the final step — blocked on the target tile
            # itself (NPC, signpost, etc.). Skip repath since the target is
            # inherently occupied; just stop adjacent.
            if i == len(directions) - 1:
                nav_info["blocked_at"] = {"x": old_x, "y": old_y, "step": steps_taken}
                nav_info["blocked_on_final_step"] = True
                return True, steps_taken, repaths_used, nav_info

            # Attempt repath around obstacle
            if repath_ctx is not None and repaths_used < MAX_REPATHS:
                new_path = _try_repath(repath_ctx, prev_npcs, new_x, new_y)
                if new_path is not None and len(new_path) > 0:
                    repaths_used += 1
                    directions = directions[:i] + new_path
                    continue  # Retry from same index with new path
            nav_info["blocked_at"] = {"x": old_x, "y": old_y, "step": steps_taken}
            return True, steps_taken, repaths_used, nav_info

        if new_map != old_map:
            map_changed = True

        # Proactive repath when NPCs moved and steps remain
        if (repath_ctx is not None and has_npc_changes
                and repaths_used < MAX_REPATHS and i + 1 < len(directions)):
            new_path = _try_repath(repath_ctx, prev_npcs, new_x, new_y)
            if new_path is None:
                nav_info["repath_failed"] = True
                return True, steps_taken, repaths_used, nav_info
            remaining = directions[i + 1:]
            if new_path != remaining:
                repaths_used += 1
                directions = directions[:i + 1] + new_path

        i += 1

    if map_changed:
        nav_info["map_changed"] = True
    if npc_move_count > 0:
        nav_info["npc_moves"] = npc_move_count

    return False, steps_taken, repaths_used, nav_info


# ── Public API ──

def _validate_path(
    terrain_info: list,
    start_x: int,
    start_y: int,
    directions: list[str],
    width: int = 32,
    height: int = 32,
) -> tuple[bool, int, str, tuple[int, int]]:
    """Simulate a path on the terrain grid and check for collisions.

    Returns (ok, step_index, direction, tile) where:
    - ok=True, step_index=-1 means full path is clear
    - ok=True, step_index>=0, direction="transition" means path is valid but
      should be trimmed at step_index (inclusive) — that step walks off a
      door/stair tile in its activation direction, triggering a map transition.
    - ok=False means step_index'th direction hits a wall at tile (x, y)

    Off-grid tiles are allowed (map transitions).
    """
    cx, cy = start_x, start_y
    deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    for i, d in enumerate(directions):
        # Check if current tile is a door/stair whose activation direction
        # matches this step — if so, this step triggers a map transition
        # regardless of what's on the destination tile.
        if 0 <= cx < width and 0 <= cy < height:
            _, cur_behavior = terrain_info[cy][cx]
            activation = DOOR_ACTIVATION.get(cur_behavior)
            if activation is not None and activation == d:
                dx, dy = deltas[d]
                nx, ny = cx + dx, cy + dy
                return True, i, "transition", (nx, ny)

        dx, dy = deltas[d]
        nx, ny = cx + dx, cy + dy

        # Off-grid = possible map transition, allow it
        if not (0 <= nx < width and 0 <= ny < height):
            cx, cy = nx, ny
            continue

        passable, behavior = terrain_info[ny][nx]
        if not passable:
            return False, i, d, (nx, ny)

        # Stepping onto a directional warp in its activation direction = transition
        if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] == d:
            return True, i, "transition", (nx, ny)

        cx, cy = nx, ny

    return True, -1, "", (0, 0)


def navigate_manual(emu: EmulatorClient, directions_str: str, flee_encounters: bool = False) -> dict[str, Any]:
    """Walk a manual path. Returns result dict with steps taken and final position."""
    directions = parse_directions(directions_str)

    valid = {"up", "down", "left", "right"}
    invalid = [d for d in directions if d not in valid]
    if invalid:
        return {"error": f"Invalid direction(s): {invalid}. Use up/down/left/right or u/d/l/r."}

    if not directions:
        return {"error": "No directions provided."}

    # Cycling road safety check — forced downhill slide makes step counting unreliable
    if is_on_cycling_road(emu):
        return {
            "error": (
                "Cannot navigate on Cycling Road (Route 206). The game forces "
                "downhill sliding on the bicycle, which causes unpredictable "
                "multi-tile movement per step. Use navigate_to() instead — it "
                "has cycling road awareness and can handle the slide."
            ),
            "cycling_road": True,
        }

    # Pre-validate path against terrain before walking
    start_map, start_x, start_y = _read_position(emu)
    expected_transition = False
    state = get_map_state(emu)
    if state is not None:
        origin_x = state.get("origin_x", 0)
        origin_y = state.get("origin_y", 0)
        terrain_info, _, _ = _build_terrain_info(state["terrain"], state["objects"])
        local_x = start_x - origin_x
        local_y = start_y - origin_y
        h = len(terrain_info)
        w = len(terrain_info[0]) if h > 0 else 32

        ok, step_idx, step_dir, (wall_x, wall_y) = _validate_path(
            terrain_info, local_x, local_y, directions, width=w, height=h,
        )
        if not ok:
            global_wall_x = wall_x + origin_x
            global_wall_y = wall_y + origin_y
            return {
                "error": (
                    f"Path would hit a wall at step {step_idx + 1} ({step_dir}): "
                    f"tile ({global_wall_x}, {global_wall_y}) is impassable. "
                    f"No movement was performed. "
                    f"Tip: use `view_map` to see the terrain layout, "
                    f"or `navigate_to(x, y)` for automatic pathfinding around obstacles!"
                ),
                "blocked_step": step_idx + 1,
                "blocked_direction": step_dir,
                "blocked_tile": {"x": global_wall_x, "y": global_wall_y},
                "start": _pos_with_map(start_x, start_y, start_map),
            }
        # Trim path at door/stair transition — that step is the last before map change
        expected_transition = step_idx >= 0 and step_dir == "transition"
        if expected_transition:
            directions = directions[:step_idx + 1]

    total_path = _summarize_path(directions)
    total_steps = 0
    flee_log: list[dict[str, Any]] = []
    remaining = directions
    hold = _get_move_hold(emu)

    for _ in range(MAX_FLEE_ENCOUNTERS if flee_encounters else 1):
        stopped_early, steps_taken, _, nav_info = _execute_path(emu, remaining, track_npcs=True, hold_frames=hold)
        total_steps += steps_taken

        # Post-navigation: poll for encounter or dialogue (also serves as settle)
        encounter = _post_nav_check(emu)

        if not flee_encounters or encounter is None:
            break

        encounter, flee_entry = _try_flee_encounter(emu, encounter)
        if flee_entry:
            flee_log.append(flee_entry)
        if encounter is not None:
            # Trainer battle, dialogue, or flee failed — stop
            break
        if not flee_entry or not flee_entry.get("fled"):
            break

        # Fled successfully — resume remaining directions from current position
        remaining = remaining[steps_taken:]
        if not remaining:
            stopped_early = False
            break
    else:
        # Hit MAX_FLEE_ENCOUNTERS cap — treat as stopped early
        stopped_early = True

    final_map, final_x, final_y = _read_position(emu)

    result: dict[str, Any] = {
        "path": total_path,
        "steps": total_steps,
        "start": _pos_with_map(start_x, start_y, start_map),
        "final": _pos_with_map(final_x, final_y, final_map),
    }

    if stopped_early:
        result["stopped_early"] = True
        result.update(nav_info)
    if encounter is not None:
        result["encounter"] = encounter
    if flee_log:
        result["flee_log"] = flee_log
        fled_count = sum(1 for e in flee_log if e.get("fled"))
        if fled_count:
            result["encounters_fled"] = fled_count
        failed = next((e for e in flee_log if not e.get("fled") and e.get("reason")), None)
        if failed:
            reason = failed["reason"]
            species = failed.get("species", "unknown")
            if "fainted" in reason:
                result["flee_failed"] = (
                    f"Pokemon fainted while fleeing wild {species}. "
                    f"Heal party before continuing."
                )
            else:
                result["flee_failed"] = f"Flee failed against wild {species}: {reason}"

    # Check if an expected warp transition didn't happen
    if expected_transition and final_map == start_map:
        # Dialogue/battle may have preempted the warp — check before declaring failure
        if encounter is None:
            encounter = _post_nav_check(emu)
            if encounter:
                result["encounter"] = encounter
        if encounter is None:
            result["warp_failed"] = True
            result["note"] = (
                "Path ended at a warp/door tile but no map transition occurred. "
                "Possible causes: locked door (key item required), story flag not yet "
                "set, or an event/script blocking entry. Check the scene manually "
                "(screenshot + read_dialogue)."
            )

    return result


def _classify_objects_for_grid(
    objects: list, grid_ox: int, grid_oy: int, grid_w: int, grid_h: int,
) -> tuple[set, dict]:
    """Classify map objects into npc_set and obstacle_map for a given grid region."""
    npc_set: set[tuple[int, int]] = set()
    obstacle_map: dict[tuple[int, int], dict] = {}
    for obj in objects:
        if obj["index"] == 0:
            continue
        lx = obj["x"] - grid_ox
        ly = obj["y"] - grid_oy
        if not (0 <= lx < grid_w and 0 <= ly < grid_h):
            continue

        gfx_id = obj.get("graphics_id", 0)
        if gfx_id in CLEARABLE_OBSTACLES:
            info = HM_OBSTACLES[gfx_id]
            obstacle_map[(lx, ly)] = {
                "type": info["type"],
                "move": info["move"],
                "badge": info["badge"],
                "gfx_id": gfx_id,
                "global_x": obj["x"],
                "global_y": obj["y"],
            }
        elif gfx_id in PUZZLE_OBSTACLES:
            npc_set.add((lx, ly))
        else:
            npc_set.add((lx, ly))
    return npc_set, obstacle_map


def _dedupe_obstacles(obstacles: list[dict]) -> list[dict]:
    """Remove duplicate obstacles (same type at same position)."""
    seen: set[tuple[str, int, int]] = set()
    result = []
    for ob in obstacles:
        key = (ob["type"], ob.get("global_x", ob.get("x", 0)), ob.get("global_y", ob.get("y", 0)))
        if key not in seen:
            seen.add(key)
            result.append(ob)
    return result


def navigate_to(
    emu: EmulatorClient, target_x: int, target_y: int,
    path_choice: str | None = None,
    flee_encounters: bool = False,
) -> dict[str, Any]:
    """Pathfind to target tile using BFS. Obstacle-aware with dual pathfinding.

    When obstacles (Rock Smash rocks, Cut trees, water, etc.) block or shorten
    the path, returns an obstacle_choice/obstacle_required status instead of
    moving, letting the caller decide. Call again with path_choice="obstacle"
    or path_choice="clean" to execute.

    When flee_encounters=True, automatically flees wild encounters and resumes
    navigation. Trainer battles (detected by pre-battle dialogue) are still
    returned to the caller since they can't be fled.

    Args:
        target_x, target_y: Target tile coordinates.
        path_choice: None (default — evaluate and ask if obstacles involved),
                     "obstacle" (take the path through obstacles),
                     "clean" (take the obstacle-free path).
        flee_encounters: If True, auto-flee wild battles and resume navigation.
    """
    hold = _get_move_hold(emu)
    if not flee_encounters:
        return _navigate_to_impl(emu, target_x, target_y, path_choice=path_choice, hold_frames=hold)

    flee_log: list[dict[str, Any]] = []
    for _ in range(MAX_FLEE_ENCOUNTERS):
        result = _navigate_to_impl(emu, target_x, target_y, path_choice=path_choice, hold_frames=hold)

        # Only path_choice matters on the first call — after that we're repathing
        path_choice = None

        enc = result.get("encounter")
        if enc is None:
            # No encounter — navigation completed (or hit a non-encounter stop)
            break

        if enc.get("encounter") != "battle":
            # Dialogue/cutscene — could be a signpost, but could also be a
            # scripted event that repositions the player or blocks the path.
            # Halt and let the caller see what happened.
            break

        if enc.get("dialogue"):
            # Trainer battle: pre-battle dialogue present → can't flee.
            # Battle state is ready for the caller to handle.
            break

        # Extract species from battle state for the log
        species = "unknown"
        for b in (enc.get("battle_state") or []):
            if b.get("side") == "enemy":
                species = b.get("species", "unknown")
                break

        # Wild battle — flee it
        flee_result = _flee_wild_battle(emu)
        if not flee_result["success"]:
            reason = flee_result["reason"]
            flee_log.append({"type": "wild", "species": species, "fled": False, "reason": reason})
            result["flee_log"] = flee_log
            if "fainted" in reason:
                result["flee_failed"] = (
                    f"Pokemon fainted while fleeing wild {species}. "
                    f"Heal party before continuing."
                )
            else:
                result["flee_failed"] = f"Flee failed against wild {species}: {reason}"
            break

        flee_log.append({
            "type": "wild",
            "species": species,
            "fled": True,
            "attempts": flee_result["attempts"],
        })
        # Wait for overworld to fully load before re-navigating
        emu.advance_frames(POST_BATTLE_SETTLE)
        # Loop will re-call _navigate_to_impl from current position

    if flee_log:
        result["flee_log"] = flee_log
        result["encounters_fled"] = sum(1 for e in flee_log if e.get("fled"))

    return result


def _navigate_to_impl(
    emu: EmulatorClient, target_x: int, target_y: int,
    path_choice: str | None = None,
    hold_frames: int | None = None,
) -> dict[str, Any]:
    """Core navigate_to logic. See navigate_to() for the public API."""
    if hold_frames is None:
        hold_frames = _get_move_hold(emu)

    # Cycling road dispatch — forced downhill slide requires special movement
    if is_on_cycling_road(emu, target_x, target_y):
        return _navigate_cycling_road(emu, target_x, target_y)

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

    # ── Build terrain, NPC set, and obstacle map ──
    if is_global and chunked:
        mc_result = _build_multi_chunk_terrain(emu, map_id, px, py, target_x, target_y)
        if mc_result is None:
            return {"error": "Could not load multi-chunk terrain."}

        terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc_result
        npc_set, obstacle_map = _classify_objects_for_grid(
            state["objects"], grid_ox, grid_oy, grid_w, grid_h,
        )

        # Block sign activation tiles (tile south of sign, auto-triggers dialogue)
        for sx, sy in read_sign_tiles_from_rom(emu, map_id):
            lx, ly = sx - grid_ox, sy - grid_oy
            if 0 <= lx < grid_w and 0 <= ly < grid_h:
                npc_set.add((lx, ly))

        rel_px = px - grid_ox
        rel_py = py - grid_oy
        rel_tx = target_x - grid_ox
        rel_ty = target_y - grid_oy
        bfs_sx, bfs_sy = rel_px, rel_py
        bfs_tx, bfs_ty = rel_tx, rel_ty
        bfs_w, bfs_h = grid_w, grid_h
        repath_ox, repath_oy = grid_ox, grid_oy
    else:
        if target_x > 31 or target_y > 31:
            target_x = target_x - origin_x
            target_y = target_y - origin_y

        terrain_info, npc_set, obstacle_map = _build_terrain_info(
            state["terrain"], state["objects"],
        )

        # Block sign activation tiles (tile south of sign, auto-triggers dialogue)
        for sx, sy in read_sign_tiles_from_rom(emu, map_id):
            lx, ly = sx - origin_x, sy - origin_y
            if 0 <= lx < 32 and 0 <= ly < 32:
                npc_set.add((lx, ly))

        bfs_sx, bfs_sy = local_px, local_py
        bfs_tx, bfs_ty = target_x, target_y
        bfs_w, bfs_h = 32, 32
        grid_ox, grid_oy = origin_x, origin_y
        grid_w, grid_h = 32, 32
        repath_ox, repath_oy = origin_x, origin_y

    # Pre-compute sign activation tiles (grid-relative) for repath
    sign_block_set: set[tuple[int, int]] = set()
    for sx, sy in read_sign_tiles_from_rom(emu, map_id):
        lx, ly = sx - repath_ox, sy - repath_oy
        if 0 <= lx < bfs_w and 0 <= ly < bfs_h:
            sign_block_set.add((lx, ly))

    repath_ctx = {
        "terrain_info": terrain_info,
        "goal_x": bfs_tx, "goal_y": bfs_ty,
        "grid_w": bfs_w, "grid_h": bfs_h,
        "grid_ox": repath_ox, "grid_oy": repath_oy,
        "sign_tiles": sign_block_set,
    }

    # ── 3D elevation detection ──
    elevation = None
    player_level = None
    is_3d = False

    if is_global and chunked:
        # Multi-chunk: load BDHC per chunk, build combined elevation
        mc_elev = _build_multi_chunk_elevation(
            emu, map_id, terrain_info, grid_ox, grid_oy, grid_w, grid_h,
        )
        if mc_elev is not None:
            player_level = _height_to_level(
                read_player_height(emu), mc_elev,
                tile_x=bfs_sx, tile_y=bfs_sy,
            )
            if player_level is not None:
                elevation = mc_elev
                is_3d = True
    else:
        land_id = get_land_data_id(emu, map_id, px, py)
        if land_id is not None:
            bdhc = parse_bdhc(land_id)
            if bdhc is not None:
                elevation = analyze_elevation(bdhc, state["terrain"])
                if elevation is not None:
                    player_level = _height_to_level(
                        read_player_height(emu), elevation,
                        tile_x=bfs_sx, tile_y=bfs_sy,
                    )
                    if player_level is not None:
                        is_3d = True

    if is_3d:
        repath_ctx["elevation"] = elevation
        repath_ctx["emu"] = emu

        # ── 3D pathfinding (replaces dual BFS for elevated maps) ──
        combined_npc_set = npc_set | set(obstacle_map.keys())
        path_3d = _bfs_pathfind_3d(
            terrain_info, combined_npc_set, elevation,
            bfs_sx, bfs_sy, bfs_tx, bfs_ty,
            player_level, width=bfs_w, height=bfs_h,
        )

        if path_3d is None:
            # 3D BFS failed — fall back to 2D BFS.  This handles:
            # - Disconnected elevation levels (e.g., L0 with no ramp to L1)
            # - Dynamic terrain changes (e.g., rotated clock puzzles in gyms)
            # - Multi-chunk overworld slopes that control camera, not walkability
            # The _try_repath fallback also drops to 2D when 3D fails mid-walk.
            is_3d = False
            elevation = None
            repath_ctx.pop("elevation", None)
            repath_ctx.pop("emu", None)

    if is_3d:
        path = path_3d
    else:
        # ── Dual BFS: clean path vs obstacle path ──
        clean_path = _bfs_pathfind(
            terrain_info, npc_set | set(obstacle_map.keys()),
            bfs_sx, bfs_sy, bfs_tx, bfs_ty, width=bfs_w, height=bfs_h,
        )

        # Only run obstacle BFS if there are obstacles on the map or terrain obstacles
        field_moves = _get_field_move_availability(emu)
        obs_path, obs_crossed = _bfs_pathfind_obstacles(
            terrain_info, npc_set, obstacle_map,
            bfs_sx, bfs_sy, bfs_tx, bfs_ty,
            field_moves, width=bfs_w, height=bfs_h,
        )
        obs_crossed = _dedupe_obstacles(obs_crossed)

        # ── Decide which path to use ──
        has_clean = clean_path is not None
        has_obs = obs_path is not None and len(obs_crossed) > 0
        obs_shorter = has_obs and (not has_clean or len(obs_path) < len(clean_path))

        # Check if all required skills are available for the obstacle path
        skills_available = True
        if has_obs:
            for ob in obs_crossed:
                if not field_moves.get(ob["move"], False):
                    skills_available = False
                    break

        # Determine which path to use
        if path_choice == "obstacle":
            if not has_obs:
                return {"error": "No obstacle path available.", "start": _pos_with_map(px, py, map_id)}
            if not skills_available:
                missing = [ob["move"] for ob in obs_crossed if not field_moves.get(ob["move"], False)]
                return {"error": f"Cannot take obstacle path — missing: {set(missing)}",
                        "start": _pos_with_map(px, py, map_id)}
            path = obs_path
        elif path_choice == "clean":
            if not has_clean:
                return {"error": "No clean (obstacle-free) path available.",
                        "start": _pos_with_map(px, py, map_id)}
            path = clean_path
        elif has_obs and obs_shorter and skills_available and path_choice is None:
            # Obstacle path is shorter and skills available — ask the caller
            start_pos = _pos_with_map(px, py, map_id)
            status = "obstacle_choice" if has_clean else "obstacle_required"
            obstacle_info = [{
                "type": ob["type"], "move": ob["move"], "badge": ob["badge"],
                "x": ob.get("global_x", ob.get("x")),
                "y": ob.get("global_y", ob.get("y")),
            } for ob in obs_crossed]
            msg_parts = [f"Path requires {ob['move']} at ({ob.get('global_x', ob.get('x'))}, {ob.get('global_y', ob.get('y'))})" for ob in obs_crossed]
            if has_clean:
                msg = (
                    f"Shorter path ({len(obs_path)} steps) needs: {', '.join(msg_parts)}. "
                    f"Clean path available ({len(clean_path)} steps). "
                    f"Call again with path_choice='obstacle' or 'clean'."
                )
            else:
                msg = (
                    f"Only path ({len(obs_path)} steps) needs: {', '.join(msg_parts)}. "
                    f"No obstacle-free path exists. "
                    f"Call again with path_choice='obstacle' to proceed."
                )
            return {
                "status": status,
                "clean_path_steps": len(clean_path) if has_clean else None,
                "obstacle_path_steps": len(obs_path),
                "obstacles": obstacle_info,
                "skills_available": skills_available,
                "start": start_pos,
                "target": {"x": target_x, "y": target_y},
                "message": msg,
            }
        elif has_obs and obs_shorter and not skills_available and not has_clean:
            # Only path requires obstacles but skills aren't available
            missing = [ob["move"] for ob in obs_crossed if not field_moves.get(ob["move"], False)]
            return {
                "error": f"No path found. An obstacle path exists but requires: {set(missing)}",
                "start": _pos_with_map(px, py, map_id),
                "target": {"x": target_x, "y": target_y},
            }
        else:
            # Default: use clean path (or None)
            path = clean_path

    # ── Check if target tile is a door/warp ──
    target_behavior = None
    tx_l = bfs_tx if (is_global and chunked) else target_x
    ty_l = bfs_ty if (is_global and chunked) else target_y
    if 0 <= ty_l < len(terrain_info) and 0 <= tx_l < len(terrain_info[0]):
        _, target_behavior = terrain_info[ty_l][tx_l]

    is_door = target_behavior in DOOR_ACTIVATION or target_behavior in DIRECTIONAL_WARP

    start_pos = _pos_with_map(px, py, map_id)

    if path is None:
        # Diagnose why BFS couldn't find a path
        reasons: list[str] = []
        combined_blocked = npc_set | set(obstacle_map.keys())
        target_in_bounds = 0 <= bfs_tx < bfs_w and 0 <= bfs_ty < bfs_h
        start_in_bounds = 0 <= bfs_sx < bfs_w and 0 <= bfs_sy < bfs_h

        if not target_in_bounds:
            reasons.append("target is outside the loaded map area")
        else:
            t_passable, t_behavior = terrain_info[bfs_ty][bfs_tx]
            if not t_passable:
                reasons.append(f"target tile is impassable ({_tile_behavior_hint(t_behavior)})")
            if (bfs_tx, bfs_ty) in obstacle_map:
                ob = obstacle_map[(bfs_tx, bfs_ty)]
                reasons.append(f"{ob['type']} obstacle on target (needs {ob['move']})")
            elif (bfs_tx, bfs_ty) in sign_block_set:
                reasons.append("target is a sign activation zone (blocked to avoid auto-dialogue)")
            elif (bfs_tx, bfs_ty) in npc_set:
                reasons.append("an NPC is standing on the target tile")

        if not start_in_bounds:
            reasons.append("player position is outside the loaded map area")

        if not reasons:
            reasons.append(
                "target tile is reachable terrain but all paths are blocked "
                "by walls, water, NPCs, or obstacles"
            )

        # Build visual failure diagram + nearest reachable suggestion
        result: dict[str, Any] = {
            "error": "No path found: " + "; ".join(reasons) + ".",
            "start": start_pos,
            "target": {"x": target_x, "y": target_y},
        }

        reachable = _bfs_reachable(
            terrain_info, combined_blocked,
            bfs_sx, bfs_sy, bfs_w, bfs_h,
        )
        nearest = _find_nearest_reachable(reachable, bfs_tx, bfs_ty)

        if nearest:
            gx = nearest[0] + repath_ox
            gy = nearest[1] + repath_oy
            dist = abs(nearest[0] - bfs_tx) + abs(nearest[1] - bfs_ty)
            result["nearest_reachable"] = {
                "x": gx, "y": gy, "distance": dist,
            }

        if target_in_bounds:
            diagram = _render_failure_diagram(
                terrain_info, combined_blocked,
                bfs_sx, bfs_sy, bfs_tx, bfs_ty,
                nearest, bfs_w, bfs_h,
            )
            result["diagram"] = diagram
            result["diagram_key"] = "@=player X=target *=nearest_reachable #=wall .=passable N=NPC ≈=water D=door"

        return result

    if len(path) == 0:
        if is_door:
            # Already standing on the door tile — activate it
            door_result = _handle_door_transition(emu, target_behavior, map_id)
            result: dict[str, Any] = {
                "path": "at door",
                "steps": 0,
                "start": start_pos,
            }
            if door_result:
                result.update(door_result)
                result["final"] = door_result["new_position"]
            else:
                # Check if dialogue/battle preempted the warp activation
                encounter = _post_nav_check(emu)
                if encounter:
                    result["final"] = start_pos
                    result["encounter"] = encounter
                else:
                    result["final"] = start_pos
                    result["warp_failed"] = True
                    result["note"] = (
                        "Already on door tile but activation did not trigger a map "
                        "transition. Possible causes: locked door (key item required), "
                        "story flag not yet set, or a script relocated the warp. "
                        "Check the scene manually (screenshot + read_dialogue)."
                    )
            return result

        emu.advance_frames(SETTLE_FRAMES)
        return {
            "path": "at target",
            "steps": 0,
            "start": start_pos,
            "final": start_pos,
        }

    stopped_early, steps_taken, repaths_used, nav_info = _execute_path(
        emu, path, repath_ctx=repath_ctx, hold_frames=hold_frames,
    )

    path_str = _summarize_path(path)

    # Door target but couldn't reach it — check for dialogue/battle that
    # interrupted the path (e.g., NPC farewell at zone exit), then fall back
    # to warp_failed if nothing is found.
    if is_door and stopped_early:
        encounter = _post_nav_check(emu)
        final_map, final_x, final_y = _read_position(emu)
        result = {
            "path": path_str,
            "steps": steps_taken,
            "start": start_pos,
            "final": _pos_with_map(final_x, final_y, final_map),
        }
        if encounter:
            result["encounter"] = encounter
        else:
            result["warp_failed"] = True
            result["note"] = (
                "Target tile is a door/warp but could not be entered. "
                "Possible causes: locked door (key item required), story flag "
                "not yet set, NPC or obstacle blocking the approach path, or a "
                "script relocated the warp. Check the scene manually "
                "(screenshot + read_dialogue)."
            )
        if repaths_used > 0:
            result["repaths"] = repaths_used
        return result

    # For door targets, check if the warp already triggered during path execution
    if is_door and not stopped_early:
        cur_map, cur_x, cur_y = _read_position(emu)
        if cur_map != map_id:
            # Warp already happened (walk-into door like 0x69)
            emu.advance_frames(SETTLE_FRAMES)
            final_map, final_x, final_y = _read_position(emu)
            return {
                "path": path_str,
                "steps": steps_taken,
                "start": start_pos,
                "final": _pos_with_map(final_x, final_y, final_map),
                "door_entered": True,
            }

        # Warp didn't trigger yet — activate the door
        door_result = _handle_door_transition(emu, target_behavior, map_id)
        result = {
            "path": path_str,
            "steps": steps_taken,
            "start": start_pos,
        }
        if door_result:
            result.update(door_result)
            result["final"] = door_result["new_position"]
        else:
            # Warp failed — check if dialogue/battle preempted it
            encounter = _post_nav_check(emu)
            final_map, final_x, final_y = _read_position(emu)
            result["final"] = _pos_with_map(final_x, final_y, final_map)
            if encounter:
                result["encounter"] = encounter
            else:
                result["warp_failed"] = True
                result["note"] = (
                    "Warp transition did not occur — player is still on the same map. "
                    "Possible causes: locked door (key item required), story flag not yet "
                    "set, or an event/script blocking entry. Check the scene manually "
                    "(screenshot + read_dialogue)."
            )
        return result

    # Non-door target: check if we ended up adjacent to a walk-into door/warp
    adj_warp_failed: dict[str, Any] | None = None
    if not is_door and not stopped_early:
        cur_map, cur_x, cur_y = _read_position(emu)
        ti = repath_ctx["terrain_info"]
        gw, gh = repath_ctx["grid_w"], repath_ctx["grid_h"]
        gox, goy = repath_ctx["grid_ox"], repath_ctx["grid_oy"]
        lx, ly = cur_x - gox, cur_y - goy
        for dx, dy, direction in BFS_MOVES:
            adj_lx, adj_ly = lx + dx, ly + dy
            if not (0 <= adj_lx < gw and 0 <= adj_ly < gh):
                continue
            _, adj_behavior = ti[adj_ly][adj_lx]
            is_walkin_door = adj_behavior in DOOR_ACTIVATION and DOOR_ACTIVATION[adj_behavior] is None
            is_dir_warp = adj_behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[adj_behavior] == direction
            if is_walkin_door or is_dir_warp:
                emu.advance_frames(hold_frames, buttons=[direction])
                emu.advance_frames(WAIT_FRAMES)
                door_result = _handle_door_transition(emu, adj_behavior, cur_map)
                if door_result:
                    result = {
                        "path": path_str,
                        "steps": steps_taken,
                        "start": start_pos,
                    }
                    result.update(door_result)
                    result["final"] = door_result["new_position"]
                    return result
                # Adjacent door didn't warp — note it and fall through
                adj_gx, adj_gy = adj_lx + gox, adj_ly + goy
                adj_warp_failed = {
                    "warp_failed": True,
                    "warp_tile": {"x": adj_gx, "y": adj_gy, "behavior": f"0x{adj_behavior:02X}"},
                    "note": (
                        f"Adjacent warp tile at ({adj_gx}, {adj_gy}) did not trigger "
                        f"a map transition. Possible causes: locked door (key item "
                        f"required), story flag not yet set, or an event/script "
                        f"blocking entry. Check the scene manually "
                        f"(screenshot + read_dialogue)."
                    ),
                }
                break  # Only try one adjacent door

    # Standard post-nav check
    encounter = _post_nav_check(emu)
    final_map, final_x, final_y = _read_position(emu)

    result = {
        "path": path_str,
        "steps": steps_taken,
        "start": start_pos,
        "final": _pos_with_map(final_x, final_y, final_map),
    }

    if stopped_early:
        # Check if we stopped adjacent to the target (Manhattan distance 1).
        # This happens when the target tile is occupied by an NPC, signpost,
        # or other entity — the player can't walk onto it but is right next
        # to it. Treat this as a successful arrival rather than an error.
        dx = abs(final_x - target_x)
        dy = abs(final_y - target_y)
        if (dx + dy) <= 1 and nav_info.get("blocked_on_final_step"):
            result["adjacent_to_target"] = True
            result["target"] = {"x": target_x, "y": target_y}
        else:
            result["stopped_early"] = True
            result.update(nav_info)
    if encounter is not None:
        result["encounter"] = encounter
    if repaths_used > 0:
        result["repaths"] = repaths_used
    if adj_warp_failed is not None and encounter is None:
        result.update(adj_warp_failed)

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

# Moving NPC intercept timing
_MOVING_NPC_POLL = 15        # frames between polls (~4/sec)
_MOVING_NPC_TIMEOUT = 900    # ~15 sec, covers 2 full patrol cycles
_INTERACT_COOLDOWN = 90      # min frames between A-press attempts

# Direction deltas → face direction string
_DELTA_TO_FACE = {(1, 0): "right", (-1, 0): "left", (0, 1): "down", (0, -1): "up"}
_FACE_TO_INT = {"up": 0, "down": 1, "left": 2, "right": 3}


def _wait_for_moving_npc(
    emu: "EmulatorClient",
    object_index: int,
    nav_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Wait for a patrolling NPC to become interactable.

    Called after the normal face→A sequence fails because the target NPC
    has a patrol movement and moved away from the expected position.

    Polls for up to ~15 seconds (2 full patrol cycles):
      - Checks for battle (trainer spotted us during patrol).
      - Checks for overworld dialogue (script triggered).
      - When NPC is adjacent, faces them and presses A.

    Returns the updated *nav_result* on success, or None on timeout.
    """
    polls = _MOVING_NPC_TIMEOUT // _MOVING_NPC_POLL
    last_attempt_frame = -_INTERACT_COOLDOWN  # allow first attempt immediately
    elapsed = 0

    for _ in range(polls):
        # ── 1. Battle check (trainer spotted us during patrol) ──
        battlers = read_battle(emu)
        if battlers:
            encounter = _post_nav_check(emu)
            if encounter:
                nav_result["encounter"] = encounter
                nav_result["intercepted_moving_npc"] = True
                return nav_result

        # ── 2. Dialogue check (NPC script triggered) ──
        dlg = read_dialogue(emu, region="overworld")
        if dlg["region"] != "none":
            adv = advance_dialogue(emu)
            nav_result["dialogue"] = adv
            battlers = read_battle(emu)
            if battlers:
                encounter = _post_nav_check(emu)
                if encounter:
                    nav_result["encounter"] = encounter
            nav_result["intercepted_moving_npc"] = True
            return nav_result

        # ── 3. Adjacency check — face + A when NPC is next to us ──
        if elapsed - last_attempt_frame >= _INTERACT_COOLDOWN:
            _, px, py, _ = read_player_state(emu)
            objects_now = read_objects(emu)
            target = next((o for o in objects_now if o["index"] == object_index), None)
            if target:
                dx = target["x"] - px
                dy = target["y"] - py
                if abs(dx) + abs(dy) == 1:
                    face_dir = _DELTA_TO_FACE.get((dx, dy))
                    if face_dir:
                        last_attempt_frame = elapsed

                        # Face the NPC
                        emu.advance_frames(HOLD_FRAMES, buttons=[face_dir])
                        emu.advance_frames(WAIT_FRAMES)

                        # Check if trainer spotted us during face turn
                        _, _, _, new_facing = read_player_state(emu)
                        if new_facing != _FACE_TO_INT[face_dir]:
                            encounter = _post_nav_check(emu)
                            if encounter:
                                nav_result["encounter"] = encounter
                                nav_result["intercepted_moving_npc"] = True
                                return nav_result

                        # Press A and check for response
                        emu.press_buttons(["a"], frames=8)
                        emu.advance_frames(INTERACT_A_WAIT)

                        dlg = read_dialogue(emu, region="overworld")
                        if dlg["region"] != "none":
                            adv = advance_dialogue(emu)
                            nav_result["dialogue"] = adv
                            nav_result["pressed_a"] = True
                            battlers = read_battle(emu)
                            if battlers:
                                encounter = _post_nav_check(emu)
                                if encounter:
                                    nav_result["encounter"] = encounter
                            nav_result["intercepted_moving_npc"] = True
                            return nav_result

                        # Check for approach animation (ctx0=RUN after A press)
                        mgr = _find_script_manager(emu)
                        if mgr:
                            ss = _read_script_state(emu, mgr)
                            if not ss["is_msg_box_open"] and not ss["sub_ctx_active"] and ss["ctx0_ptr"]:
                                ctx0 = _read_context_state(emu, ss["ctx0_ptr"])
                                if ctx0["state"] == CTX_RUNNING:
                                    encounter = _post_nav_check(emu)
                                    if encounter:
                                        nav_result["encounter"] = encounter
                                        nav_result["intercepted_moving_npc"] = True
                                        return nav_result

        emu.advance_frames(_MOVING_NPC_POLL)
        elapsed += _MOVING_NPC_POLL

    return None


def _target_info(has_object: bool, object_index: int, name: str, x: int, y: int) -> dict:
    """Build target dict for interact_with results."""
    info: dict[str, Any] = {"name": name, "x": x, "y": y}
    if has_object:
        info["index"] = object_index
    return info


def interact_with(emu: EmulatorClient, object_index: int = -1, x: int = -1, y: int = -1, flee_encounters: bool = False) -> dict[str, Any]:
    """Navigate to an object/NPC or static tile and interact with it.

    Object mode (object_index): looks up by index, pathfinds to adjacent tile.
    Coordinate mode (x, y): targets a specific tile directly (for PCs, bookshelves, etc.).
    """
    hold_frames = _get_move_hold(emu)
    has_object = object_index >= 0
    has_coords = x >= 0 and y >= 0
    if not has_object and not has_coords:
        return {"error": "Provide either object_index or both x and y."}
    if has_object and has_coords:
        return {"error": "Provide object_index OR (x, y), not both."}

    # ── Read current state ──
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not read map state."}

    objects = state["objects"]
    map_id = state["map_id"]
    px, py = state["px"], state["py"]
    chunked = state["chunked"]

    if has_object:
        target = next((o for o in objects if o["index"] == object_index), None)
        if target is None:
            return {"error": f"Object index {object_index} not found in current map objects."}
        target_x, target_y = target["x"], target["y"]
        target_name = target.get("name", f"Object {object_index}")
        exclude_index = object_index
    else:
        target_x, target_y = x, y
        target_name = f"Tile ({x}, {y})"
        exclude_index = -1

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
            if obj["index"] == 0 or obj["index"] == exclude_index:
                continue
            nx = obj["x"] - grid_ox
            ny = obj["y"] - grid_oy
            if 0 <= nx < grid_w and 0 <= ny < grid_h:
                npc_set.add((nx, ny))

        # Block sign activation tiles
        for sx, sy in read_sign_tiles_from_rom(emu, map_id):
            lx, ly = sx - grid_ox, sy - grid_oy
            if 0 <= lx < grid_w and 0 <= ly < grid_h:
                npc_set.add((lx, ly))

        rel_px = px - grid_ox
        rel_py = py - grid_oy
        rel_tx = target_x - grid_ox
        rel_ty = target_y - grid_oy
        width, height = grid_w, grid_h
    else:
        origin_x = state.get("origin_x", 0)
        origin_y = state.get("origin_y", 0)
        terrain_info, npc_set, _ = _build_terrain_info(state["terrain"], state["objects"])

        # Block sign activation tiles
        for sx, sy in read_sign_tiles_from_rom(emu, map_id):
            lx, ly = sx - origin_x, sy - origin_y
            if 0 <= lx < 32 and 0 <= ly < 32:
                npc_set.add((lx, ly))

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
            "target": _target_info(has_object, object_index, target_name, target_x, target_y),
        }

    # Pick shortest path
    candidates.sort(key=lambda c: c[0])
    _, best_path, dest_x, dest_y, face_dir = candidates[0]

    # ── Execute path ──
    nav_result: dict[str, Any] = {
        "target": _target_info(has_object, object_index, target_name, target_x, target_y),
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
        stopped_early, steps_taken, repaths_used, nav_info = _execute_path(
            emu, best_path, repath_ctx=repath_ctx, hold_frames=hold_frames,
        )
        nav_result["path"] = _summarize_path(best_path)
        nav_result["steps"] = steps_taken
        if stopped_early:
            encounter = _post_nav_check(emu)
            if encounter and flee_encounters:
                encounter, flee_entry = _try_flee_encounter(emu, encounter)
                if flee_entry:
                    nav_result.setdefault("flee_log", []).append(flee_entry)
                    if flee_entry.get("fled"):
                        nav_result["encounters_fled"] = nav_result.get("encounters_fled", 0) + 1
                    elif flee_entry.get("reason"):
                        reason = flee_entry["reason"]
                        species = flee_entry.get("species", "unknown")
                        if "fainted" in reason:
                            nav_result["flee_failed"] = (
                                f"Pokemon fainted while fleeing wild {species}. "
                                f"Heal party before continuing."
                            )
                        else:
                            nav_result["flee_failed"] = f"Flee failed against wild {species}: {reason}"
                        nav_result["encounter"] = encounter
                        nav_result["interrupted"] = True
                        return nav_result
            if encounter:
                nav_result["encounter"] = encounter
                nav_result["interrupted"] = True
                return nav_result
            if not nav_result.get("encounters_fled"):
                # Stopped early but no encounter (door entry, wall, etc.)
                nav_result["stopped_early"] = True
                nav_result.update(nav_info)
                return nav_result
            # Wild encounter fled — re-navigate from current position
            emu.advance_frames(POST_BATTLE_SETTLE)
            dest_gx, dest_gy = dest_x + grid_ox, dest_y + grid_oy
            retry = navigate_to(emu, dest_gx, dest_gy, flee_encounters=True)
            if retry.get("flee_log"):
                nav_result["flee_log"].extend(retry["flee_log"])
                nav_result["encounters_fled"] += retry.get("encounters_fled", 0)
            if retry.get("encounter") or retry.get("error") or retry.get("stopped_early"):
                if retry.get("encounter"):
                    nav_result["encounter"] = retry["encounter"]
                    nav_result["interrupted"] = True
                return nav_result
            # Re-path succeeded — fall through to face + interact
    else:
        nav_result["path"] = "adjacent"
        nav_result["steps"] = 0

    # ── Face the target ──
    _, _, _, cur_facing = read_player_state(emu)
    desired_facing = {"up": 0, "down": 1, "left": 2, "right": 3}[face_dir]
    facing_seized = False
    if cur_facing != desired_facing:
        emu.advance_frames(HOLD_FRAMES, buttons=[face_dir])
        emu.advance_frames(WAIT_FRAMES)
        # Validate facing actually changed — if not, a script may have
        # seized control (e.g. trainer-spotted animation)
        _, _, _, new_facing = read_player_state(emu)
        if new_facing == desired_facing:
            nav_result["turned_to_face"] = face_dir
        else:
            facing_seized = True
            nav_result["facing_seized"] = True

    # ── If facing was seized, a trainer-spotted script likely has control.
    #    Poll for the resulting dialogue or battle instead of pressing A. ──
    if facing_seized:
        encounter = _post_nav_check(emu)
        if encounter:
            nav_result["encounter"] = encounter
            nav_result["interrupted"] = True
            return nav_result
        # Still nothing — fall through to normal interaction below

    # ── Check for auto-interaction (signs auto-trigger when faced) ──
    emu.advance_frames(INTERACT_DIALOGUE_WAIT)
    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] != "none":
        adv_result = advance_dialogue(emu)
        if adv_result.get("status") != "no_dialogue":
            nav_result["dialogue"] = adv_result
            # Check if dialogue led into a battle (trainer taunts, etc.)
            battlers = read_battle(emu)
            if battlers:
                encounter = _post_nav_check(emu)
                if encounter:
                    nav_result["encounter"] = encounter
            return nav_result
        # msgBox=0: might be stale buffer data, or a sign overlay (board
        # message) that doesn't set msgBox.  Signs use a BG-layer overlay
        # for text instead of the standard dialogue box.
        is_sign = (has_object and target is not None
                   and target.get("graphics_id", 0) in SIGN_GFX_IDS)
        if is_sign:
            # Accept the text from read_dialogue and dismiss the overlay
            emu.press_buttons(["b"], frames=8)
            emu.advance_frames(SETTLE_FRAMES)
            nav_result["dialogue"] = {
                "status": "completed",
                "text": dialogue.get("text", ""),
                "lines": dialogue.get("lines", []),
                "sign_overlay": True,
            }
            return nav_result
        # Not a sign — stale data. Fall through to A press.

    # ── Press A to interact ──
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(INTERACT_A_WAIT)

    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] != "none":
        adv_result = advance_dialogue(emu)
        if adv_result.get("status") != "no_dialogue":
            nav_result["dialogue"] = adv_result
            nav_result["pressed_a"] = True
            # Check if dialogue led into a battle
            battlers = read_battle(emu)
            if battlers:
                encounter = _post_nav_check(emu)
                if encounter:
                    nav_result["encounter"] = encounter
            return nav_result
        # msgBox=0: might be pre-positioned cutscene data, or sign overlay.
        is_sign = (has_object and target is not None
                   and target.get("graphics_id", 0) in SIGN_GFX_IDS)
        if is_sign:
            emu.press_buttons(["b"], frames=8)
            emu.advance_frames(SETTLE_FRAMES)
            nav_result["dialogue"] = {
                "status": "completed",
                "text": dialogue.get("text", ""),
                "lines": dialogue.get("lines", []),
                "sign_overlay": True,
            }
            nav_result["pressed_a"] = True
            return nav_result
        # Not a sign — fall through to script detection.

    # ── Fallback: check for script activation (trainer spotted during walk
    #    or "!" approach animation still in progress after A press) ──
    mgr = _find_script_manager(emu)
    if mgr is not None:
        ss = _read_script_state(emu, mgr)
        script_active = ss["is_msg_box_open"] or ss["sub_ctx_active"]
        # During trainer approach animations ("!" bubble + walk toward player),
        # msgBox and subCtx are both 0 for ~170 frames.  The only signal is
        # ctx0 being in RUN or WAIT state.
        if not script_active and ss["ctx0_ptr"]:
            ctx0 = _read_context_state(emu, ss["ctx0_ptr"])
            if ctx0["state"] in (CTX_RUNNING, CTX_WAITING):
                script_active = True
        if script_active:
            encounter = _post_nav_check(emu)
            if encounter:
                nav_result["encounter"] = encounter
                nav_result["interrupted"] = True
                return nav_result

    # ── Moving NPC retry: if target has a patrol movement, wait for it ──
    if has_object and target is not None:
        movement = target.get("movement_type", "none")
        if movement not in ("none", "stationary"):
            intercept = _wait_for_moving_npc(emu, object_index, nav_result)
            if intercept is not None:
                return intercept
            # Timeout — include diagnostics
            nav_result["dialogue"] = None
            nav_result["note"] = (
                f"{target_name} has patrol movement ({movement}) and could not "
                f"be intercepted within {_MOVING_NPC_TIMEOUT // 60:.0f} seconds. "
                f"Try navigating to their patrol area and waiting manually."
            )
            return nav_result

    # ── No dialogue found ──
    nav_result["dialogue"] = None
    nav_result["note"] = f"{target_name} did not produce any dialogue when interacted with."
    return nav_result
