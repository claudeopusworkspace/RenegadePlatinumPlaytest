"""BFS pathfinding algorithms and terrain grid construction.

Contains all BFS variants (2D, 3D, obstacle-aware), terrain grid builders
(single-chunk and multi-chunk), elevation helpers, and path validation.
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Any

from renegade_mcp.nav_constants import (
    _3D_MAX_DEPTH,
    _3D_TIMEOUT,
    _DIAG_CHAR,
    BADGE_BITS,
    BFS_MOVES,
    BIKE_RAMP_BEHAVIORS,
    BIKE_RAMP_DIRECTIONS,
    BIKE_RAMP_JUMP_TILES,
    BIKE_RAMP_NEAR_JUMP_TILES,
    BIKE_RAMP_RUNWAY_TILES,
    BIKE_SLOPE_BEHAVIORS,
    BIKE_SLOPE_RUNWAY_TILES,
    CLEARABLE_OBSTACLES,
    DIRECTIONAL_BLOCKS,
    DIRECTIONAL_WARP,
    DOOR_ACTIVATION,
    HM_OBSTACLES,
    LEDGE_DIRECTIONS,
    PUZZLE_OBSTACLES,
    STEPPABLE_HEIGHT,
    TERRAIN_OBSTACLE_INFO,
    TERRAIN_OBSTACLES,
    WARP_PASSABLE,
    is_follower_npc,
)
from renegade_mcp.map_state import (
    CHUNK_SIZE,
    get_matrix_for_map,
    load_terrain_from_rom,
    parse_bdhc,
)
from renegade_mcp.party import read_party
from renegade_mcp.trainer import read_trainer_status

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


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


def _bike_ramp_edges(
    terrain_info: list, x: int, y: int, direction: str,
    dx: int, dy: int, width: int, height: int,
    momentum: int | None = None,
) -> list[tuple[int, int, int]]:
    """Return all ramp-jump edges admitted from stepping (x, y)→ramp in
    ``direction``. Each edge is ``(landing_x, landing_y, post_momentum)``.

    Two jump kinds, selected by running-start momentum at the approach:

    - **FAR jump** — momentum at approach is at full runway
      (``momentum + 1 >= BIKE_RAMP_RUNWAY_TILES``). Lands at
      approach + BIKE_RAMP_JUMP_TILES (= ramp + 4).  Post-jump momentum
      is RUNWAY so chained ramps can carry through.
    - **NEAR jump** — momentum at approach is exactly 0 (standing start,
      or just turned onto the approach).  Lands at approach +
      BIKE_RAMP_NEAR_JUMP_TILES (= ramp + 1).  Post-jump momentum is 1
      (one tile's worth — the jump itself, no runway built up).

    Mid-range momentum (1 or 2 of the 3 runway prefixes) empirically did
    not produce a clean intermediate landing in our spike (obstacles may
    clamp the engine's natural displacement), so no edge is emitted.

    ``momentum`` modes mirror the legacy single-landing helper:
    - ``int`` — caller tracks per-state directional momentum precisely.
    - ``None`` — caller doesn't track. Geometric fallback: the FAR edge
      is admitted only if the RUNWAY-1 tiles behind (x, y) are clear
      and not direction-gated; the NEAR edge is never emitted (the
      caller has no way to assert standing-start).

    Returns [] when there is no ramp, the ramp faces a different axis,
    the landing is out of bounds, or the landing tile is impassable.
    """
    nx, ny = x + dx, y + dy
    if not (0 <= nx < width and 0 <= ny < height):
        return []
    _ramp_passable, behavior = terrain_info[ny][nx]
    if behavior not in BIKE_RAMP_BEHAVIORS:
        return []
    if BIKE_RAMP_DIRECTIONS[behavior] != direction:
        return []

    edges: list[tuple[int, int, int]] = []

    # Helper: admit an edge if the landing is in-bounds and passable.
    def _try_admit(jump_tiles: int, post_m: int) -> None:
        lx, ly = x + dx * jump_tiles, y + dy * jump_tiles
        if not (0 <= lx < width and 0 <= ly < height):
            return
        land_passable, _land_beh = terrain_info[ly][lx]
        if not land_passable:
            return
        edges.append((lx, ly, post_m))

    if momentum is None:
        # Geometric fallback: can only reason about far-jump feasibility.
        for i in range(1, BIKE_RAMP_RUNWAY_TILES):
            bx, by = x - i * dx, y - i * dy
            if not (0 <= bx < width and 0 <= by < height):
                return []
            back_passable, back_behavior = terrain_info[by][bx]
            if not back_passable:
                return []
            if back_behavior in LEDGE_DIRECTIONS:
                return []
            if back_behavior in DIRECTIONAL_WARP:
                return []
        _try_admit(BIKE_RAMP_JUMP_TILES, BIKE_RAMP_RUNWAY_TILES)
        return edges

    # Integer momentum — caller knows exactly.
    if momentum + 1 >= BIKE_RAMP_RUNWAY_TILES:
        _try_admit(BIKE_RAMP_JUMP_TILES, BIKE_RAMP_RUNWAY_TILES)
    if momentum == 0:
        _try_admit(BIKE_RAMP_NEAR_JUMP_TILES, 1)
    return edges


def _bike_ramp_landing(
    terrain_info: list, x: int, y: int, direction: str,
    dx: int, dy: int, width: int, height: int,
    momentum: int | None = None,
) -> tuple[int, int] | None:
    """Legacy single-landing wrapper — returns just the FAR-jump landing
    tile when a far-jump edge is admitted, else None.

    Kept for callers that only care about the fast-gear far-jump (unit
    tests, non-momentum-aware consumers).  BFS variants should call
    :func:`_bike_ramp_edges` instead to also admit near-jumps.
    """
    for lx, ly, post_m in _bike_ramp_edges(
        terrain_info, x, y, direction, dx, dy, width, height, momentum=momentum,
    ):
        if post_m == BIKE_RAMP_RUNWAY_TILES:
            return (lx, ly)
    return None


def _bike_slope_entry_blocked(
    terrain_info: list, x: int, y: int, direction: str,
    dx: int, dy: int, momentum: int,
) -> bool:
    """Return True iff the step from (x, y) in `direction` enters a bike slope
    tile (0xD9/0xDA) going *up* without enough approach momentum.

    Gen 4 Platinum slopes are N-S only: climbing means stepping `up` onto a
    slope tile. The engine's running-start detection fires only on *initial*
    entry to the slope — once the player is on a slope tile, a continuous
    hold carries them through the rest of the slope without re-checking
    momentum. BFS matches: gate only the step from a NON-slope approach tile
    onto a slope tile. Continued up-steps from one slope tile to another
    (tile-by-tile model of the engine's single continuous climb) are not
    gated.

    Non-slope neighbors, non-ascent directions, and slope-to-slope steps are
    not gated and this returns False (caller proceeds with ordinary
    passability logic). The approach tile (x, y) counts toward the runway,
    so `momentum + 1 >= RUNWAY` admits — same convention as
    `_bike_ramp_landing`.

    `momentum` is the approach momentum (prior consecutive same-direction
    steps including arrival at (x, y)) — caller passes 0 when arriving at
    (x, y) via a turn so the slope correctly rejects.
    """
    if direction != "up":
        return False
    ny = y + dy
    nx = x + dx
    if not (0 <= ny < len(terrain_info)) or not (0 <= nx < len(terrain_info[0])):
        return False
    _, behavior = terrain_info[ny][nx]
    if behavior not in BIKE_SLOPE_BEHAVIORS:
        return False
    # Slope-to-slope continuation: player already mid-climb, no gate.
    if 0 <= y < len(terrain_info) and 0 <= x < len(terrain_info[0]):
        _, src_behavior = terrain_info[y][x]
        if src_behavior in BIKE_SLOPE_BEHAVIORS:
            return False
    return momentum + 1 < BIKE_SLOPE_RUNWAY_TILES


def _bfs_reachable(
    terrain_info: list, npc_set: set,
    start_x: int, start_y: int,
    width: int, height: int,
) -> set[tuple[int, int]]:
    """Flood-fill BFS from start. Returns set of all reachable (x, y) tiles.

    Momentum-aware: state is (x, y, last_dir, momentum) so that bike ramps
    requiring a multi-tile runway are admitted exactly when the player can
    build up same-direction travel to reach them. Landing from a ramp
    jump sets momentum=RUNWAY in the ramp direction, enabling chained
    ramp sequences across short intermediate gaps.
    """
    if not (0 <= start_x < width and 0 <= start_y < height):
        return set()
    reachable: set[tuple[int, int]] = {(start_x, start_y)}
    start_state = (start_x, start_y, None, 0)
    visited: set[tuple[int, int, str | None, int]] = {start_state}
    queue: deque[tuple[int, int, str | None, int]] = deque([start_state])
    runway = BIKE_RAMP_RUNWAY_TILES
    while queue:
        x, y, last_d, m = queue.popleft()
        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            passable, behavior = terrain_info[ny][nx]
            if not passable:
                approach_m = m if last_d == direction else 0
                for lx, ly, post_m in _bike_ramp_edges(
                    terrain_info, x, y, direction, dx, dy, width, height,
                    momentum=approach_m,
                ):
                    if (lx, ly) in npc_set:
                        continue
                    new_state = (lx, ly, direction, post_m)
                    if new_state in visited:
                        continue
                    visited.add(new_state)
                    reachable.add((lx, ly))
                    queue.append(new_state)
                continue
            if (nx, ny) in npc_set:
                continue
            if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                continue
            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue
            approach_m = m if last_d == direction else 0
            if _bike_slope_entry_blocked(
                terrain_info, x, y, direction, dx, dy, approach_m,
            ):
                continue
            new_m = min(m + 1, runway) if last_d == direction else 1
            new_state = (nx, ny, direction, new_m)
            if new_state in visited:
                continue
            visited.add(new_state)
            reachable.add((nx, ny))
            queue.append(new_state)
    return reachable


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
        # Follower NPCs (Mira, Cheryl, rival escorts) swap places with the
        # player on step-in — their tile is effectively passable, so leave
        # them out of npc_set to avoid walling off narrow escort corridors.
        if is_follower_npc(obj):
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
    """BFS shortest path with ledge and bike-ramp awareness.

    Momentum-aware: state is (x, y, last_dir, momentum) so chained bike
    ramps (landing carries full momentum into the next ramp) are admitted.
    Returns direction list or None.
    """
    if not (0 <= start_x < width and 0 <= start_y < height):
        return None
    if not (0 <= goal_x < width and 0 <= goal_y < height):
        return None
    if (start_x, start_y) == (goal_x, goal_y):
        return []

    start_state = (start_x, start_y, None, 0)
    visited: set[tuple[int, int, str | None, int]] = {start_state}
    queue: deque[tuple[int, int, str | None, int, list[str]]] = deque(
        [(start_x, start_y, None, 0, [])]
    )
    goal = (goal_x, goal_y)
    runway = BIKE_RAMP_RUNWAY_TILES

    while queue:
        x, y, last_d, m, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                approach_m = m if last_d == direction else 0
                goal_return = None
                for lx, ly, post_m in _bike_ramp_edges(
                    terrain_info, x, y, direction, dx, dy, width, height,
                    momentum=approach_m,
                ):
                    if (lx, ly) in npc_set and (lx, ly) != goal:
                        continue
                    new_state = (lx, ly, direction, post_m)
                    if new_state in visited:
                        continue
                    new_path = path + [direction]
                    if (lx, ly) == goal:
                        goal_return = new_path
                        break
                    visited.add(new_state)
                    queue.append((lx, ly, direction, post_m, new_path))
                if goal_return is not None:
                    return goal_return
                continue

            if (nx, ny) in npc_set and (nx, ny) != goal:
                continue

            if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                continue

            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue

            approach_m = m if last_d == direction else 0
            if _bike_slope_entry_blocked(
                terrain_info, x, y, direction, dx, dy, approach_m,
            ):
                continue

            new_m = min(m + 1, runway) if last_d == direction else 1
            new_state = (nx, ny, direction, new_m)
            if new_state in visited:
                continue
            new_path = path + [direction]
            if (nx, ny) == goal:
                return new_path
            visited.add(new_state)
            queue.append((nx, ny, direction, new_m, new_path))

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
    height_by_level = {lv["level"]: lv["height"] for lv in elevation["levels"]}
    current_height = height_by_level.get(current_level)

    def _steppable(other_level: int) -> bool:
        if current_height is None:
            return False
        oh = height_by_level.get(other_level)
        if oh is None:
            return False
        return abs(oh - current_height) <= STEPPABLE_HEIGHT

    def _tile_on_level(tx: int, ty: int, level: int) -> bool:
        key = (tx, ty)
        ri = ramp_tiles.get(key)
        lvls = level_map.get(key)
        # A tile can have BOTH a ramp plate AND a flat plate at overlapping
        # (x, y) — a Cycling-Road ramp visibly sits over the ground tiles
        # beneath it. Check each source independently and accept if either
        # permits the level. Mirrors _flood_fill_level so single-level BFS
        # agrees with view_map's hierarchical reachability.
        if ri is not None:
            if level in (ri["from_level"], ri["to_level"]):
                return True
            if _steppable(ri["from_level"]) or _steppable(ri["to_level"]):
                return True
        if lvls is not None:
            if level in lvls:
                return True
            if any(_steppable(lv) for lv in lvls):
                return True
        # No elevation data on either source → accessible on any level.
        return ri is None and lvls is None

    goal = (goal_x, goal_y)
    start_state = (start_x, start_y, None, 0)
    visited: set[tuple[int, int, str | None, int]] = {start_state}
    tile_seen: set[tuple[int, int]] = {(start_x, start_y)}
    queue: deque[tuple[int, int, str | None, int, list[str]]] = deque(
        [(start_x, start_y, None, 0, [])]
    )
    reachable_ramps: dict[int, tuple[list[str], tuple[int, int], int]] = {}
    runway = BIKE_RAMP_RUNWAY_TILES

    while queue:
        x, y, last_d, m, path = queue.popleft()

        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                approach_m = m if last_d == direction else 0
                goal_return = None
                for lx, ly, post_m in _bike_ramp_edges(
                    terrain_info, x, y, direction, dx, dy, width, height,
                    momentum=approach_m,
                ):
                    if (lx, ly) in npc_set and (lx, ly) != goal:
                        continue
                    if not _tile_on_level(lx, ly, current_level):
                        continue
                    new_state = (lx, ly, direction, post_m)
                    if new_state in visited:
                        continue
                    new_path = path + [direction]
                    if (lx, ly) == (goal_x, goal_y):
                        goal_return = new_path
                        break
                    visited.add(new_state)
                    tile_seen.add((lx, ly))
                    queue.append((lx, ly, direction, post_m, new_path))
                if goal_return is not None:
                    return goal_return, reachable_ramps
                continue

            if (nx, ny) in npc_set and (nx, ny) != goal:
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

            approach_m = m if last_d == direction else 0
            if _bike_slope_entry_blocked(
                terrain_info, x, y, direction, dx, dy, approach_m,
            ):
                continue

            new_m = min(m + 1, runway) if last_d == direction else 1
            new_state = (nx, ny, direction, new_m)
            if new_state in visited:
                continue
            new_path = path + [direction]
            visited.add(new_state)

            # Record ramp transitions to other levels (first discovery only).
            ramp_key = (nx, ny)
            if ramp_key not in tile_seen and ramp_key in ramp_tiles:
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
            tile_seen.add(ramp_key)

            if (nx, ny) == (goal_x, goal_y):
                return new_path, reachable_ramps

            queue.append((nx, ny, direction, new_m, new_path))

    return None, reachable_ramps


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


def _flood_fill_level(
    terrain_info: list, npc_set: set, elevation: dict,
    start_x: int, start_y: int, current_level: int,
    width: int = 32, height: int = 32,
    max_steps: int | None = None,
) -> tuple[dict[tuple[int, int], int],
           dict[object, tuple[int, tuple[int, int], int]]]:
    """Flood-fill restricted to one elevation level.

    Returns (reach, transitions) where:
    - reach: {(x, y): steps} for every tile reachable on ``current_level``.
    - transitions: {key: (steps, (x, y), other_level)} for each way to
      cross to a different level from one of the reached tiles. Keys are
      either ``ramp_index`` (int, for a ramp) or ``("ml", x, y, other_level)``
      for a multi-level flat tile where the player can switch levels
      (e.g. a bridge-over-ground overlap tile).

    Uses the same level-compatibility rules as ``_bfs_pathfind_level``.

    When ``max_steps`` is given, the flood stops expanding past that
    distance (measured from the start tile on this level).

    ``npc_set`` may be 2D ``{(x, y)}`` — in which case an NPC blocks every
    level at its tile — or 3D ``{(x, y, level)}`` for elevation-aware
    blocking (a bridge-level trainer doesn't block ground traversal under
    the bridge). The set type is detected from the first element.
    """
    npc_is_3d = bool(npc_set) and len(next(iter(npc_set))) == 3
    if not (0 <= start_x < width and 0 <= start_y < height):
        return {}, {}

    level_map = elevation["level_map"]
    ramp_tiles = elevation["ramp_tiles"]
    height_by_level = {lv["level"]: lv["height"] for lv in elevation["levels"]}
    current_height = height_by_level.get(current_level)

    def _steppable(other_level: int) -> bool:
        if current_height is None:
            return False
        oh = height_by_level.get(other_level)
        if oh is None:
            return False
        return abs(oh - current_height) <= STEPPABLE_HEIGHT

    def _tile_on_level(tx: int, ty: int, level: int) -> bool:
        key = (tx, ty)
        ri = ramp_tiles.get(key)
        lvls = level_map.get(key)
        # A tile can have BOTH a ramp plate AND a flat plate at overlapping
        # (x, y) — a Cycling-Road ramp visibly sits over the ground tiles
        # beneath it. Check each source independently and accept if either
        # permits the level.
        if ri is not None:
            if level in (ri["from_level"], ri["to_level"]):
                return True
            if _steppable(ri["from_level"]) or _steppable(ri["to_level"]):
                return True
        if lvls is not None:
            if level in lvls:
                return True
            if any(_steppable(lv) for lv in lvls):
                return True
        # No BDHC data on this tile — permissive.
        return ri is None and lvls is None

    reach: dict[tuple[int, int], int] = {(start_x, start_y): 0}
    start_state = (start_x, start_y, None, 0)
    visited: set[tuple[int, int, str | None, int]] = {start_state}
    queue: deque[tuple[int, int, str | None, int, int]] = deque(
        [(start_x, start_y, None, 0, 0)]
    )
    transitions: dict[object, tuple[int, tuple[int, int], int]] = {}
    runway = BIKE_RAMP_RUNWAY_TILES

    def _record_transitions(tx: int, ty: int, steps: int) -> None:
        # Ramp tile: record once per ramp index.
        ri = ramp_tiles.get((tx, ty))
        if ri is not None:
            ramp_idx = ri["ramp_index"]
            if ramp_idx not in transitions:
                if ri["from_level"] == current_level:
                    other = ri["to_level"]
                elif ri["to_level"] == current_level:
                    other = ri["from_level"]
                else:
                    other = None
                if other is not None and other != current_level:
                    transitions[ramp_idx] = (steps, (tx, ty), other)
            return
        # Multi-level flat tile: each "other" level is a separate transition.
        # Only allow ML transitions between levels within STEPPABLE_HEIGHT —
        # a tile whose BDHC reports both ground (h=16) and bridge (h=140)
        # plates is not a teleporter; the player needs a ramp to switch.
        lvls = level_map.get((tx, ty))
        if lvls and len(lvls) > 1 and current_level in lvls:
            for other_lv in lvls:
                if other_lv == current_level:
                    continue
                if not _steppable(other_lv):
                    continue
                key = ("ml", tx, ty, other_lv)
                if key not in transitions:
                    transitions[key] = (steps, (tx, ty), other_lv)

    # Start tile may itself be a transition point.
    _record_transitions(start_x, start_y, 0)

    while queue:
        x, y, last_d, m, d = queue.popleft()
        if max_steps is not None and d >= max_steps:
            continue
        for dx, dy, direction in BFS_MOVES:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue

            passable, behavior = terrain_info[ny][nx]
            if not passable:
                approach_m = m if last_d == direction else 0
                for lx, ly, post_m in _bike_ramp_edges(
                    terrain_info, x, y, direction, dx, dy, width, height,
                    momentum=approach_m,
                ):
                    if npc_is_3d:
                        if (lx, ly, current_level) in npc_set:
                            continue
                    elif (lx, ly) in npc_set:
                        continue
                    if not _tile_on_level(lx, ly, current_level):
                        continue
                    new_state = (lx, ly, direction, post_m)
                    if new_state in visited:
                        continue
                    visited.add(new_state)
                    nd = d + 1
                    if (lx, ly) not in reach:
                        reach[(lx, ly)] = nd
                        _record_transitions(lx, ly, nd)
                    queue.append((lx, ly, direction, post_m, nd))
                continue

            if npc_is_3d:
                if (nx, ny, current_level) in npc_set:
                    continue
            elif (nx, ny) in npc_set:
                continue

            if behavior in DIRECTIONAL_WARP and DIRECTIONAL_WARP[behavior] != direction:
                continue
            if behavior in LEDGE_DIRECTIONS and LEDGE_DIRECTIONS[behavior] != direction:
                continue
            _, src_behavior = terrain_info[y][x]
            if src_behavior in DIRECTIONAL_BLOCKS and DIRECTIONAL_BLOCKS[src_behavior] == direction:
                continue

            if not _tile_on_level(nx, ny, current_level):
                continue

            approach_m = m if last_d == direction else 0
            if _bike_slope_entry_blocked(
                terrain_info, x, y, direction, dx, dy, approach_m,
            ):
                continue

            new_m = min(m + 1, runway) if last_d == direction else 1
            new_state = (nx, ny, direction, new_m)
            if new_state in visited:
                continue
            visited.add(new_state)
            nd = d + 1
            if (nx, ny) not in reach:
                reach[(nx, ny)] = nd
                _record_transitions(nx, ny, nd)

            queue.append((nx, ny, direction, new_m, nd))

    return reach, transitions


def _validate_path_elevation(
    path: list[str], elevation: dict,
    start_x: int, start_y: int, start_level: int,
) -> bool:
    """Walk a 2D path simulating level transitions; reject if any step
    jumps between incompatible elevation layers (e.g. under-bridge ground
    up onto the bridge).

    Permissive where the existing 3D BFS is permissive: no-data tiles are
    accepted on any level, multi-level tiles act as implicit level
    transitions, and small height differences (≤ STEPPABLE_HEIGHT) are
    allowed.

    Used to filter 2D-BFS fallback paths on 3D maps so BUG-030-style bridge
    routing doesn't sneak through.
    """
    level_map = elevation["level_map"]
    ramp_tiles = elevation["ramp_tiles"]
    height_by_level = {lv["level"]: lv["height"] for lv in elevation["levels"]}

    def _steppable(a: int, b: int) -> bool:
        ha = height_by_level.get(a)
        hb = height_by_level.get(b)
        if ha is None or hb is None:
            return False
        return abs(ha - hb) <= STEPPABLE_HEIGHT

    # current_levels is a set: on ramp/multi-level tiles the player's
    # effective level is ambiguous until a forcing single-level tile.
    current_levels: set[int] = {start_level}
    cx, cy = start_x, start_y
    deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    for step in path:
        dx, dy = deltas[step]
        cx += dx
        cy += dy
        key = (cx, cy)
        ri = ramp_tiles.get(key)
        lvls = level_map.get(key)

        # Each step, enumerate every level the player could plausibly be on
        # after landing here from ``current_levels``. Ramp and flat plates
        # at the same (x, y) are considered independently so a ground-level
        # traversal under a Cycling Road ramp stays on the ground plate.
        next_levels: set[int] = set()
        if ri is not None:
            ends = {ri["from_level"], ri["to_level"]}
            for lv in ends:
                if lv in current_levels or any(_steppable(cl, lv) for cl in current_levels):
                    next_levels.update(ends)
                    break
        if lvls is not None:
            next_levels |= set(lvls) & current_levels
            for lv in lvls:
                if any(_steppable(cl, lv) for cl in current_levels):
                    next_levels.add(lv)

        if next_levels:
            current_levels = next_levels
            continue
        if ri is None and lvls is None:
            continue  # No plate data — permissive.
        return False

    return True


def _bfs_reachable_3d(
    terrain_info: list, npc_set: set, elevation: dict,
    start_x: int, start_y: int, start_level: int,
    width: int = 32, height: int = 32,
    timeout: float = 1.5,
    max_steps: int | None = None,
) -> dict[tuple[int, int, int], int]:
    """Hierarchical flood-fill across elevation levels via ramp transitions.

    Returns {(x, y, level): min_steps} for every (tile, level) pair
    reachable from (start_x, start_y) on start_level or any level reachable
    through ramps and multi-level flat-tile transitions. The elevation
    dimension is preserved so callers can distinguish tiles reached only
    at one level (e.g. a bridge tile reached via ramp from the bridge
    plateau but not from the ground beneath it).

    Iterative (not recursive): each (tile, level) combo is flood-filled at
    most once across the whole search, bounded by O(tiles * levels). The
    ``timeout`` parameter caps wall-clock time — default 1.5s is enough for
    a Cycling-Road-sized 5x5-chunk grid and keeps ``view_map`` responsive.

    When ``max_steps`` is given, both the per-level floods and the ramp
    transition enqueue respect it: tiles farther than the cap are omitted
    and transitions whose entry distance already exceeds the cap are not
    followed.
    """
    deadline = time.monotonic() + timeout
    reach: dict[tuple[int, int, int], int] = {}
    visited_level_starts: set[tuple[int, int, int]] = set()

    # Work queue: (flood_start_x, flood_start_y, level, base_steps).
    # Each entry triggers one flood_fill_level pass on the level.
    work: deque[tuple[int, int, int, int]] = deque(
        [(start_x, start_y, start_level, 0)]
    )
    visited_level_starts.add((start_x, start_y, start_level))

    while work:
        if time.monotonic() > deadline:
            break

        sx, sy, level, base_steps = work.popleft()
        level_budget = None if max_steps is None else max(0, max_steps - base_steps)
        level_reach, level_transitions = _flood_fill_level(
            terrain_info, npc_set, elevation,
            sx, sy, level, width=width, height=height,
            max_steps=level_budget,
        )
        for (tx, ty), s in level_reach.items():
            total = base_steps + s
            if max_steps is not None and total > max_steps:
                continue
            key = (tx, ty, level)
            prev = reach.get(key)
            if prev is None or total < prev:
                reach[key] = total

        for _key, (steps_to_t, (rx, ry), other_level) in level_transitions.items():
            seed = (rx, ry, other_level)
            if seed in visited_level_starts:
                continue
            new_base = base_steps + steps_to_t
            if max_steps is not None and new_base > max_steps:
                continue
            visited_level_starts.add(seed)
            work.append((rx, ry, other_level, new_base))

    return reach


def _build_multi_chunk_terrain(
    emu: EmulatorClient, map_id: int, px: int, py: int, target_x: int, target_y: int,
    extra_targets: list[tuple[int, int]] | None = None,
) -> tuple | None:
    """Load multi-chunk terrain grid. Returns (terrain_info, origin_x, origin_y, w, h) or None.

    The chunk window is bounded by the player, the (target_x, target_y) coord,
    and any ``extra_targets`` tiles — then expanded by one chunk on each side.
    Pass every POI a caller needs reachable (warps, objects) in ``extra_targets``
    so a player standing in a corner-chunk of a wide map still gets a BFS grid
    that covers the full single-map route; otherwise connectors in distant
    chunks vanish. Capped at 5x5 chunks regardless.
    """
    result = get_matrix_for_map(emu, map_id)
    if result is None:
        return None

    matrix_id, mw, mh, header_ids, terrain_ids = result

    player_chunk_x = px // CHUNK_SIZE
    player_chunk_y = py // CHUNK_SIZE
    target_chunk_x = target_x // CHUNK_SIZE
    target_chunk_y = target_y // CHUNK_SIZE

    xs = [player_chunk_x, target_chunk_x]
    ys = [player_chunk_y, target_chunk_y]
    if extra_targets:
        for tx, ty in extra_targets:
            xs.append(tx // CHUNK_SIZE)
            ys.append(ty // CHUNK_SIZE)

    min_cx = max(0, min(xs) - 1)
    max_cx = min(mw - 1, max(xs) + 1)
    min_cy = max(0, min(ys) - 1)
    max_cy = min(mh - 1, max(ys) + 1)

    # Cap at 5x5 chunks. With extra_targets (view_map reachability), center on
    # the player — the flood starts there and we'd rather lose distant POIs
    # than miss the player's own chunk. Without extras (navigate_to /
    # interaction), center on the player↔target midpoint so both endpoints
    # stay in bounds.
    if max_cx - min_cx > 4:
        if extra_targets:
            min_cx = max(0, player_chunk_x - 2)
            max_cx = min(mw - 1, player_chunk_x + 2)
        else:
            mid = (player_chunk_x + target_chunk_x) // 2
            min_cx = max(0, mid - 2)
            max_cx = min(mw - 1, mid + 2)
    if max_cy - min_cy > 4:
        if extra_targets:
            min_cy = max(0, player_chunk_y - 2)
            max_cy = min(mh - 1, player_chunk_y + 2)
        else:
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


def _classify_objects_for_grid(
    objects: list, grid_ox: int, grid_oy: int, grid_w: int, grid_h: int,
) -> tuple[set, dict]:
    """Classify map objects into npc_set and obstacle_map for a given grid region."""
    npc_set: set[tuple[int, int]] = set()
    obstacle_map: dict[tuple[int, int], dict] = {}
    for obj in objects:
        if obj["index"] == 0:
            continue
        if is_follower_npc(obj):
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
