"""NPC and object interaction logic.

Handles navigating to NPCs/objects, facing them, pressing A,
and processing the resulting dialogue or battle encounters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.nav_constants import (
    _ADJACENT_OFFSETS,
    _DELTA_TO_FACE,
    _FACE_TO_INT,
    _INTERACT_COOLDOWN,
    _MOVING_NPC_POLL,
    _MOVING_NPC_TIMEOUT,
    HOLD_FRAMES,
    INTERACT_A_WAIT,
    INTERACT_DIALOGUE_WAIT,
    POST_BATTLE_SETTLE,
    SETTLE_FRAMES,
    WAIT_FRAMES,
    _get_move_hold,
    _pos_with_map,
    _summarize_path,
)
from renegade_mcp.battle import read_battle
from renegade_mcp.dialogue import (
    CTX_RUNNING, CTX_WAITING,
    _find_script_manager, _read_context_state, _read_script_state,
    advance_dialogue, read_dialogue,
)
from renegade_mcp.map_state import (
    SIGN_GFX_IDS,
    get_map_state,
    read_objects,
    read_player_state,
    read_sign_tiles_from_rom,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


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
    # Lazy import to avoid circular dependency
    from renegade_mcp.nav_events import _post_nav_check

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
    # Lazy imports to avoid circular dependencies
    from renegade_mcp.nav_events import _post_nav_check, _try_flee_encounter
    from renegade_mcp.navigation import navigate_to
    from renegade_mcp.pathfinding import _bfs_pathfind, _build_multi_chunk_terrain, _build_terrain_info

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
        # Lazy import to avoid circular dependency
        from renegade_mcp.navigation import _execute_path

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
