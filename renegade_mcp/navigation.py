"""Manual walking and BFS pathfinding for overworld navigation.

Connects to the emulator to move the player one tile at a time,
verifying position after each step.

Implementation is split across several submodules for maintainability:
  nav_constants   — shared constants and tiny utilities
  pathfinding     — BFS algorithms and terrain grid construction
  hm_traverse     — HM field move obstacle clearing
  cycling_road    — cycling road bridge + bike slope traversal
  nav_events      — post-navigation encounter/dialogue detection
  fishing         — fishing encounters and pacing-pair seeking
  interaction     — NPC/object interaction
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# ── Re-exports for backward compatibility ──
# All symbols that were previously defined in this file are re-exported so
# that existing imports (tests, server.py, other modules) continue to work.

# --- nav_constants (all constants + utilities) ---
from renegade_mcp.nav_constants import (  # noqa: F401
    _3D_MAX_DEPTH,
    _3D_TIMEOUT,
    _ADJACENT_OFFSETS,
    _BATTLE_OVER,
    _DELTA_TO_FACE,
    _DIAG_CHAR,
    _DIR_DELTAS,
    _FACE_TO_INT,
    _FAINT_STATES,
    _FACING_DELTAS,
    _FACING_VALUES,
    _FISH_ANIM_BITE,
    _FISH_ANIM_OFFSET,
    _FISH_MAX_POLL,
    _INTERACT_COOLDOWN,
    _MOVING_NPC_POLL,
    _MOVING_NPC_TIMEOUT,
    _OPPOSITE_DIR,
    _ROD_NAMES,
    AUTO_NAVIGATE_TYPES,
    BADGE_BITS,
    BFS_MOVES,
    BIKE_HOLD_FRAMES,
    BIKE_RAMP_BEHAVIORS,
    BIKE_RAMP_DIRECTIONS,
    BIKE_RAMP_JUMP_TILES,
    BIKE_RAMP_NEAR_JUMP_TILES,
    BIKE_RAMP_RUNWAY_TILES,
    BIKE_RAMP_TYPES,
    BIKE_BRIDGE_BEHAVIORS,
    BIKE_BRIDGE_TYPES,
    BIKE_SLOPE_BACKUP_TILES,
    BIKE_SLOPE_BEHAVIORS,
    BIKE_SLOPE_MAX_FRAMES,
    BIKE_SLOPE_RUNWAY_TILES,
    BIKE_SLOPE_TYPES,
    CLEARABLE_OBSTACLES,
    CLEARABLE_TYPES,
    CYCLING_ROAD_LATERAL_HOLD,
    CYCLING_ROAD_MAX_WAIT,
    CYCLING_ROAD_POLL_INTERVAL,
    CYCLING_ROAD_SLIDE_RATE,
    CYCLING_ROAD_UPHILL_HOLD,
    DIR_ALIASES,
    DIRECTIONAL_BLOCKS,
    DIRECTIONAL_WARP,
    DOOR_ACTIVATION,
    DOOR_POLL_FRAMES,
    DOOR_TRANSITION_POLLS,
    GRASS_BEHAVIOR,
    HM_INTERACT_WAIT,
    HM_OBSTACLES,
    HM_POST_CONFIRM_WAIT,
    HM_SETTLE_WAIT,
    HOLD_FRAMES,
    INTERACT_A_WAIT,
    INTERACT_DIALOGUE_WAIT,
    LEDGE_DIRECTIONS,
    MAX_FLEE_ENCOUNTERS,
    MAX_REPATHS,
    MULTI_TILE_HM_TYPES,
    OPPOSITE_DIR,
    POST_BATTLE_SETTLE,
    POST_NAV_MAX_POLLS,
    POST_NAV_POLL_FRAMES,
    PUZZLE_OBSTACLES,
    ROCK_CLIMB_BEHAVIORS,
    ROCK_CLIMB_TYPES,
    SEEK_MAX_CASTS,
    SEEK_MAX_STEPS,
    SETTLE_FRAMES,
    SLOW_TERRAIN_RETRIES,
    SURF_HOLD_FRAMES,
    SURF_TYPES,
    TERRAIN_OBSTACLE_INFO,
    TERRAIN_OBSTACLES,
    WARP_PASSABLE,
    WATER_BEHAVIORS,
    WATERFALL_BEHAVIOR,
    WATERFALL_TYPES,
    WAIT_FRAMES,
    _get_move_hold,
    _normalize_direction,
    step_hold,
    _pos_with_map,
    _read_position,
    _summarize_path,
    _tile_behavior_hint,
    parse_directions,
)

# --- pathfinding ---
from renegade_mcp.pathfinding import (  # noqa: F401
    _bfs_pathfind,
    _bfs_pathfind_3d,
    _bfs_pathfind_level,
    _bfs_pathfind_obstacles,
    _bfs_reachable,
    _build_multi_chunk_elevation,
    _build_multi_chunk_terrain,
    _build_terrain_info,
    _classify_objects_for_grid,
    _dedupe_obstacles,
    _find_nearest_reachable,
    _get_field_move_availability,
    _get_tile_level,
    _height_to_level,
    _render_failure_diagram,
    _validate_path,
    _validate_path_elevation,
)

# --- hm_traverse ---
from renegade_mcp.hm_traverse import _clear_hm_obstacle  # noqa: F401

# --- cycling_road ---
from renegade_mcp.cycling_road import (  # noqa: F401
    _check_encounter_quick,
    _get_current_tile_behavior,
    _navigate_cycling_road,
    _traverse_bike_slope,
)

# --- nav_events ---
from renegade_mcp.nav_events import (  # noqa: F401
    _flee_wild_battle,
    _handle_door_transition,
    _post_nav_check,
    _try_flee_encounter,
)

# --- fishing ---
from renegade_mcp.fishing import (  # noqa: F401
    _find_fishing_spot,
    _find_pacing_pair,
    _fish_once,
    _seek_fishing,
    seek_encounter,
)

# --- interaction ---
from renegade_mcp.interaction import (  # noqa: F401
    _target_info,
    _wait_for_moving_npc,
    interact_with,
)

# ── Imports for this module's own code ──
from renegade_mcp.map_state import (
    analyze_elevation,
    get_land_data_id,
    get_map_state,
    is_on_cycling_road,
    parse_bdhc,
    read_objects,
    read_player_height,
    read_sign_tiles_from_rom,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def _attach_warp_hint(
    result: dict[str, Any], terrain_info: list, sx: int, sy: int,
) -> None:
    """If (sx, sy) is a directional warp tile, attach a 'note' telling the
    caller to press the warp direction instead of trying to walk through it."""
    if not (0 <= sy < len(terrain_info) and 0 <= sx < len(terrain_info[0])):
        return
    _, start_behavior = terrain_info[sy][sx]
    direction = DIRECTIONAL_WARP.get(start_behavior)
    if direction is None:
        return
    result["note"] = (
        f"You are standing on a directional warp tile.  "
        f"Trigger it with `press_buttons(['{direction}'])` "
        f"to transition, then navigate from the other side."
    )


# ── NPC tracking and dynamic repathing ──

def _read_npc_positions(emu: EmulatorClient) -> dict[int, tuple[int, int]]:
    """Read current NPC tile positions. Returns {obj_index: (global_x, global_y)}.

    Followers (Mira, Cheryl, rival escorts) are excluded — they trail the
    player tile-by-tile, so every step would otherwise register as a fake
    NPC movement AND their position would spuriously block repath BFS in
    narrow corridors.
    """
    from renegade_mcp.nav_constants import is_follower_npc
    objects = read_objects(emu)
    return {
        obj["index"]: (obj["x"], obj["y"])
        for obj in objects
        if obj["index"] != 0 and not is_follower_npc(obj)
    }


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

    # When surfing, use obstacle-aware BFS so water tiles remain passable
    if ctx.get("surfing"):
        field_moves = ctx.get("field_moves", {})
        obstacle_map = ctx.get("obstacle_map", {})
        obs_path, _ = _bfs_pathfind_obstacles(
            ctx["terrain_info"], npc_set, obstacle_map,
            sx, sy, ctx["goal_x"], ctx["goal_y"],
            field_moves, width=w, height=h,
        )
        if obs_path is not None:
            return obs_path

    return _bfs_pathfind(
        ctx["terrain_info"], npc_set,
        sx, sy, ctx["goal_x"], ctx["goal_y"],
        width=w, height=h,
    )


def _auto_mount_for_slope(emu: EmulatorClient) -> bool:
    """Mount the bicycle if not already on it. Returns True on success.

    Always ends with the bike in fast gear — `use_item("Bicycle")` already
    forces fast on fresh mount, and if the player was already cycling we
    toggle here. Slopes and long-jump ramps only fire reliably at fast gear.
    (BIKE_GEAR_STATE_ADDR byte==1 is fast; see addresses.py docstring.)
    """
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import _ensure_fast_gear, use_item

    if bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")):
        _ensure_fast_gear(emu)
        return True
    mount = use_item(emu, "Bicycle")
    return bool(mount.get("success"))


def _auto_dismount_if_bike(emu: EmulatorClient) -> bool:
    """Dismount the bicycle if currently mounted. Returns True if the player
    is off-bike at exit (including the no-op case where they were already on
    foot). False only when a dismount was attempted and failed."""
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    if not bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")):
        return True
    result = use_item(emu, "Bicycle")
    return bool(result.get("success"))


def _bike_ramp_segment(
    directions: list[str], i: int, obstacle_tiles: dict, cur_x: int, cur_y: int,
    terrain_info: list | None = None, grid_ox: int = 0, grid_oy: int = 0,
    npc_set: set | None = None,
    goal_x: int | None = None, goal_y: int | None = None,
) -> tuple[int, int, int, int, int] | None:
    """If step i starts a contiguous same-direction bike-ramp segment,
    return ``(segment_end_idx, landing_x, landing_y, last_ramp_tile_x,
    last_ramp_tile_y, target_gear)`` — otherwise ``None``, and the
    caller falls back to per-tile step execution.

    A segment is walked as ONE sustained direction hold. Releasing
    between tiles drains the engine's bike-speed accumulator, so an
    in-chain far ramp would refuse entry (fast-gear step gate requires
    speed ≥ 2) and the sequence breaks down.

    The segment extends forward while direction stays the same
    (momentum resets on turn), and terminates at the last ramp's
    landing tile OR when direction changes.

    Momentum tracking matches BFS: same-direction steps accumulate
    momentum (capped at RUNWAY), ramp entries fire either:
      • FAR jump when ``momentum + 1 >= RUNWAY`` and ramp+4 is clear —
        lands at approach + ``BIKE_RAMP_JUMP_TILES``, post-momentum =
        RUNWAY, requires ``target_gear = 0`` (fast, decomp semantic).
      • FAR_SHORT jump when ``momentum + 1 >= RUNWAY`` but ramp+4 is a
        same-direction ramp / wall / NPC — engine auto-truncates, lands
        at approach + (JUMP_TILES - 1) = ramp+3, post-momentum = 0.
        This halts any chain (next ramp can't fire without RUNWAY
        momentum) so the segment ends at this landing.
      • NEAR jump when ``momentum == 0`` — lands at approach +
        ``BIKE_RAMP_NEAR_JUMP_TILES``, post-momentum = 1, requires
        ``target_gear = 1`` (slow).

    A segment's ``target_gear`` is the gear required by the FIRST
    ramp in the chain.  Mixed near+far (different gear requirements)
    bails with ``None`` and the per-tile fallback handles it.

    The ``last_ramp_tile_*`` coords are the ramp tile that triggers
    the final jump (not the landing); polling for that position +
    idling the jump animation lets the engine place the player
    cleanly on the landing with no drift past the target.

    ``terrain_info`` + ``grid_ox/oy`` + ``npc_set`` are optional
    blocker-detection inputs (grid-local coord space).  When supplied,
    the "+4 blocker → +3" rule honors walls and NPCs too; without
    them it falls back to same-direction-ramp detection via
    ``obstacle_tiles`` (the common case).
    """
    if i >= len(directions):
        return None
    d = directions[i]
    dx, dy = _DIR_DELTAS.get(d, (0, 0))
    if dx == 0 and dy == 0:
        return None

    def _far_plus_one_blocked(ramp_gx: int, ramp_gy: int) -> bool:
        """Is ramp+4 (= ramp_gx + 4*dx, ramp_gy + 4*dy) blocked by a same-
        direction ramp, wall, or NPC?  Mirrors the rule in
        ``_bike_ramp_edges``."""
        far_gx = ramp_gx + dx * (BIKE_RAMP_JUMP_TILES - 1)
        far_gy = ramp_gy + dy * (BIKE_RAMP_JUMP_TILES - 1)
        # Same-direction ramp check via obstacle_tiles (global coords).
        obs_far = obstacle_tiles.get((far_gx, far_gy))
        if obs_far is not None and obs_far.get("type") in BIKE_RAMP_TYPES:
            if BIKE_RAMP_DIRECTIONS.get(obs_far.get("behavior")) == d:
                return True
        # Terrain / NPC check (grid-local) when provided.
        if terrain_info is not None:
            tx, ty = far_gx - grid_ox, far_gy - grid_oy
            if not (0 <= ty < len(terrain_info)) or not (0 <= tx < len(terrain_info[0])):
                return True
            p, beh = terrain_info[ty][tx]
            if not p:
                return True
            if (beh in BIKE_RAMP_BEHAVIORS
                    and BIKE_RAMP_DIRECTIONS[beh] == d):
                return True
        if npc_set is not None and (far_gx, far_gy) in npc_set:
            return True
        return False

    def _far_plus_one_is_chain_ramp(ramp_gx: int, ramp_gy: int) -> bool:
        """Is ramp+4 specifically a same-direction chain ramp (not a wall/
        void/NPC)?  Used to gate CHAIN_THROUGH — only chain-ramps let
        the bike re-fire mid-flight; other blockers just truncate the
        jump to ramp+3."""
        far_gx = ramp_gx + dx * (BIKE_RAMP_JUMP_TILES - 1)
        far_gy = ramp_gy + dy * (BIKE_RAMP_JUMP_TILES - 1)
        # NPC on the chain-ramp tile disables the chain (bike can't land on it).
        if npc_set is not None and (far_gx, far_gy) in npc_set:
            return False
        obs_far = obstacle_tiles.get((far_gx, far_gy))
        if obs_far is not None and obs_far.get("type") in BIKE_RAMP_TYPES:
            if BIKE_RAMP_DIRECTIONS.get(obs_far.get("behavior")) == d:
                return True
        if terrain_info is not None:
            tx, ty = far_gx - grid_ox, far_gy - grid_oy
            if 0 <= ty < len(terrain_info) and 0 <= tx < len(terrain_info[0]):
                _, beh = terrain_info[ty][tx]
                if beh in BIKE_RAMP_BEHAVIORS and BIKE_RAMP_DIRECTIONS[beh] == d:
                    return True
        return False

    def _chain_through_landing_clear(ramp_gx: int, ramp_gy: int) -> bool:
        """Is the chain-ramp's own FAR landing (= approach + 2*JUMP_TILES,
        or equivalently chain-ramp + JUMP_TILES) clear of walls, NPCs,
        and same-direction chain ramps?  Mirrors ``_tile_passable_clear
        (..., exclude_chain=True)`` in pathfinding."""
        # chain-ramp tile is at ramp + (JUMP_TILES - 1).  Its own FAR
        # landing adds another JUMP_TILES.
        ct_gx = ramp_gx + dx * (BIKE_RAMP_JUMP_TILES - 1 + BIKE_RAMP_JUMP_TILES)
        ct_gy = ramp_gy + dy * (BIKE_RAMP_JUMP_TILES - 1 + BIKE_RAMP_JUMP_TILES)
        if npc_set is not None and (ct_gx, ct_gy) in npc_set:
            return False
        if terrain_info is not None:
            tx, ty = ct_gx - grid_ox, ct_gy - grid_oy
            if not (0 <= ty < len(terrain_info)) or not (0 <= tx < len(terrain_info[0])):
                return False
            p, beh = terrain_info[ty][tx]
            if not p:
                return False
            if beh in BIKE_RAMP_BEHAVIORS and BIKE_RAMP_DIRECTIONS[beh] == d:
                return False
        return True

    fx, fy = cur_x, cur_y
    momentum = 0
    last_ramp_idx = -1
    last_ramp_fx = last_ramp_fy = None
    last_ramp_tile_fx = last_ramp_tile_fy = None
    # For normal ramps the executor releases the direction button when
    # the player reaches the ramp tile (the jump then animates out).
    # CHAIN_THROUGH requires holding past the chain transition so the
    # chain-ramp auto-fires; track the release target separately.
    release_tile_fx = release_tile_fy = None
    segment_gear: int | None = None  # locked by first ramp; follow-ups must match
    j = i
    while j < len(directions):
        if directions[j] != d:
            break
        nx, ny = fx + dx, fy + dy
        obs = obstacle_tiles.get((nx, ny))
        is_ramp_here = obs is not None and obs.get("type") in BIKE_RAMP_TYPES
        if is_ramp_here:
            if momentum + 1 >= BIKE_RAMP_RUNWAY_TILES:
                if _far_plus_one_blocked(nx, ny):
                    # Distinguish CHAIN_THROUGH (chain-ramp at +4 with
                    # clear landing) from FAR_SHORT (non-chain blocker
                    # or release-at-pocket).  When the BFS-planned goal
                    # sits at the CHAIN_THROUGH landing, or the plan
                    # continues same-direction past this ramp, we hold
                    # through; otherwise we release and land at ramp+3.
                    ct_landing_x = fx + dx * (2 * BIKE_RAMP_JUMP_TILES)
                    ct_landing_y = fy + dy * (2 * BIKE_RAMP_JUMP_TILES)
                    goal_at_ct = (
                        goal_x is not None and goal_y is not None
                        and goal_x == ct_landing_x and goal_y == ct_landing_y
                    )
                    plan_continues = (
                        j + 1 < len(directions) and directions[j + 1] == d
                    )
                    if ((plan_continues or goal_at_ct)
                            and _far_plus_one_is_chain_ramp(nx, ny)
                            and _chain_through_landing_clear(nx, ny)):
                        # Holding direction through the chain: bike lands
                        # on chain-ramp mid-flight, re-fires, lands at
                        # chain-ramp + JUMP_TILES (= approach + 2*JUMP_TILES).
                        jump_tiles = 2 * BIKE_RAMP_JUMP_TILES
                        post_m = BIKE_RAMP_RUNWAY_TILES
                    else:
                        jump_tiles = BIKE_RAMP_JUMP_TILES - 1  # ramp+3
                        post_m = 0  # chain halts here
                else:
                    jump_tiles = BIKE_RAMP_JUMP_TILES
                    post_m = BIKE_RAMP_RUNWAY_TILES
                this_gear = 0  # fast (decomp semantic; _set_bike_gear inverts)
            elif momentum == 0:
                jump_tiles = BIKE_RAMP_NEAR_JUMP_TILES
                post_m = 1
                this_gear = 1  # slow (decomp semantic; _set_bike_gear inverts)
            else:
                # Mid-range momentum — BFS doesn't plan into this regime,
                # so if we're here the plan is inconsistent. Bail and let
                # the per-tile fallback handle it.
                return None
            if segment_gear is None:
                segment_gear = this_gear
            elif segment_gear != this_gear:
                # Mixed near+far in one continuous hold can't satisfy a
                # single gear setting. Bail on the mix; per-tile handles
                # the rest.
                return None
            last_ramp_tile_fx, last_ramp_tile_fy = nx, ny
            fx += dx * jump_tiles
            fy += dy * jump_tiles
            momentum = post_m
            last_ramp_idx = j
            last_ramp_fx, last_ramp_fy = fx, fy
            # Release target defaults to the ramp tile (single-jump cases).
            # CHAIN_THROUGH must hold through the chain animation, so the
            # release target becomes the chain-through landing itself.
            if jump_tiles == 2 * BIKE_RAMP_JUMP_TILES:
                release_tile_fx, release_tile_fy = fx, fy
            else:
                release_tile_fx, release_tile_fy = nx, ny
            if post_m == 0:
                # FAR_SHORT halts the chain — segment ends at this landing
                # regardless of what the path does next.
                j += 1
                break
        else:
            fx, fy = nx, ny
            momentum = min(momentum + 1, BIKE_RAMP_RUNWAY_TILES)
        j += 1

    if last_ramp_idx == -1 or segment_gear is None:
        return None

    # Use the per-jump-type release target if set; fall back to the last
    # ramp tile for legacy single-jump paths.
    rel_fx = release_tile_fx if release_tile_fx is not None else last_ramp_tile_fx
    rel_fy = release_tile_fy if release_tile_fy is not None else last_ramp_tile_fy
    return (
        last_ramp_idx, last_ramp_fx, last_ramp_fy,
        rel_fx, rel_fy, segment_gear,
    )


def _scan_path_for_bike_obstacles(
    directions: list[str], terrain_info: list, start_gx: int, start_gy: int,
    grid_ox: int, grid_oy: int, obstacle_tiles: dict,
) -> None:
    """Populate ``obstacle_tiles`` with bike-ramp/slope tiles crossed by the
    planned path. Idempotent — existing keys are kept.

    Mirrors the scanner in _navigate_to_impl (which builds the same map
    from obs_crossed), but works for callers like interact_with that
    dispatch directly to _execute_path without a navigate_to detour.
    Without these entries, _step_needs_bike can't detect ramps ahead and
    the executor walks straight into the ramp tile on foot.

    Coordinates: ``start_gx/gy`` are the player's starting grid-local
    position (grid_ox/oy is the grid→global offset). Simulates
    momentum (reset on direction change) so ramp entries advance by
    far-jump or near-jump displacement matching what BFS planned.
    """
    sx, sy = start_gx, start_gy
    last_dir: str | None = None
    momentum = 0
    for i, step_dir in enumerate(directions):
        sdx, sdy = _DIR_DELTAS.get(step_dir, (0, 0))
        if step_dir != last_dir:
            momentum = 0
        nx, ny = sx + sdx, sy + sdy
        is_ramp = False
        if 0 <= ny < len(terrain_info) and 0 <= nx < len(terrain_info[ny]):
            _, nbeh = terrain_info[ny][nx]
            if (nbeh in BIKE_RAMP_BEHAVIORS
                    and BIKE_RAMP_DIRECTIONS[nbeh] == step_dir):
                is_ramp = True
                gx, gy = nx + grid_ox, ny + grid_oy
                if (gx, gy) not in obstacle_tiles:
                    obstacle_tiles[(gx, gy)] = {
                        "type": "bike_ramp",
                        "behavior": nbeh,
                    }
        if is_ramp:
            if momentum + 1 >= BIKE_RAMP_RUNWAY_TILES:
                # FAR-class jump: natural landing is ramp+4, but if that
                # tile is blocked (same-dir ramp / wall / void) the engine
                # truncates to ramp+3 and stops momentum (FAR_SHORT) — unless
                # the blocker is a chain-ramp AND the next plan direction
                # continues through it AND chain-ramp's own landing is
                # clear, in which case CHAIN_THROUGH carries the bike to
                # approach + 2*JUMP_TILES. Mirrors _bike_ramp_edges.
                far_x, far_y = sx + sdx * BIKE_RAMP_JUMP_TILES, sy + sdy * BIKE_RAMP_JUMP_TILES
                far_is_chain = False
                far_blocked = True
                if 0 <= far_y < len(terrain_info) and 0 <= far_x < len(terrain_info[far_y]):
                    far_p, far_beh = terrain_info[far_y][far_x]
                    if far_p and not (
                        far_beh in BIKE_RAMP_BEHAVIORS
                        and BIKE_RAMP_DIRECTIONS[far_beh] == step_dir
                    ):
                        far_blocked = False
                    elif (far_beh in BIKE_RAMP_BEHAVIORS
                            and BIKE_RAMP_DIRECTIONS[far_beh] == step_dir):
                        far_is_chain = True
                if far_blocked:
                    plan_continues = (
                        i + 1 < len(directions) and directions[i + 1] == step_dir
                    )
                    ct_x = sx + sdx * (2 * BIKE_RAMP_JUMP_TILES)
                    ct_y = sy + sdy * (2 * BIKE_RAMP_JUMP_TILES)
                    ct_clear = False
                    if far_is_chain and plan_continues:
                        if 0 <= ct_y < len(terrain_info) and 0 <= ct_x < len(terrain_info[ct_y]):
                            ct_p, ct_beh = terrain_info[ct_y][ct_x]
                            if ct_p and not (
                                ct_beh in BIKE_RAMP_BEHAVIORS
                                and BIKE_RAMP_DIRECTIONS[ct_beh] == step_dir
                            ):
                                ct_clear = True
                    if far_is_chain and plan_continues and ct_clear:
                        # CHAIN_THROUGH. Also record the chain-ramp tile
                        # so downstream passes know it's in the path.
                        cr_gx, cr_gy = far_x + grid_ox, far_y + grid_oy
                        if (cr_gx, cr_gy) not in obstacle_tiles:
                            obstacle_tiles[(cr_gx, cr_gy)] = {
                                "type": "bike_ramp",
                                "behavior": far_beh,
                            }
                        jump_tiles = 2 * BIKE_RAMP_JUMP_TILES
                        momentum = BIKE_RAMP_RUNWAY_TILES
                    else:
                        jump_tiles = BIKE_RAMP_JUMP_TILES - 1  # ramp+3
                        momentum = 0  # chain halts at FAR_SHORT landing
                else:
                    jump_tiles = BIKE_RAMP_JUMP_TILES
                    momentum = BIKE_RAMP_RUNWAY_TILES
            elif momentum == 0:
                jump_tiles = BIKE_RAMP_NEAR_JUMP_TILES
                momentum = 1
            else:
                # Mid-range momentum — BFS wouldn't have planned here;
                # fall back to the old far-jump assumption so we don't
                # desync the scanner on edge cases.
                jump_tiles = BIKE_RAMP_JUMP_TILES
                momentum = BIKE_RAMP_RUNWAY_TILES
            sx = sx + sdx * jump_tiles
            sy = sy + sdy * jump_tiles
            last_dir = step_dir
            continue
        sx, sy = nx, ny
        momentum = min(momentum + 1, BIKE_RAMP_RUNWAY_TILES)
        last_dir = step_dir
        if 0 <= sy < len(terrain_info) and 0 <= sx < len(terrain_info[sy]):
            _passable, beh = terrain_info[sy][sx]
            if beh in BIKE_SLOPE_BEHAVIORS:
                gx, gy = sx + grid_ox, sy + grid_oy
                if (gx, gy) not in obstacle_tiles:
                    obstacle_tiles[(gx, gy)] = {
                        "type": "bike_slope",
                        "behavior": beh,
                    }
            elif beh in BIKE_BRIDGE_BEHAVIORS:
                gx, gy = sx + grid_ox, sy + grid_oy
                if (gx, gy) not in obstacle_tiles:
                    obstacle_tiles[(gx, gy)] = {
                        "type": "bike_bridge",
                        "behavior": beh,
                    }


def _step_needs_bike(
    directions: list[str], i: int, obstacle_tiles: dict, cur_x: int, cur_y: int,
) -> bool:
    """Return True if executing step ``i`` from (cur_x, cur_y) requires the
    bicycle.

    Three conditions qualify:
      • A bike-ramp entry within the same-direction runway window
        (BIKE_RAMP_RUNWAY_TILES): stay on bike through approach + chain so
        the engine's running-start detection fires the jump.
      • The IMMEDIATE next tile is a bike-slope ascent (up direction): mount
        before step_hold runs so step_hold-on-bike cleanly blocks, letting
        the slope branch fire the backup+run traversal. Walking onto a
        slope on foot "succeeds" briefly (position changes) before the
        engine slides the player back south, evading the blocked check
        (BUG-025). We ONLY check the immediate tile for slopes — not the
        runway ahead — because the BFS slope-runway rule (BUG-045) plans a
        south backup before the climb. A runway-style lookahead would
        mount the bike while the plan still has down-steps left, causing
        mount/dismount thrashing and oscillation against the repath loop.
      • The current OR immediate-next tile is a bike-bridge body
        (BIKE_BRIDGE_TYPES). The engine rejects on-foot entry to body
        tiles AND rejects mid-bridge dismounts, so the bike must be on
        across the whole span. Including the current tile in the check
        keeps the bike active for the last step that exits the bridge
        (body → bridge_start) so we don't emit a doomed dismount call
        from a body tile.
    """
    if i >= len(directions):
        return False
    d = directions[i]
    dx, dy = _DIR_DELTAS.get(d, (0, 0))
    if dx == 0 and dy == 0:
        return False

    # Bike bridge — current or immediate-next tile.
    cur = obstacle_tiles.get((cur_x, cur_y))
    if cur is not None and cur.get("type") in BIKE_BRIDGE_TYPES:
        return True
    imm_bridge = obstacle_tiles.get((cur_x + dx, cur_y + dy))
    if imm_bridge is not None and imm_bridge.get("type") in BIKE_BRIDGE_TYPES:
        return True

    # Slope ascent — immediate next tile only.
    if d == "up":
        imm = obstacle_tiles.get((cur_x + dx, cur_y + dy))
        if imm is not None and imm.get("type") in BIKE_SLOPE_TYPES:
            return True

    # Ramp runway — look ahead up to RUNWAY tiles, same direction only.
    x, y = cur_x, cur_y
    for k in range(BIKE_RAMP_RUNWAY_TILES):
        j = i + k
        if j >= len(directions):
            break
        if directions[j] != d:
            break  # direction change resets momentum — no runway past here
        nx, ny = x + dx, y + dy
        obs = obstacle_tiles.get((nx, ny))
        if obs is not None and obs.get("type") in BIKE_RAMP_TYPES:
            return True
        x, y = nx, ny
    return False


# ── Path execution ──

def _execute_path(
    emu: EmulatorClient,
    directions: list[str],
    track_npcs: bool = False,
    repath_ctx: dict | None = None,
    hold_frames: int = HOLD_FRAMES,
    obstacle_tiles: dict | None = None,
) -> tuple[bool, int, int, dict]:
    """Execute directions, verifying each step.

    When repath_ctx is provided, tracks NPC positions and attempts BFS repath
    when NPCs block or move into the planned path.

    Args:
        hold_frames: Frames to hold per step (16 walking, 8 cycling).
        obstacle_tiles: Dict mapping global (x, y) → obstacle info for
            clearable HM obstacles on the path. When a step is blocked at one
            of these tiles, the field move interaction is triggered to clear it.

    Returns (stopped_early, steps_taken, repaths_used, nav_info).
    nav_info contains compact summary data (map_change, blocked_at, npc_moves).
    """
    if repath_ctx is not None:
        track_npcs = True
    if obstacle_tiles is None:
        obstacle_tiles = {}

    # Callers that dispatch directly here (e.g. interact_with) don't populate
    # ramp/slope entries. Without them, _step_needs_bike is blind to ramps
    # ahead and the executor walks on foot into the ramp tile, bonks, and
    # repaths forever. Scan the path ourselves when terrain + grid offsets
    # are in scope.
    if repath_ctx is not None and "terrain_info" in repath_ctx:
        terr = repath_ctx["terrain_info"]
        gox = repath_ctx.get("grid_ox", 0)
        goy = repath_ctx.get("grid_oy", 0)
        _, start_gx_g, start_gy_g = _read_position(emu)
        _scan_path_for_bike_obstacles(
            directions, terr,
            start_gx_g - gox, start_gy_g - goy,
            gox, goy, obstacle_tiles,
        )

    steps_taken = 0
    repaths_used = 0
    npc_move_count = 0
    map_changed = False
    prev_npcs = _read_npc_positions(emu) if track_npcs else {}
    nav_info: dict = {}
    active_hold = hold_frames  # may change to SURF_HOLD_FRAMES after Surf activation
    last_step_was_ramp = False  # suppresses end-of-path settle that would drift past landing

    i = 0
    while i < len(directions):
        direction = directions[i]
        old_map, old_x, old_y = _read_position(emu)
        dx, dy = _DIR_DELTAS.get(direction, (0, 0))
        pre_target = (old_x + dx, old_y + dy)
        pre_obs = obstacle_tiles.get(pre_target)

        # Decide bike state for this step. Bike momentum carries across
        # direction changes — if the previous step moved the bike, the engine
        # finishes that in-progress move before accepting a new direction,
        # which can shift the player diagonally and off-path. So we only
        # keep the bike mounted during ramp/slope approaches (runway + chain);
        # every other tile is walked on foot where direction changes are safe.
        from renegade_mcp.addresses import addr as _addr
        on_bike = bool(emu.read_memory(_addr("CYCLING_GEAR_ADDR"), size="short"))
        step_wants_bike = _step_needs_bike(
            directions, i, obstacle_tiles, old_x, old_y,
        )
        if step_wants_bike and not on_bike:
            # Settle after any prior on-foot motion so the engine's player-
            # state is quiesced before the mount + ramp sequence. The mount
            # menu writes to player state; if a walk step is still in-
            # flight, the post-mount bike state can be inconsistent and the
            # first ramp of the chain fires at slow-gear displacement.
            emu.advance_frames(WAIT_FRAMES)
            if not _auto_mount_for_slope(emu):
                cur_obs = obstacle_tiles.get((old_x, old_y))
                if (pre_obs is not None and pre_obs.get("type") in BIKE_BRIDGE_TYPES) \
                        or (cur_obs is not None and cur_obs.get("type") in BIKE_BRIDGE_TYPES):
                    kind = "bike_bridge"
                elif pre_obs is not None and pre_obs.get("type") in BIKE_RAMP_TYPES:
                    kind = "bike_ramp"
                else:
                    kind = "bike_slope"
                nav_info["blocked_at"] = {"x": old_x, "y": old_y, "step": steps_taken}
                nav_info["blocked_reason"] = f"{kind}_requires_bicycle"
                nav_info["note"] = (
                    f"{kind.replace('_', ' ').capitalize()} approach at "
                    f"({old_x}, {old_y}) requires the Bicycle key item.  "
                    f"Get the Bicycle and retry."
                )
                return True, steps_taken, repaths_used, nav_info
            # Bike-bridge mounts use SLOW gear (byte=1). Slow gear prevents
            # the fast-gear bike's ~3-tile coast-on-release that otherwise
            # carries the player past the bridge exit during the dismount
            # menu open (the menu's verification `down` press then reads as
            # overworld input, adding a +1 south drift on top of the
            # westward coast). Bridges don't need momentum — slow gear is
            # fine. Ramps/slopes keep fast gear, which is asserted later.
            pre_obs_bridge = obstacle_tiles.get(pre_target)
            cur_obs_bridge = obstacle_tiles.get((old_x, old_y))
            on_bridge_segment = (
                (pre_obs_bridge is not None
                 and pre_obs_bridge.get("type") in BIKE_BRIDGE_TYPES)
                or (cur_obs_bridge is not None
                    and cur_obs_bridge.get("type") in BIKE_BRIDGE_TYPES)
            )
            if on_bridge_segment:
                from renegade_mcp.use_item import _set_bike_gear
                _set_bike_gear(emu, 1)
            active_hold = BIKE_HOLD_FRAMES
        elif not step_wants_bike and on_bike:
            # CYCLING_GEAR_ADDR is also non-zero during surf/waterfall, but
            # the player isn't on the bike — use_item(Bicycle) fails, and
            # the menu open/close frames let in-flight surf movement drift
            # the player off the movement axis (observed: 1 tile south per
            # spurious dismount attempt during westward surf).
            is_surfing = (
                (repath_ctx is not None and repath_ctx.get("surfing"))
                or active_hold == SURF_HOLD_FRAMES
            )
            if not is_surfing:
                _auto_dismount_if_bike(emu)
                active_hold = hold_frames

        # Sustained bike-ramp segment — runway + chained ramps as ONE
        # continuous hold. Per-tile step_hold releases the direction between
        # tiles, draining the engine's bike-momentum timer; a subsequent
        # ramp entry then fires at slow-gear displacement (~1 tile instead
        # of 4). Releasing only after the last ramp's settle preserves
        # momentum through the whole chain.
        if step_wants_bike:
            # Pass terrain + NPC context so the segment sim can honor the
            # "any blocker at ramp+4 → ramp+3 truncation" rule that
            # _bike_ramp_edges uses when planning.  Without these, the sim
            # only catches same-direction-ramp blockers (via obstacle_tiles);
            # walls and NPCs at +4 would desync sim from BFS.
            _seg_terrain = None
            _seg_gox = _seg_goy = 0
            _seg_npc: set | None = None
            if repath_ctx is not None:
                _seg_terrain = repath_ctx.get("terrain_info")
                _seg_gox = repath_ctx.get("grid_ox", 0)
                _seg_goy = repath_ctx.get("grid_oy", 0)
                _seg_npc = repath_ctx.get("npc_set")
            _seg_goal_x = _seg_goal_y = None
            if repath_ctx is not None:
                _gx = repath_ctx.get("goal_x")
                _gy = repath_ctx.get("goal_y")
                if _gx is not None and _gy is not None:
                    _seg_goal_x = _gx + _seg_gox
                    _seg_goal_y = _gy + _seg_goy
            seg = _bike_ramp_segment(
                directions, i, obstacle_tiles, old_x, old_y,
                terrain_info=_seg_terrain,
                grid_ox=_seg_gox, grid_oy=_seg_goy,
                npc_set=_seg_npc,
                goal_x=_seg_goal_x, goal_y=_seg_goal_y,
            )
            if seg is not None:
                seg_end_idx, seg_fx, seg_fy, ramp_tile_x, ramp_tile_y, seg_gear = seg
                from renegade_mcp.addresses import addr as _addr
                from renegade_mcp.use_item import _set_bike_gear
                # Post-mount settle + gear toggle. 90f lets any mount
                # animation fully apply so the player is PLAYER_STATE_CYCLING
                # settled — a precondition for B-press to register as a
                # gear toggle. Then set the gear the segment requires (1
                # for far-jump chains, 0 for near-jump). Byte writes to
                # BIKE_GEAR_STATE_ADDR are unreliable (engine re-syncs
                # from an authoritative mirror within ~60f), so the
                # helper uses B-press input.
                emu.advance_frames(90)
                _bgs_addr = _addr("BIKE_GEAR_STATE_ADDR")
                _pre_cycling = bool(
                    emu.read_memory(_addr("CYCLING_GEAR_ADDR"), size="short")
                )
                _pre_gear = emu.read_memory(_bgs_addr, size="byte")
                if not _set_bike_gear(emu, seg_gear):
                    _post_cycling = bool(
                        emu.read_memory(_addr("CYCLING_GEAR_ADDR"), size="short")
                    )
                    _post_gear = emu.read_memory(_bgs_addr, size="byte")
                    nav_info["blocked_at"] = {
                        "x": old_x, "y": old_y, "step": steps_taken,
                    }
                    nav_info["blocked_reason"] = "bike_gear_toggle_failed"
                    nav_info["gear_debug"] = {
                        "target": seg_gear,
                        "pre_cycling": _pre_cycling,
                        "pre_gear": _pre_gear,
                        "post_cycling": _post_cycling,
                        "post_gear": _post_gear,
                    }
                    return True, steps_taken, repaths_used, nav_info
                # Poll for stepping ONTO the last ramp tile (not the landing).
                # Releasing at the ramp tile, then idling the 16f jump
                # animation lets the engine place the player exactly on the
                # landing with no fast-gear drift past it. Matches the
                # "release at ramp tile + 36f idle" pattern validated by
                # spike_ramp_poll_release.py.
                axis_offset = 8 if direction in ("left", "right") else 12
                final_coord = (
                    ramp_tile_x if direction in ("left", "right") else ramp_tile_y
                )
                operator = ">=" if (dx + dy) > 0 else "<="
                # Generous max: worst case ~BIKE_HOLD_FRAMES per runway tile
                # + 36f for the last ramp's jump animation. Multiply by 4 for
                # slow-gear-early-tiles tolerance.
                seg_len = seg_end_idx - i + 1
                max_f = max(BIKE_HOLD_FRAMES * seg_len * 4, 180)
                emu.advance_frames_until(
                    max_frames=max_f,
                    conditions=[{
                        "type": "value",
                        "address": _addr("PLAYER_POS_BASE") + axis_offset,
                        "size": "long",
                        "operator": operator,
                        "value": final_coord,
                    }],
                    poll_interval=1,
                    buttons=[direction],
                )
                emu.advance_frames(36)  # let the final ramp jump animate
                new_map, new_x, new_y = _read_position(emu)
                reached = (new_x, new_y) == (seg_fx, seg_fy)
                if reached:
                    steps_taken += seg_len
                    # Clear consumed ramp tiles from tracking so the next
                    # BFS repath (if any) doesn't re-attempt them. We walk
                    # the path from start, detect ramps by dest-tile lookup,
                    # and delete each ramp key we crossed.
                    sim_x, sim_y = old_x, old_y
                    for k in range(i, seg_end_idx + 1):
                        kdx, kdy = _DIR_DELTAS.get(directions[k], (0, 0))
                        dest = (sim_x + kdx, sim_y + kdy)
                        obs_here = obstacle_tiles.get(dest)
                        if obs_here is not None and obs_here.get("type") in BIKE_RAMP_TYPES:
                            obstacle_tiles.pop(dest, None)
                            sim_x += kdx * BIKE_RAMP_JUMP_TILES
                            sim_y += kdy * BIKE_RAMP_JUMP_TILES
                        else:
                            sim_x, sim_y = dest
                    nav_info.setdefault("obstacles_cleared", []).append({
                        "type": "bike_ramp_segment",
                        "tiles": seg_len,
                        "start_x": old_x, "start_y": old_y,
                        "final_x": seg_fx, "final_y": seg_fy,
                    })
                    last_step_was_ramp = True
                    i = seg_end_idx + 1
                    continue
                # Segment didn't land on predicted tile — fall through to
                # the per-tile logic, which will detect blocked + repath.
                last_step_was_ramp = False

        is_ramp_step = (
            pre_obs is not None
            and pre_obs.get("type") in BIKE_RAMP_TYPES
        )
        if is_ramp_step:
            # Bike ramp jump — hold direction until the player steps ONTO the
            # ramp tile (approach + 1), then release. The engine plays out
            # the discrete JumpFartherEast action (4-tile displacement past
            # the ramp) during the subsequent idle, landing the player at
            # ramp+4 = approach+BIKE_RAMP_JUMP_TILES. Holding the button
            # *through* the jump instead causes bike fast-gear to continue
            # past the natural landing (+1 to +4 tiles depending on idle),
            # so we release at ramp entry — the same moment the old fixed-
            # press path released, but with poll-driven entry timing.
            # Empirically (scripts/spike_ramp_poll_release.py on session31
            # save): release at ramp tile + 32+f idle → stable landing at
            # ramp+4 with no drift.
            from renegade_mcp.addresses import addr as _addr
            ramp_dx, ramp_dy = _DIR_DELTAS[direction]
            ramp_x = old_x + ramp_dx
            ramp_y = old_y + ramp_dy
            axis_offset = 8 if direction in ("left", "right") else 12
            ramp_coord = ramp_x if direction in ("left", "right") else ramp_y
            operator = ">=" if (ramp_dx + ramp_dy) > 0 else "<="
            emu.advance_frames_until(
                max_frames=BIKE_HOLD_FRAMES * 3,
                conditions=[{
                    "type": "value",
                    "address": _addr("PLAYER_POS_BASE") + axis_offset,
                    "size": "long",
                    "operator": operator,
                    "value": ramp_coord,
                }],
                poll_interval=1,
                buttons=[direction],
            )
            emu.advance_frames(36)  # covers ~16f jump animation + settle
            last_step_was_ramp = True
        else:
            last_step_was_ramp = False
            if pre_obs is not None and pre_obs.get("type") in BIKE_SLOPE_TYPES:
                # Don't fire step_hold directly into a slope tile. A single
                # press with no running start gets slope-rejected (engine
                # speed-gate); the rejection leaves the bike slightly past
                # the slope boundary and corrupts the subsequent blocked-
                # check, which can mis-classify the step as "succeeded" and
                # skip the slope handler. Let blocked=True propagate so the
                # dedicated slope-traversal branch fires.
                pass
            else:
                # Hold direction until the movement-axis coord changes (or max
                # frames elapse). Including "b" when walking engages Running
                # Shoes (~2x speed outdoors, harmless otherwise). Bike/surf:
                # "b" would toggle bike gear or do nothing useful, so skip it.
                aux = ["b"] if active_hold == HOLD_FRAMES else None
                step_hold(emu, direction, active_hold, aux_buttons=aux)

        new_map, new_x, new_y = _read_position(emu)

        blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map

        if blocked:
            # Check if blocked by a clearable HM obstacle BEFORE slow terrain
            # retries — extra directional presses would interfere with the
            # Rock Smash / Cut / Surf interaction dialogue.
            obs_gx, obs_gy = old_x + dx, old_y + dy
            obs_info = obstacle_tiles.get((obs_gx, obs_gy))
            if obs_info is not None and obs_info["type"] in BIKE_SLOPE_TYPES:
                # Bike slope — needs fast gear + running start, not an HM
                # interaction.  Mount the bicycle first if walking.
                from renegade_mcp.addresses import addr
                cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
                if not cycling:
                    from renegade_mcp.use_item import use_item
                    mount_result = use_item(emu, "Bicycle")
                    if mount_result.get("success"):
                        active_hold = BIKE_HOLD_FRAMES
                        cycling = True

                if cycling:
                    # Count consecutive slope tiles ahead.
                    num_slopes = 0
                    cx, cy = old_x, old_y
                    for j in range(i, len(directions)):
                        sdx, sdy = _DIR_DELTAS[directions[j]]
                        cx, cy = cx + sdx, cy + sdy
                        si = obstacle_tiles.get((cx, cy))
                        if si and si["type"] in BIKE_SLOPE_TYPES:
                            num_slopes += 1
                        else:
                            break

                    final_x, final_y, tiles_moved = _traverse_bike_slope(
                        emu, direction, old_x, old_y, num_slopes,
                    )
                    new_x, new_y = final_x, final_y
                    blocked = (old_x, old_y) == (new_x, new_y)
                    if not blocked:
                        # Remove traversed slope tiles from tracking
                        sx, sy = old_x, old_y
                        for step in range(1, tiles_moved + 1):
                            t = (sx + dx * step, sy + dy * step)
                            obstacle_tiles.pop(t, None)
                        nav_info.setdefault("obstacles_cleared", []).append({
                            "type": "bike_slope",
                            "tiles": num_slopes,
                            "x": obs_gx, "y": obs_gy,
                        })

                        # Slope momentum overshoots the expected landing by 1-3
                        # tiles unpredictably. Dismount and re-BFS from actual
                        # position — walking back a few tiles is more reliable
                        # than trying to predict the landing.
                        if repath_ctx is not None:
                            from renegade_mcp.use_item import use_item
                            use_item(emu, "Bicycle")
                            active_hold = HOLD_FRAMES
                            goal_gx = repath_ctx["grid_ox"] + repath_ctx["goal_x"]
                            goal_gy = repath_ctx["grid_oy"] + repath_ctx["goal_y"]
                            steps_taken += tiles_moved
                            if (new_x, new_y) == (goal_gx, goal_gy):
                                # Slope landed us exactly on target. Done.
                                return False, steps_taken, repaths_used, nav_info
                            new_path = _try_repath(repath_ctx, prev_npcs, new_x, new_y)
                            if new_path is None:
                                # No foot path from landing tile to original
                                # target (e.g. target was on a slope tile, now
                                # impassable without the bike). Surface as
                                # stopped_early so callers can react.
                                nav_info["blocked_at"] = {
                                    "x": new_x, "y": new_y, "step": steps_taken,
                                }
                                nav_info["blocked_reason"] = "post_slope_repath_failed"
                                return True, steps_taken, repaths_used, nav_info
                            repaths_used += 1
                            directions = directions[:i] + new_path
                            continue  # replay loop at same i with new path
                        else:
                            # Manual walking (no repath context) — preserve the
                            # original behavior: skip consumed path steps.
                            extra = tiles_moved - 1
                            if extra > 0:
                                i += extra
                                steps_taken += extra
                    else:
                        # Engine refuses this slope (seen on some ascent
                        # slopes). Surface it as a structured error rather
                        # than stopping silently.
                        nav_info["blocked_reason"] = "bike_slope_traversal_failed"
                        nav_info["bike_slope_position"] = {"x": obs_gx, "y": obs_gy}

            elif obs_info is not None:
                is_surf = obs_info["type"] in SURF_TYPES
                is_multi_tile = obs_info["type"] in MULTI_TILE_HM_TYPES
                cleared = _clear_hm_obstacle(emu, direction, obs_info)

                # For multi-tile HMs (Rock Climb, Waterfall), check position
                # even if dialogue wasn't detected — downstream waterfalls
                # auto-slide the player without an HM prompt, and the A press
                # in _clear_hm_obstacle may have triggered that slide.
                if not cleared and is_multi_tile:
                    new_map, new_x, new_y = _read_position(emu)
                    if (old_x, old_y) != (new_x, new_y) or old_map != new_map:
                        cleared = True  # player moved via auto-slide

                if cleared:
                    obstacle_tiles.pop((obs_gx, obs_gy), None)
                    nav_info.setdefault("obstacles_cleared", []).append({
                        "type": obs_info["type"],
                        "move": obs_info["move"],
                        "x": obs_gx, "y": obs_gy,
                    })
                    if is_surf:
                        # Surf moves the player ONTO the water tile (unlike
                        # Rock Smash/Cut where the obstacle is removed and the
                        # player stays in place). Don't retry the step.
                        new_map, new_x, new_y = _read_position(emu)
                        blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map
                        # Mark surfing state so repath uses water-aware BFS,
                        # and switch to surf hold frames (2x walk speed).
                        if not blocked:
                            active_hold = SURF_HOLD_FRAMES
                            if repath_ctx is not None:
                                repath_ctx["surfing"] = True
                    elif is_multi_tile:
                        # Rock Climb / Waterfall: animation moves the player
                        # through ALL obstacle tiles at once. Read new position
                        # and skip consumed path steps.
                        new_map, new_x, new_y = _read_position(emu)
                        blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map
                        if not blocked:
                            # Count how many tiles the animation traversed
                            tiles_moved = abs(new_x - old_x) + abs(new_y - old_y)
                            # Current step (i) consumed 1 tile; skip additional
                            extra = tiles_moved - 1
                            if extra > 0:
                                i += extra
                                steps_taken += extra
                            # Remove all traversed obstacle tiles from tracking
                            for step in range(1, tiles_moved + 1):
                                t = (old_x + dx * step, old_y + dy * step)
                                obstacle_tiles.pop(t, None)
                            # Waterfall: player stays surfing at surf speed
                            if obs_info["type"] in WATERFALL_TYPES:
                                active_hold = SURF_HOLD_FRAMES
                                if repath_ctx is not None:
                                    repath_ctx["surfing"] = True
                    else:
                        # Rock Smash / Cut: obstacle removed, player stays.
                        # Retry the step — tile should now be passable.
                        emu.advance_frames(active_hold, buttons=[direction])
                        emu.advance_frames(WAIT_FRAMES)
                        new_map, new_x, new_y = _read_position(emu)
                        blocked = (old_x, old_y) == (new_x, new_y) and old_map == new_map

        if blocked and not is_ramp_step:
            # Slow terrain (deep snow, ice) may not complete a step within
            # active_hold + WAIT_FRAMES. Retry with full press cycles —
            # the first press may have only turned the character, or the
            # animation may still be in progress.
            # Skipped for bike ramps: a successful jump already displaced
            # 2 tiles, and a retry would re-press the direction after the
            # landing and step one tile past the landing tile.
            for _ in range(SLOW_TERRAIN_RETRIES):
                emu.advance_frames(active_hold, buttons=[direction])
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

    # All directions executed. The new primitive exits each step on the first
    # pos-change, so the last step's animation can continue briefly after we
    # release input — give it time to settle before checking whether we made
    # it to the goal. For manual walking (no repath_ctx) there's no goal.
    # Exception: bike-ramp final step already settled its own animation; an
    # additional WAIT_FRAMES of idle lets bike momentum drift the player one
    # tile past the landing (empirically: 8f idle → +1 tile drift).
    if repath_ctx is not None:
        if not last_step_was_ramp:
            emu.advance_frames(WAIT_FRAMES)
        goal_gx = repath_ctx["grid_ox"] + repath_ctx["goal_x"]
        goal_gy = repath_ctx["grid_oy"] + repath_ctx["goal_y"]
        _, cur_x, cur_y = _read_position(emu)
        if (cur_x, cur_y) != (goal_gx, goal_gy):
            nav_info["blocked_at"] = {"x": cur_x, "y": cur_y, "step": steps_taken}
            nav_info["blocked_reason"] = "path_exhausted_before_target"
            return True, steps_taken, repaths_used, nav_info

    return False, steps_taken, repaths_used, nav_info


# ── Public API ──

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
    from renegade_mcp.phase_timer import phase

    total_steps = 0
    flee_log: list[dict[str, Any]] = []
    remaining = directions
    hold = _get_move_hold(emu)

    for _ in range(MAX_FLEE_ENCOUNTERS if flee_encounters else 1):
        with phase("nav_execute_path"):
            stopped_early, steps_taken, _, nav_info = _execute_path(emu, remaining, track_npcs=True, hold_frames=hold)
        total_steps += steps_taken

        # Post-navigation: poll for encounter or dialogue (also serves as settle)
        with phase("nav_post_check"):
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


def navigate_to(
    emu: EmulatorClient,
    target_x: int = -1, target_y: int = -1,
    path_choice: str | None = None,
    flee_encounters: bool = False,
    poi: str | None = None,
) -> dict[str, Any]:
    """Pathfind to target tile or POI using BFS. Obstacle-aware with dual pathfinding.

    Two modes:
    - **Coordinate mode**: pass (target_x, target_y) to walk to a specific tile.
    - **POI mode**: pass `poi` — an id from `view_map`'s ``interactibles`` list
      (e.g. ``"obj:5"`` or ``"warp:2"``). The tool resolves the POI from a live
      ``view_map`` call, pathfinds to the POI's ``interaction_x/y``, and
      dispatches the default interaction: step onto warp tiles, face+A for
      NPCs / signs / items / berries.

    Auto-traverses water (Surf), Rock Climb walls, and Waterfall tiles when
    the obstacle path is shorter than the clean path and the party has the
    required move + badge.

    Rock Smash rocks and Cut trees are treated as impassable objects
    (Renegade Platinum has no mandatory Rock Smash/Cut obstacles — see
    CLEARABLE_OBSTACLES in nav_constants.py). Strength boulders likewise go
    to npc_set; the Distortion World puzzle needs manual handling.

    When flee_encounters=True, automatically flees wild encounters and resumes
    navigation. Trainer battles (detected by pre-battle dialogue) are still
    returned to the caller since they can't be fled.

    Args:
        target_x, target_y: Target tile coordinates (coordinate mode).
        path_choice: None (default — evaluate and ask if obstacles involved),
                     "obstacle" (take the path through obstacles),
                     "clean" (take the obstacle-free path).
        flee_encounters: If True, auto-flee wild battles and resume navigation.
        poi: Interactible id (e.g. "obj:5", "warp:2") from ``view_map``
             output. Mutually exclusive with (target_x, target_y).
    """
    has_xy = target_x >= 0 and target_y >= 0
    has_poi = poi is not None
    if has_xy and has_poi:
        return {"error": "Provide (target_x, target_y) OR poi, not both."}
    if not has_xy and not has_poi:
        return {"error": "Provide (target_x, target_y) or poi."}

    if has_poi:
        return _navigate_to_poi(
            emu, poi,  # type: ignore[arg-type]
            path_choice=path_choice,
            flee_encounters=flee_encounters,
        )

    if not flee_encounters:
        return _nav_impl_with_overshoot_retry(
            emu, target_x, target_y, path_choice=path_choice,
        )

    flee_log: list[dict[str, Any]] = []
    original_start: dict[str, Any] | None = None
    for _ in range(MAX_FLEE_ENCOUNTERS):
        result = _nav_impl_with_overshoot_retry(
            emu, target_x, target_y, path_choice=path_choice,
        )
        # Preserve the user-visible start from the first iteration — subsequent
        # retries restart BFS from wherever the interrupt left the player, but
        # the caller wants to know where they were when the call started.
        # (BUG-044: slope overshoot + wild encounter fled, the retry's
        # re-invocation produced a nonsensical `start` from mid-slope.)
        if original_start is None:
            original_start = result.get("start")

        # Only path_choice matters on the first call — after that we're repathing
        path_choice = None

        enc = result.get("encounter")
        if enc is None:
            # No encounter — navigation completed (or hit a non-encounter stop)
            break

        if enc.get("encounter") != "battle":
            break

        if enc.get("dialogue"):
            # Trainer battle: pre-battle dialogue present → can't flee.
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

    if original_start is not None:
        result["start"] = original_start

    return result


def _navigate_to_poi(
    emu: EmulatorClient, poi_id: str,
    path_choice: str | None = None,
    flee_encounters: bool = False,
) -> dict[str, Any]:
    """Resolve a POI from live view_map and dispatch the default interaction.

    Warps: pathfind onto the interaction tile (the existing warp-step handling
    in _navigate_to_impl activates the transition).
    NPCs / signs / items / berries: hand off to interact_with with the POI's
    object_index so the standard face+A flow runs.
    """
    # Lazy import — view_map lives in map_state, which also imports from this
    # module transitively; keep it local to avoid circular-import surprises.
    from renegade_mcp.map_state import view_map

    vmap = view_map(emu)
    if "error" in vmap:
        return {"error": f"Could not resolve POI '{poi_id}': {vmap['error']}"}

    all_entries = (
        vmap.get("interactibles", []) + vmap.get("unreachable_interactibles", [])
    )
    entry = next((e for e in all_entries if e.get("id") == poi_id), None)
    if entry is None:
        return {
            "error": f"POI '{poi_id}' not found in current map",
            "available_ids": [e["id"] for e in all_entries],
        }

    if "steps" not in entry:
        # Present in unreachable list — surface the reason so the caller
        # can decide whether to move closer or pick a different target.
        return {
            "error": (
                f"POI '{poi_id}' ({entry.get('label')}) is not currently "
                f"reachable (Manhattan distance {entry.get('distance', '?')})."
            ),
            "poi": entry,
        }

    resolved = {
        "id": poi_id,
        "kind": entry["kind"],
        "x": entry["x"], "y": entry["y"],
        "label": entry.get("label"),
    }

    if entry["kind"] == "warp":
        ix, iy = entry["interaction_x"], entry["interaction_y"]
        result = navigate_to(
            emu, ix, iy,
            path_choice=path_choice, flee_encounters=flee_encounters,
        )
        result["poi_resolved"] = resolved
        return result

    # Object-style interaction — hand off to interact_with.
    obj_idx = entry.get("preview", {}).get("object_index")
    if obj_idx is None:
        return {
            "error": f"POI '{poi_id}' has kind={entry['kind']!r} but no object_index",
            "poi": entry,
        }

    from renegade_mcp.interaction import interact_with
    result = interact_with(emu, object_index=obj_idx, flee_encounters=flee_encounters)
    result["poi_resolved"] = resolved
    return result


def _nav_impl_with_overshoot_retry(
    emu: EmulatorClient, target_x: int, target_y: int,
    path_choice: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Call `_navigate_to_impl`; if it finishes short of target because the
    plan ran out (`path_exhausted_before_target`), re-BFS from the current
    position and retry up to ``max_retries`` times.

    Motivation: bike-bridge traversal leaves the player on a bike with a
    few tiles of fast-gear coasting momentum; the dismount menu takes
    long enough that the player can drift past the planned final tile.
    Rather than tune the coasting out (fragile), we just repath on foot
    from wherever we ended up. Covers any future "plan-followed-exactly-
    but-engine-carried-us-further" case without specializing on bikes.

    ``path_choice`` is only honored on the first attempt — subsequent
    retries are treated as repaths and should not re-ask the user.
    """
    result = _navigate_to_impl(emu, target_x, target_y, path_choice=path_choice)
    attempts_used = 0
    while (
        attempts_used < max_retries
        and result.get("stopped_early")
        and result.get("blocked_reason") == "path_exhausted_before_target"
    ):
        final = result.get("final") or {}
        if final.get("x") == target_x and final.get("y") == target_y:
            break  # already there — no-op
        # Re-BFS from current position. Drop path_choice so the retry
        # doesn't trip the "obstacle path requires choice" prompt.
        retry_result = _navigate_to_impl(
            emu, target_x, target_y, path_choice=None,
        )
        # Preserve the original start position — otherwise successive retries
        # would shadow the caller's "where did we begin" expectation.
        if "start" in result:
            retry_result["start"] = result["start"]
        # Sum step counts across retries so the caller sees total movement.
        retry_result["steps"] = result.get("steps", 0) + retry_result.get("steps", 0)
        result = retry_result
        attempts_used += 1
    if attempts_used > 0:
        result["overshoot_repaths"] = attempts_used
    return result


def _navigate_to_impl(
    emu: EmulatorClient, target_x: int, target_y: int,
    path_choice: str | None = None,
    hold_frames: int | None = None,
) -> dict[str, Any]:
    """Core navigate_to logic. See navigate_to() for the public API."""
    from renegade_mcp.phase_timer import phase

    if hold_frames is None:
        hold_frames = _get_move_hold(emu)

    # Cycling road dispatch — forced downhill slide requires special movement
    if is_on_cycling_road(emu, target_x, target_y):
        return _navigate_cycling_road(emu, target_x, target_y)

    with phase("nav_read_map_state"):
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
    elevation_for_validation = None
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
        with phase("nav_bfs_3d"):
            path_3d = _bfs_pathfind_3d(
                terrain_info, combined_npc_set, elevation,
                bfs_sx, bfs_sy, bfs_tx, bfs_ty,
                player_level, width=bfs_w, height=bfs_h,
            )

        if path_3d is None:
            # Fall back to 2D BFS (still needed for HM-obstacle crossings),
            # but retain the elevation data so we can reject paths that
            # cross layers (bridge ↔ under-bridge ground).
            is_3d = False
            elevation_for_validation = elevation
            elevation = None
            repath_ctx.pop("elevation", None)
            repath_ctx.pop("emu", None)

    # Defaults for 2D BFS variables (may not be set in 3D path)
    obs_path = None
    obs_crossed: list[dict] = []

    if is_3d:
        path = path_3d
        field_moves = _get_field_move_availability(emu)
        if path is not None:
            obs_path_3d, obs_crossed_3d = _bfs_pathfind_obstacles(
                terrain_info, npc_set, obstacle_map,
                bfs_sx, bfs_sy, bfs_tx, bfs_ty,
                field_moves, width=bfs_w, height=bfs_h,
            )
            obs_crossed_3d = _dedupe_obstacles(obs_crossed_3d)
            all_auto = all(ob["type"] in AUTO_NAVIGATE_TYPES for ob in obs_crossed_3d)
            if (obs_path_3d is not None and obs_crossed_3d
                    and len(obs_path_3d) < len(path) and all_auto):
                skills_ok = all(field_moves.get(ob["move"], False) for ob in obs_crossed_3d)
                if skills_ok:
                    path = obs_path_3d
                    obs_path = obs_path_3d
                    obs_crossed = obs_crossed_3d
    else:
        # ── Dual BFS: clean path vs obstacle path ──
        with phase("nav_bfs_2d"):
            clean_path = _bfs_pathfind(
                terrain_info, npc_set | set(obstacle_map.keys()),
                bfs_sx, bfs_sy, bfs_tx, bfs_ty, width=bfs_w, height=bfs_h,
            )

        field_moves = _get_field_move_availability(emu)
        with phase("nav_bfs_obstacle"):
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

        skills_available = True
        if has_obs:
            for ob in obs_crossed:
                if not field_moves.get(ob["move"], False):
                    skills_available = False
                    break

        auto_obs = [ob for ob in obs_crossed if ob["type"] in AUTO_NAVIGATE_TYPES]
        manual_obs = [ob for ob in obs_crossed if ob["type"] not in AUTO_NAVIGATE_TYPES]
        all_auto = len(manual_obs) == 0 and len(auto_obs) > 0

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
        elif has_obs and obs_shorter and skills_available and all_auto and path_choice is None:
            path = obs_path
        elif has_obs and obs_shorter and skills_available and not all_auto and path_choice is None:
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
            missing = [ob["move"] for ob in obs_crossed if not field_moves.get(ob["move"], False)]
            return {
                "error": f"No path found. An obstacle path exists but requires: {set(missing)}",
                "start": _pos_with_map(px, py, map_id),
                "target": {"x": target_x, "y": target_y},
            }
        else:
            path = clean_path

    # Reject 2D-fallback paths that cross elevation layers (e.g. bridge over
    # ground). HM-obstacle paths — Surf, Rock Climb, Waterfall — are exempt
    # because they legitimately cross layers as part of their traversal.
    path_uses_hm_crossing = (
        obs_path is not None and path is obs_path
        and any(ob["type"] in AUTO_NAVIGATE_TYPES for ob in obs_crossed)
    )
    if (
        elevation_for_validation is not None
        and path is not None
        and path_3d is None
        and not path_uses_hm_crossing
        and not _validate_path_elevation(
            path, elevation_for_validation, bfs_sx, bfs_sy, player_level,
        )
    ):
        manhattan = abs(bfs_tx - bfs_sx) + abs(bfs_ty - bfs_sy)
        result: dict[str, Any] = {
            "error": (
                f"No reasonable path at your current elevation "
                f"(level {player_level}).  The 2D fallback would step "
                "between incompatible layers.  Try a ramp or warp first, "
                "or use `navigate` with explicit directions."
            ),
            "start": _pos_with_map(px, py, map_id),
            "target": {"x": target_x, "y": target_y},
            "player_level": player_level,
            "manhattan": manhattan,
        }
        _attach_warp_hint(result, terrain_info, bfs_sx, bfs_sy)
        return result

    # ── Check if target tile is a door/warp ──
    target_behavior = None
    tx_l = bfs_tx if (is_global and chunked) else target_x
    ty_l = bfs_ty if (is_global and chunked) else target_y
    if 0 <= ty_l < len(terrain_info) and 0 <= tx_l < len(terrain_info[0]):
        _, target_behavior = terrain_info[ty_l][tx_l]

    is_door = target_behavior in DOOR_ACTIVATION or target_behavior in DIRECTIONAL_WARP

    start_pos = _pos_with_map(px, py, map_id)

    # BUG-024 length guard removed 2026-04-22 session 29 — the Cycling Road
    # gate-house scenario it was meant to catch is now rejected earlier by
    # the BUG-030 elevation validator (incompatible-layer 2D fallback gets
    # a specific "trigger the warp" message). The length guard was biting
    # legitimate long winding dungeon paths (Wayward Cave 100-step, 17
    # Manhattan) as false positives.

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

    # Build obstacle tile lookup for _execute_path (auto-navigable obstacles).
    exec_obstacle_tiles: dict[tuple[int, int], dict] = {}
    if obs_crossed and path is obs_path:
        for ob in obs_crossed:
            if ob["type"] in AUTO_NAVIGATE_TYPES:
                if "global_x" in ob:
                    gx, gy = ob["global_x"], ob["global_y"]
                else:
                    gx = ob["x"] + repath_ox
                    gy = ob["y"] + repath_oy
                exec_obstacle_tiles[(gx, gy)] = ob

    # Scan the chosen path for bike slope and bike ramp tiles. Bike ramps
    # (0xD7/0xD8) appear in the path as a single direction step representing
    # a fast-gear jump — the ramp tile itself is impassable and never
    # "walked" onto, so the scanner must detect the ramp on the NEXT tile in
    # direction and advance the position tracker by BIKE_RAMP_JUMP_TILES
    # (landing = approach + 5 = ramp + 4 in the ramp direction).
    if path and terrain_info:
        sx, sy = bfs_sx, bfs_sy
        for step_dir in path:
            sdx, sdy = _DIR_DELTAS.get(step_dir, (0, 0))
            nx, ny = sx + sdx, sy + sdy
            is_ramp = False
            if 0 <= ny < len(terrain_info) and 0 <= nx < len(terrain_info[ny]):
                _, nbeh = terrain_info[ny][nx]
                if (nbeh in BIKE_RAMP_BEHAVIORS
                        and BIKE_RAMP_DIRECTIONS[nbeh] == step_dir):
                    is_ramp = True
                    gx, gy = nx + repath_ox, ny + repath_oy
                    if (gx, gy) not in exec_obstacle_tiles:
                        exec_obstacle_tiles[(gx, gy)] = {
                            "type": "bike_ramp",
                            "behavior": nbeh,
                        }
            if is_ramp:
                # Advance to landing: approach (sx, sy) + JUMP_TILES * dir.
                sx = sx + sdx * BIKE_RAMP_JUMP_TILES
                sy = sy + sdy * BIKE_RAMP_JUMP_TILES
                continue
            sx, sy = nx, ny
            if 0 <= sy < len(terrain_info) and 0 <= sx < len(terrain_info[sy]):
                _passable, beh = terrain_info[sy][sx]
                if beh in BIKE_SLOPE_BEHAVIORS:
                    gx, gy = sx + repath_ox, sy + repath_oy
                    if (gx, gy) not in exec_obstacle_tiles:
                        exec_obstacle_tiles[(gx, gy)] = {
                            "type": "bike_slope",
                            "behavior": beh,
                        }

    # Provide field_moves + obstacle_map for repath during Surf navigation.
    repath_ctx["field_moves"] = field_moves
    repath_ctx["obstacle_map"] = obstacle_map

    with phase("nav_execute_path"):
        stopped_early, steps_taken, repaths_used, nav_info = _execute_path(
            emu, path, repath_ctx=repath_ctx, hold_frames=hold_frames,
            obstacle_tiles=exec_obstacle_tiles,
        )
    path_str = _summarize_path(path)

    # Door target but couldn't reach it
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
            emu.advance_frames(SETTLE_FRAMES)
            final_map, final_x, final_y = _read_position(emu)
            return {
                "path": path_str,
                "steps": steps_taken,
                "start": start_pos,
                "final": _pos_with_map(final_x, final_y, final_map),
                "door_entered": True,
            }

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
    # (nav was aiming at the door-adjacent tile and the user probably wants to
    # actually step through). Skip this when the caller asked for a specific
    # non-door tile and we're already on it — otherwise we'd shove the player
    # off their intended target by pressing into an unrelated nearby warp.
    adj_warp_failed: dict[str, Any] | None = None
    cur_map, cur_x, cur_y = _read_position(emu)
    goal_gx = repath_ctx["grid_ox"] + repath_ctx["goal_x"]
    goal_gy = repath_ctx["grid_oy"] + repath_ctx["goal_y"]
    at_target = (cur_x, cur_y) == (goal_gx, goal_gy)
    if not is_door and not stopped_early and not at_target:
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
    with phase("nav_post_nav_check"):
        encounter = _post_nav_check(emu)
    final_map, final_x, final_y = _read_position(emu)

    result = {
        "path": path_str,
        "steps": steps_taken,
        "start": start_pos,
        "final": _pos_with_map(final_x, final_y, final_map),
    }

    if nav_info.get("obstacles_cleared"):
        result["obstacles_cleared"] = nav_info["obstacles_cleared"]

    if stopped_early:
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
