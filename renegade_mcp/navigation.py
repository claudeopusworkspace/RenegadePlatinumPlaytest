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
    BIKE_SLOPE_BACKUP_TILES,
    BIKE_SLOPE_BEHAVIORS,
    BIKE_SLOPE_MAX_FRAMES,
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
    """Mount the bicycle if not already on it. Returns True on success."""
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    if bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")):
        return True
    mount = use_item(emu, "Bicycle")
    return bool(mount.get("success"))


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

    steps_taken = 0
    repaths_used = 0
    npc_move_count = 0
    map_changed = False
    prev_npcs = _read_npc_positions(emu) if track_npcs else {}
    nav_info: dict = {}
    active_hold = hold_frames  # may change to SURF_HOLD_FRAMES after Surf activation

    i = 0
    while i < len(directions):
        direction = directions[i]
        old_map, old_x, old_y = _read_position(emu)
        dx, dy = _DIR_DELTAS.get(direction, (0, 0))

        # Pre-step: if the next tile is a bike slope and we're walking,
        # mount the bicycle first.  Stepping onto a slope on foot registers
        # as a successful step (position briefly changes) before the game's
        # slope physics slides the player back south, so the post-step
        # `blocked` check never catches this case — the player oscillates.
        # Once on the bike, stepping into a slope IS blocked, which routes
        # through the existing blocked-branch slope traversal below.
        pre_target = (old_x + dx, old_y + dy)
        pre_obs = obstacle_tiles.get(pre_target)
        if pre_obs is not None and pre_obs.get("type") in BIKE_SLOPE_TYPES:
            from renegade_mcp.addresses import addr as _addr
            on_bike = bool(emu.read_memory(_addr("CYCLING_GEAR_ADDR"), size="short"))
            if not on_bike:
                if not _auto_mount_for_slope(emu):
                    nav_info["blocked_at"] = {"x": old_x, "y": old_y, "step": steps_taken}
                    nav_info["blocked_reason"] = "bike_slope_requires_bicycle"
                    nav_info["note"] = (
                        f"Bike slope at ({pre_target[0]}, {pre_target[1]}) "
                        f"requires the Bicycle key item.  Get the Bicycle "
                        f"and retry."
                    )
                    return True, steps_taken, repaths_used, nav_info
                active_hold = BIKE_HOLD_FRAMES

        emu.advance_frames(active_hold, buttons=[direction])
        emu.advance_frames(WAIT_FRAMES)

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
                        # Skip consumed path steps (current step + extras)
                        extra = tiles_moved - 1
                        if extra > 0:
                            i += extra
                            steps_taken += extra
                        nav_info.setdefault("obstacles_cleared", []).append({
                            "type": "bike_slope",
                            "tiles": num_slopes,
                            "x": obs_gx, "y": obs_gy,
                        })

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

        if blocked:
            # Slow terrain (deep snow, ice) may not complete a step within
            # active_hold + WAIT_FRAMES. Retry with full press cycles —
            # the first press may have only turned the character, or the
            # animation may still be in progress.
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
    emu: EmulatorClient, target_x: int, target_y: int,
    path_choice: str | None = None,
    flee_encounters: bool = False,
) -> dict[str, Any]:
    """Pathfind to target tile using BFS. Obstacle-aware with dual pathfinding.

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
            is_3d = False
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

    # ── Check if target tile is a door/warp ──
    target_behavior = None
    tx_l = bfs_tx if (is_global and chunked) else target_x
    ty_l = bfs_ty if (is_global and chunked) else target_y
    if 0 <= ty_l < len(terrain_info) and 0 <= tx_l < len(terrain_info[0]):
        _, target_behavior = terrain_info[ty_l][tx_l]

    is_door = target_behavior in DOOR_ACTIVATION or target_behavior in DIRECTIONAL_WARP

    start_pos = _pos_with_map(px, py, map_id)

    # ── Sanity cap: reject absurdly long paths vs manhattan distance ──
    # When player is on a side-warp cluster (gate house, Cycling Road), BFS
    # can find a technically valid path that loops all the way around the
    # overworld to reach the other side of the gate.  The correct action is
    # to trigger the warp, not walk 93 tiles for a 7-tile trip.
    # Exception: when the chosen path traverses an HM tile (Rock Climb
    # descent, Surf, Waterfall), the path legitimately can be long because
    # the player is in a region whose only exits are HM tiles.  Skip the
    # cap in that case.
    path_uses_hm = (
        obs_path is not None and path is obs_path
        and any(ob["type"] in AUTO_NAVIGATE_TYPES for ob in obs_crossed)
    )
    if path is not None and len(path) > 0 and not path_uses_hm:
        manhattan = abs(bfs_tx - bfs_sx) + abs(bfs_ty - bfs_sy)
        limit = max(manhattan * 5, manhattan + 30)
        if len(path) > limit:
            # Check if the player is currently standing on a directional warp
            # tile — if so, they almost certainly want to trigger it.
            on_warp_dir = None
            if 0 <= bfs_sy < len(terrain_info) and 0 <= bfs_sx < len(terrain_info[0]):
                _, start_behavior = terrain_info[bfs_sy][bfs_sx]
                on_warp_dir = DIRECTIONAL_WARP.get(start_behavior)
            target_gx = bfs_tx + repath_ox
            target_gy = bfs_ty + repath_oy
            result: dict[str, Any] = {
                "error": (
                    f"No reasonable path to ({target_gx}, {target_gy}): "
                    f"BFS path is {len(path)} steps for a {manhattan}-tile "
                    f"Manhattan distance.  Target is likely in a separate "
                    f"walkable region reachable only via warp."
                ),
                "start": start_pos,
                "target": {"x": target_x, "y": target_y},
                "path_length": len(path),
                "manhattan": manhattan,
            }
            if on_warp_dir is not None:
                result["note"] = (
                    f"You are standing on a directional warp tile.  "
                    f"Trigger it with `press_buttons(['{on_warp_dir}'])` "
                    f"to transition, then navigate from the other side."
                )
            return result

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

    # Scan the chosen path for bike slope tiles
    if path and terrain_info:
        sx, sy = bfs_sx, bfs_sy
        for step_dir in path:
            sdx, sdy = _DIR_DELTAS.get(step_dir, (0, 0))
            sx, sy = sx + sdx, sy + sdy
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
