"""Cycling road bridge movement and bike slope traversal.

Handles Route 206's auto-slide bridge tiles (0x71) and bike slope tiles
(0xD9/0xDA) that require fast gear + running start.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.nav_constants import (
    _DIR_DELTAS,
    _OPPOSITE_DIR,
    BIKE_HOLD_FRAMES,
    BIKE_SLOPE_BACKUP_TILES,
    BIKE_SLOPE_MAX_FRAMES,
    CYCLING_ROAD_MAX_WAIT,
    CYCLING_ROAD_POLL_INTERVAL,
    WAIT_FRAMES,
    _pos_with_map,
    _read_position,
)
from renegade_mcp.battle import read_battle
from renegade_mcp.dialogue import (
    CTX_RUNNING, CTX_WAITING,
    _find_script_manager, _read_context_state, _read_script_state,
    read_dialogue,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def _check_encounter_quick(emu: EmulatorClient) -> dict[str, Any] | None:
    """Lightweight encounter check for use during cycling road movement.

    Checks read_battle (trainer/wild) and dialogue (trainer spotted, sign, etc.).
    Returns encounter dict if detected, None otherwise. Does NOT advance frames.
    """
    battlers = read_battle(emu)
    if battlers:
        return {"encounter": "battle_detected", "battlers": battlers}

    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] != "none":
        mgr = _find_script_manager(emu)
        if mgr is not None:
            ss = _read_script_state(emu, mgr)
            if ss["is_msg_box_open"]:
                return {"encounter": "dialogue_detected", "dialogue": dialogue}
            # Script running but msgBox not open yet — trainer approach animation
            if ss["ctx0_ptr"]:
                ctx0 = _read_context_state(emu, ss["ctx0_ptr"])
                if ctx0["state"] in (CTX_RUNNING, CTX_WAITING):
                    return {"encounter": "script_running"}
    return None


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

    Encounter detection runs after every movement phase. Trainer battles (pre-battle
    dialogue) and wild encounters are caught and returned immediately.
    """
    # Lazy import to avoid circular dependency
    from renegade_mcp.nav_events import _post_nav_check

    start_map, start_x, start_y = _read_position(emu)
    cur_x, cur_y = start_x, start_y
    steps_log: list[str] = []
    total_frames = 0
    encounter: dict[str, Any] | None = None
    max_iters = 200
    no_progress = 0
    last_pos = (cur_x, cur_y)

    for _ in range(max_iters):
        if cur_x == target_x and cur_y == target_y:
            break

        # General stuck detection: bail after 3 consecutive no-progress iterations
        if (cur_x, cur_y) == last_pos:
            no_progress += 1
            if no_progress >= 3:
                break
        else:
            no_progress = 0
        last_pos = (cur_x, cur_y)

        dx = target_x - cur_x
        dy = target_y - cur_y
        behavior = _get_current_tile_behavior(emu)
        on_bridge = (behavior == 0x71)

        # ── Phase: Normal ground movement (not on bridge body) ──
        if not on_bridge:
            if dy > 0:
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

            # Encounter check after ground step
            enc = _check_encounter_quick(emu)
            if enc is not None:
                encounter = _post_nav_check(emu)
                break
            continue

        # ── Phase: On bridge body — uphill first (before lateral) ──
        if dy < 0:
            wait = 0
            phase_start_y = cur_y
            while cur_y > target_y and wait < CYCLING_ROAD_MAX_WAIT:
                emu.advance_frames(4, buttons=["up"])
                wait += 4
                total_frames += 4
                _, new_x, new_y = _read_position(emu)
                if new_y != cur_y:
                    steps_log.append(f"up ({cur_x},{cur_y})→({new_x},{new_y})")
                    cur_x, cur_y = new_x, new_y
                # Encounter check during uphill
                enc = _check_encounter_quick(emu)
                if enc is not None:
                    encounter = _post_nav_check(emu)
                    break
            if encounter is not None:
                break
            if cur_y == phase_start_y:
                break  # No uphill progress — stuck (NPC or wall blocking)
            continue

        # ── Phase: On bridge body — lateral moves ──
        if dx != 0:
            btn = "left" if dx < 0 else "right"
            emu.advance_frames(4, buttons=[btn])
            total_frames += 4
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

            # Encounter check after lateral step
            enc = _check_encounter_quick(emu)
            if enc is not None:
                encounter = _post_nav_check(emu)
                break
            continue

        # ── Phase: On bridge body — southbound (auto-slide) ──
        if dy > 0:
            wait = 0
            phase_start_y = cur_y
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
                # Encounter check during slide — position may stall if trainer
                # spotted us (approach animation freezes player movement)
                enc = _check_encounter_quick(emu)
                if enc is not None:
                    encounter = _post_nav_check(emu)
                    break
            if encounter is not None:
                break
            if cur_y == phase_start_y:
                break  # No slide progress — stuck (NPC or wall blocking)
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
    if encounter is not None:
        result["encounter"] = encounter
    if not reached and encounter is None:
        result["note"] = (
            f"Stopped at ({final_x},{final_y}), target was ({target_x},{target_y}). "
            f"Possible obstacle (trainer NPC, wall, or end of bridge)."
        )
    return result


def _traverse_bike_slope(
    emu: EmulatorClient,
    direction: str,
    old_x: int, old_y: int,
    num_slope_tiles: int,
) -> tuple[int, int, int]:
    """Traverse bike slope tiles using fast gear and a running start.

    The game engine blocks single-step entry onto slope tiles.  To cross:
    1. Switch to fast gear (press B if in slow gear)
    2. Back up 3 tiles (opposite direction) to build momentum space
    3. Hold *direction* continuously until past all slope tiles
    4. Restore original gear

    Args:
        direction: Direction of travel through the slope.
        old_x, old_y: Player position immediately before the first slope tile.
        num_slope_tiles: Consecutive slope tiles to cross (usually 2).

    Returns:
        (final_x, final_y, tiles_moved) where tiles_moved is the distance
        from old_x/old_y to the final position (includes the slope tiles).
    """
    from renegade_mcp.use_item import _set_bike_gear

    opp = _OPPOSITE_DIR[direction]
    dx, dy = _DIR_DELTAS[direction]

    # ── 1. Ensure fast gear (the authoritative gate for slope climb).
    # Earlier versions did a paranoid dismount+remount here that cost ~800f
    # per call without fixing anything — it was papering over a gear-address
    # misdiagnosis (BUG-046). With BIKE_GEAR_STATE_ADDR at PPB+0x8c and
    # `_set_bike_gear` handling the byte-inversion internally, calling
    # `_set_bike_gear(emu, 0)` (decomp semantic 0=fast) reliably B-presses
    # when needed and is a no-op when already fast.
    _set_bike_gear(emu, 0)

    # ── 2. Back up for running start. The engine's slope gate checks
    # PlayerAvatar.Speed >= 3 — fast-gear bike reaches that within ~3 tiles
    # of continuous hold.
    for _ in range(BIKE_SLOPE_BACKUP_TILES):
        emu.advance_frames(BIKE_HOLD_FRAMES, buttons=[opp])
        emu.advance_frames(WAIT_FRAMES)

    # ── 3. Continuous hold through the slope ──
    # Fine-grained 2-frame polling from the backed-up position all the way
    # through the slope.  Fast gear moves ~2-3 f/tile, so coarser polling
    # causes multi-tile overshoot.  Stop once we've moved past all slope
    # tiles (fwd > num_slope_tiles, measured from old_x/old_y).
    frames_used = 0
    last_pos = None
    stall_frames = 0
    while frames_used < BIKE_SLOPE_MAX_FRAMES:
        emu.advance_frames(2, buttons=[direction])
        frames_used += 2
        _, nx, ny = _read_position(emu)

        fwd = (nx - old_x) * dx + (ny - old_y) * dy
        if fwd > num_slope_tiles:
            break  # just past the last slope tile

        # Stuck detection: bail if position unchanged for 40+ frames
        if (nx, ny) == last_pos:
            stall_frames += 2
            if stall_frames >= 40:
                break
        else:
            stall_frames = 0
        last_pos = (nx, ny)

    # ── 3b. Cancel fast gear and drain momentum ──
    # Drop to slow gear (byte=1) so the bike stops auto-advancing, then
    # idle for 120 frames (~2 sec) to fully drain the game engine's
    # internal momentum counter.  Shorter settle periods look stable but
    # the bike resumes drifting when subsequent code advances frames
    # (e.g. the 300-frame post-navigation encounter poll).
    _set_bike_gear(emu, 1)
    emu.advance_frames(120)

    _, final_x, final_y = _read_position(emu)
    tiles_moved = abs(final_x - old_x) + abs(final_y - old_y)
    return final_x, final_y, tiles_moved
