"""Fishing encounter logic and pacing-pair seeking.

Handles fishing rod usage (bite detection, hook timing), positioning
near water, and the grass/cave pacing pair search for seek_encounter.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from renegade_mcp.nav_constants import (
    _DIR_DELTAS,
    _FACING_DELTAS,
    _FACING_VALUES,
    _FISH_ANIM_BITE,
    _FISH_ANIM_OFFSET,
    _FISH_MAX_POLL,
    _ROD_NAMES,
    BFS_MOVES,
    GRASS_BEHAVIOR,
    LEDGE_DIRECTIONS,
    OPPOSITE_DIR,
    SEEK_MAX_CASTS,
    SEEK_MAX_STEPS,
    WAIT_FRAMES,
    WATER_BEHAVIORS,
    _get_move_hold,
    _pos_with_map,
    _read_position,
)
from renegade_mcp.map_state import (
    FACING_NAMES,
    get_map_state,
    read_player_state,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


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


def _fish_once(emu: EmulatorClient, rod_name: str) -> dict[str, Any]:
    """Execute one fishing attempt: use rod → detect bite → press A → battle.

    Returns dict with:
        result: "encounter" | "no_bite" | "got_away" | "error"
        encounter: (only on "encounter") battle data from _post_nav_check
        error: (only on "error") error message
    """
    from renegade_mcp.use_item import activate_key_item, FISHING_FUNCS
    from renegade_mcp.addresses import addr
    # Lazy import to avoid circular dependency
    from renegade_mcp.nav_events import _post_nav_check

    # Use the rod through the menu system
    activated = activate_key_item(emu, rod_name, allowed_funcs=FISHING_FUNCS)
    if not activated.get("success"):
        return {"result": "error", "error": activated.get("error", "Failed to use rod.")}

    # Menu is closing, fishing animation starting.
    # Read the player MapObject animation state to detect the bite.
    obj_base = addr("OBJ_ARRAY_FPX_BASE") - 0x70  # MapObject[0] true start
    anim_addr = obj_base + _FISH_ANIM_OFFSET

    # Phase 1: Wait for cast animation to start (anim 0 → 1).
    cast_result = emu.advance_frames_until(
        max_frames=120,
        conditions=[{"type": "value", "address": anim_addr, "size": "long",
                     "operator": "==", "value": 1}],
    )
    if not cast_result["triggered"]:
        # Cast never started — dismiss any leftover text and bail.
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(60)
        return {"result": "got_away"}

    # Phase 2: Wait for bite (anim == 2) or return to idle (anim == 0 = no bite).
    bite_result = emu.advance_frames_until(
        max_frames=_FISH_MAX_POLL,
        conditions=[
            {"type": "value", "address": anim_addr, "size": "long",
             "operator": "==", "value": _FISH_ANIM_BITE},   # condition 0: bite
            {"type": "value", "address": anim_addr, "size": "long",
             "operator": "==", "value": 0},                  # condition 1: no bite
        ],
    )

    if bite_result["triggered"] and bite_result["condition_index"] == 0:
        # Bite! Press A immediately to hook the fish.
        emu.press_buttons(["a"], frames=8)

        # Reeling animation plays (~15 frames), then "Landed a Pokémon!"
        # text appears. Wait for the text, then dismiss with A/B.
        emu.advance_frames(120)
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(120)
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(120)

        # Battle transition now. Use _post_nav_check which polls up to
        # 300 frames for battle detection and advances through intro.
        encounter = _post_nav_check(emu)
        if encounter is not None:
            return {"result": "encounter", "encounter": encounter}

        # Fallback: advance more and re-check
        emu.advance_frames(600)
        encounter = _post_nav_check(emu)
        if encounter is not None:
            return {"result": "encounter", "encounter": encounter}

        return {"result": "error", "error": "Bite detected but battle did not start."}

    elif bite_result["triggered"] and bite_result["condition_index"] == 1:
        # Animation returned to idle after casting = "Not even a nibble..."
        # Dismiss the text with B and return.
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(120)
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(60)
        return {"result": "no_bite"}

    # Timeout — might be "The Pokémon got away..." or stuck.
    # Dismiss any text and return.
    emu.press_buttons(["b"], frames=8)
    emu.advance_frames(120)
    emu.press_buttons(["b"], frames=8)
    emu.advance_frames(60)
    return {"result": "got_away"}


def _find_fishing_spot(
    terrain: list, local_px: int, local_py: int,
    npc_set: set, width: int, height: int,
) -> tuple[int, int, str] | None:
    """Find a walkable tile adjacent to water and the direction to face.

    BFS from player position to find the nearest free tile that has at least
    one adjacent water tile. Returns (local_x, local_y, face_direction) or None.
    """
    queue: deque[tuple[int, int, list[str]]] = deque()
    queue.append((local_px, local_py, []))
    visited: set[tuple[int, int]] = {(local_px, local_py)}

    while queue:
        cx, cy, path = queue.popleft()

        # Check if this tile has an adjacent water tile
        for direction, (dx, dy) in _DIR_DELTAS.items():
            wx, wy = cx + dx, cy + dy
            if 0 <= wx < width and 0 <= wy < height:
                behavior = terrain[wy][wx] & 0x00FF
                if behavior in WATER_BEHAVIORS:
                    return (cx, cy, direction)

        # Expand BFS to adjacent walkable tiles
        if len(path) >= 15:
            continue
        for direction, (dx, dy) in _DIR_DELTAS.items():
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in visited:
                continue
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            cell = terrain[ny][nx]
            blocked = (cell & 0x8000) != 0
            behavior = cell & 0x00FF
            if blocked or behavior in WATER_BEHAVIORS:
                continue
            if (nx, ny) in npc_set:
                continue
            visited.add((nx, ny))
            queue.append((nx, ny, path + [direction]))

    return None


def _seek_fishing(emu: EmulatorClient, rod_name: str) -> dict[str, Any]:
    """Fish repeatedly until a wild encounter triggers or max casts reached.

    Handles positioning near water, facing water, and retrying on misses.
    """
    # Validate rod name
    if rod_name.lower() not in _ROD_NAMES:
        return {"error": f"Unknown rod: '{rod_name}'. Valid: Old Rod, Good Rod, Super Rod."}

    # Check bag for the rod
    from renegade_mcp.bag import read_bag
    bag = read_bag(emu)
    key_pocket = None
    for pocket in bag:
        if pocket["name"] == "Key Items":
            key_pocket = pocket
            break
    if key_pocket is None:
        return {"error": "Key Items pocket not found in bag data."}
    rod_found = any(it["name"].lower() == rod_name.lower() for it in key_pocket["items"])
    if not rod_found:
        available_rods = [it["name"] for it in key_pocket["items"]
                          if it["name"].lower() in _ROD_NAMES]
        msg = f"'{rod_name}' not found in Key Items."
        if available_rods:
            msg += f" Available rods: {', '.join(available_rods)}."
        else:
            msg += " No fishing rods in bag."
        return {"error": msg}

    # Read current state
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not read map state."}

    local_px, local_py = state["local_px"], state["local_py"]
    terrain = state["terrain"]
    origin_x = state.get("origin_x", 0)
    origin_y = state.get("origin_y", 0)
    h = len(terrain)
    w = len(terrain[0]) if terrain else 32

    npc_set: set[tuple[int, int]] = set()
    for obj in state.get("objects", []):
        if obj["index"] == 0:
            continue
        lx = obj.get("local_x", obj["x"]) - origin_x
        ly = obj.get("local_y", obj["y"]) - origin_y
        if 0 <= lx < w and 0 <= ly < h:
            npc_set.add((lx, ly))

    # Check if player is surfing (standing on a water tile)
    player_behavior = terrain[local_py][local_px] & 0x00FF if (
        0 <= local_py < h and 0 <= local_px < w
    ) else 0
    is_surfing = player_behavior in WATER_BEHAVIORS

    if is_surfing:
        # Already on water — check if facing a water tile, if not turn to face one
        _, _, _, facing_val = read_player_state(emu)
        facing_name = FACING_NAMES.get(facing_val, "down")
        dx, dy = _FACING_DELTAS.get(facing_val, (0, 1))
        check_x, check_y = local_px + dx, local_py + dy

        facing_water = (
            0 <= check_x < w and 0 <= check_y < h
            and (terrain[check_y][check_x] & 0x00FF) in WATER_BEHAVIORS
        )

        if not facing_water:
            # Turn to face a water tile
            for direction, (ddx, ddy) in _DIR_DELTAS.items():
                nx, ny = local_px + ddx, local_py + ddy
                if 0 <= nx < w and 0 <= ny < h:
                    if (terrain[ny][nx] & 0x00FF) in WATER_BEHAVIORS:
                        emu.press_buttons([direction], frames=2)
                        emu.advance_frames(15)
                        break
    else:
        # Not surfing — find a walkable tile next to water and navigate there
        spot = _find_fishing_spot(terrain, local_px, local_py, npc_set, w, h)
        if spot is None:
            return {"error": "No water tiles found nearby to fish from."}

        target_lx, target_ly, face_dir = spot
        target_gx = target_lx + origin_x
        target_gy = target_ly + origin_y

        # Navigate to the fishing spot if not already there
        if (local_px, local_py) != (target_lx, target_ly):
            # Lazy import to avoid circular dependency
            from renegade_mcp.navigation import navigate_to
            nav_result = navigate_to(emu, target_gx, target_gy)
            if nav_result.get("encounter"):
                return {"result": "encounter", "steps_taken": 0,
                        "encounter": nav_result["encounter"]}

        # Face the water
        emu.press_buttons([face_dir], frames=2)
        emu.advance_frames(15)

    # Fish repeatedly until encounter or max casts
    casts = 0
    for casts in range(1, SEEK_MAX_CASTS + 1):
        result = _fish_once(emu, rod_name)

        if result["result"] == "encounter":
            return {
                "result": "encounter",
                "steps_taken": casts,
                "encounter": result["encounter"],
            }
        elif result["result"] == "error":
            return {"error": result["error"], "casts": casts}
        # "no_bite" or "got_away" — retry

    _, fx, fy = _read_position(emu)
    return {
        "result": "max_casts",
        "steps_taken": casts,
        "position": _pos_with_map(fx, fy, _read_position(emu)[0]),
    }


def seek_encounter(emu: EmulatorClient, cave: bool = False,
                   rod: str = "") -> dict[str, Any]:
    """Walk in grass/cave or fish until a wild encounter triggers.

    Without rod: finds nearest grass tiles (or cave walkable tiles) and paces
    between them. Checks for battle after each step. Caps at 200 steps.

    With rod: validates the rod is in the bag, positions near water (or turns
    to face water if surfing), uses the rod, and detects the bite via the
    player's MapObject animation state. Retries on "not even a nibble" and
    "the Pokémon got away". Caps at 20 casts.

    Args:
        cave: If True, pace on any walkable tiles (not just grass).
        rod: Name of fishing rod to use (e.g. "Old Rod"). Empty = no fishing.

    Returns dict with result type, steps taken, and encounter data if found.
    """
    # ── Fishing path ──
    if rod:
        return _seek_fishing(emu, rod)

    # ── Grass/cave path ──
    # Lazy import to avoid circular dependency
    from renegade_mcp.nav_events import _post_nav_check
    from renegade_mcp.phase_timer import phase

    with phase("seek_setup"):
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
