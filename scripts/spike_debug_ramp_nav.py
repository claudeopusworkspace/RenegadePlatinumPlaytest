"""Step-by-step diagnostic for navigate_to on the Wayward Cave bike-ramp chain.

Load `bug_bike_ramps_repel` (player on bike at (7,22), Repel active), run
navigate_to to the east-chamber Pokéball at (31,16), and print exhaustive
per-step evidence:

  • BFS planned path (direction sequence)
  • Planned tile trajectory (what BFS thinks the player should visit)
  • Per-step EXECUTED event log: directions pressed, advance_frames_until
    return values, position before/after, cycling gear, repaths triggered
  • Final navigate_to result + position

No modifications to production code — we monkey-patch `emu.advance_frames`,
`emu.advance_frames_until`, and `nav_constants.step_hold` (via the
`renegade_mcp.navigation` namespace that imported it) inside this script only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp import navigation, nav_constants, pathfinding  # noqa: E402
from renegade_mcp.map_state import get_map_state  # noqa: E402
from renegade_mcp.navigation import navigate_to as _navigate_to  # noqa: E402
from helpers import do_load_state  # noqa: E402

SAVE = "bug_bike_ramps_repel"
SOCK = ".melonds_bridge.sock"
TARGET = (31, 17)  # interaction tile for Pokeball at (31, 16)


def _pos(emu):
    base = addresses.addr("PLAYER_POS_BASE")
    x = emu.read_memory(base + 8, size="long")
    y = emu.read_memory(base + 12, size="long")
    return x, y


def _on_bike(emu):
    return bool(emu.read_memory(addresses.addr("CYCLING_GEAR_ADDR"), size="short"))


def _gear(emu):
    from renegade_mcp.addresses import BIKE_GEAR_STATE_ADDR
    return emu.read_memory(BIKE_GEAR_STATE_ADDR, size="byte")


def dump_bfs_plan(emu):
    """Extract the BFS plan without executing it."""
    state = get_map_state(emu)
    map_id = state["map_id"]
    px, py = state["px"], state["py"]
    tx, ty = TARGET

    mc = pathfinding._build_multi_chunk_terrain(emu, map_id, px, py, tx, ty)
    if mc is None:
        print("ERROR: could not build terrain")
        return None
    terrain_info, grid_ox, grid_oy, grid_w, grid_h = mc

    npc_set, obstacle_map = navigation._classify_objects_for_grid(
        state["objects"], grid_ox, grid_oy, grid_w, grid_h,
    )

    bfs_sx, bfs_sy = px - grid_ox, py - grid_oy
    bfs_tx, bfs_ty = tx - grid_ox, ty - grid_oy

    elevation = pathfinding._build_multi_chunk_elevation(
        emu, map_id, terrain_info, grid_ox, grid_oy, grid_w, grid_h,
    )
    player_level = None
    if elevation is not None:
        from renegade_mcp.pathfinding import _height_to_level
        from renegade_mcp.map_state import read_player_height
        player_level = _height_to_level(
            read_player_height(emu), elevation,
            tile_x=bfs_sx, tile_y=bfs_sy,
        )

    print(f"\n== BFS Setup ==")
    print(f"  player global = ({px}, {py}) → target global = ({tx}, {ty})")
    print(f"  grid origin = ({grid_ox}, {grid_oy})  size = {grid_w}x{grid_h}")
    print(f"  bfs_s = ({bfs_sx}, {bfs_sy})  bfs_t = ({bfs_tx}, {bfs_ty})")
    print(f"  player_level = {player_level}  (3D = {elevation is not None})")

    path_3d = None
    if elevation is not None and player_level is not None:
        path_3d = pathfinding._bfs_pathfind_3d(
            terrain_info, npc_set | set(obstacle_map.keys()), elevation,
            bfs_sx, bfs_sy, bfs_tx, bfs_ty,
            player_level, width=grid_w, height=grid_h,
        )

    clean = pathfinding._bfs_pathfind(
        terrain_info, npc_set | set(obstacle_map.keys()),
        bfs_sx, bfs_sy, bfs_tx, bfs_ty, width=grid_w, height=grid_h,
    )

    print(f"\n== BFS Plan ==")
    print(f"  3D path: {path_3d!r}  (len={len(path_3d) if path_3d else 0})")
    print(f"  2D path: {clean!r}  (len={len(clean) if clean else 0})")

    # Walk the 3D plan through BFS momentum model to verify expected tile
    # trajectory — helps compare against actual executed positions later.
    if path_3d:
        print(f"\n== Expected tile trajectory (3D plan, ramp-aware) ==")
        cx, cy = bfs_sx, bfs_sy
        last_dir = None
        momentum = 0
        for i, d in enumerate(path_3d):
            dx, dy = nav_constants._DIR_DELTAS[d]
            nx, ny = cx + dx, cy + dy
            # Check for ramp
            from renegade_mcp.nav_constants import (
                BIKE_RAMP_BEHAVIORS, BIKE_RAMP_DIRECTIONS,
            )
            is_ramp_entry = False
            if 0 <= ny < len(terrain_info) and 0 <= nx < len(terrain_info[ny]):
                _, beh = terrain_info[ny][nx]
                if beh in BIKE_RAMP_BEHAVIORS and BIKE_RAMP_DIRECTIONS[beh] == d:
                    is_ramp_entry = True
            if is_ramp_entry:
                landing_x = cx + dx * 5  # BIKE_RAMP_JUMP_TILES
                landing_y = cy + dy * 5
                g_landing = (landing_x + grid_ox, landing_y + grid_oy)
                print(f"  step {i:2d} {d:>5} RAMP enters ({nx+grid_ox},{ny+grid_oy}) → lands at {g_landing}")
                cx, cy = landing_x, landing_y
                momentum = 4  # RUNWAY after ramp
                last_dir = d
            else:
                g = (nx + grid_ox, ny + grid_oy)
                if d == last_dir:
                    momentum = min(momentum + 1, 4)
                else:
                    momentum = 1
                last_dir = d
                print(f"  step {i:2d} {d:>5} -> {g}  momentum={momentum}")
                cx, cy = nx, ny
        print(f"  Final tile: ({cx + grid_ox}, {cy + grid_oy})  "
              f"target: ({tx}, {ty})  "
              f"{'MATCH' if (cx+grid_ox, cy+grid_oy)==(tx, ty) else 'MISS'}")

    return path_3d or clean


def instrument_and_run(emu):
    """Run navigate_to with instrumentation hooks; log per-step evidence."""
    log: list[dict] = []

    orig_step_hold = nav_constants.step_hold
    orig_advance_frames = emu.advance_frames
    orig_advance_frames_until = emu.advance_frames_until
    orig_read_position = navigation._read_position
    orig_try_repath = navigation._try_repath

    # Snapshot the currently bound names inside the `navigation` module so
    # monkey-patches are visible from the exec loop.
    navigation.step_hold = None  # will set below

    def logged_step_hold(e, direction, active_hold, aux_buttons=None):
        before = _pos(e)
        bike = _on_bike(e)
        ret = orig_step_hold(e, direction, active_hold, aux_buttons=aux_buttons)
        after = _pos(e)
        log.append({
            "type": "step_hold", "direction": direction,
            "hold": active_hold, "aux": aux_buttons,
            "before": before, "after": after, "bike": bike,
            "triggered": ret.get("triggered"),
            "frames": ret.get("frames_elapsed"),
        })
        return ret
    navigation.step_hold = logged_step_hold

    def logged_advance_frames(count=1, buttons=None, touch_x=None, touch_y=None):
        before = _pos(emu)
        ret = orig_advance_frames(count=count, buttons=buttons or [],
                                  touch_x=touch_x, touch_y=touch_y)
        after = _pos(emu)
        log.append({
            "type": "advance_frames", "count": count, "buttons": buttons,
            "before": before, "after": after,
        })
        return ret
    emu.advance_frames = logged_advance_frames

    def logged_advance_frames_until(max_frames, conditions, poll_interval=1, buttons=None):
        before = _pos(emu)
        bike = _on_bike(emu)
        gear_before = _gear(emu) if bike else None
        ret = orig_advance_frames_until(
            max_frames=max_frames, conditions=conditions,
            poll_interval=poll_interval, buttons=buttons or [],
        )
        after = _pos(emu)
        bike_after = _on_bike(emu)
        gear_after = _gear(emu) if bike_after else None
        log.append({
            "type": "advance_frames_until", "max": max_frames,
            "buttons": buttons, "conds": conditions,
            "before": before, "after": after, "bike": bike,
            "gear_before": gear_before, "gear_after": gear_after,
            "triggered": ret.get("triggered"),
            "frames": ret.get("frames_elapsed"),
        })
        return ret
    emu.advance_frames_until = logged_advance_frames_until

    def logged_try_repath(repath_ctx, prev_npcs, new_x, new_y):
        ret = orig_try_repath(repath_ctx, prev_npcs, new_x, new_y)
        log.append({
            "type": "try_repath", "from": (new_x, new_y),
            "new_path": ret,
        })
        return ret
    navigation._try_repath = logged_try_repath

    try:
        result = _navigate_to(emu, target_x=TARGET[0], target_y=TARGET[1],
                              flee_encounters=True)
    finally:
        nav_constants.step_hold = orig_step_hold
        if hasattr(navigation, "step_hold"):
            navigation.step_hold = orig_step_hold
        emu.advance_frames = orig_advance_frames
        emu.advance_frames_until = orig_advance_frames_until
        navigation._try_repath = orig_try_repath
        navigation._read_position = orig_read_position

    return result, log


def print_event_log(log):
    print(f"\n== Instrumented event log ({len(log)} events) ==")
    for i, ev in enumerate(log):
        t = ev["type"]
        if t == "step_hold":
            moved = ev["after"] != ev["before"]
            print(f"  [{i:3d}] step_hold {ev['direction']:>5}  "
                  f"{ev['before']} → {ev['after']}  "
                  f"{'MOVED' if moved else 'STUCK':>5}  "
                  f"trig={ev['triggered']} frames={ev['frames']}  "
                  f"bike={ev['bike']}")
        elif t == "advance_frames_until":
            conds = ev["conds"]
            cond_s = ""
            if conds:
                c = conds[0]
                op = c.get("operator", "==")
                cond_s = f"addr+off {op} {c.get('value', '?')}"
            btn_s = str(ev['buttons'])
            gear_s = ""
            if ev.get('gear_before') is not None or ev.get('gear_after') is not None:
                gear_s = f" gear={ev.get('gear_before')}→{ev.get('gear_after')}"
            print(f"  [{i:3d}] afu btn={btn_s:<20} max={ev['max']:<5} "
                  f"{ev['before']} → {ev['after']}  "
                  f"trig={ev['triggered']} frames={ev['frames']}  "
                  f"bike={ev['bike']}{gear_s}  [{cond_s}]")
        elif t == "advance_frames":
            print(f"  [{i:3d}] frames count={ev['count']:<4} "
                  f"btn={ev['buttons']}  "
                  f"{ev['before']} → {ev['after']}")
        elif t == "try_repath":
            path_preview = ev["new_path"][:6] if ev["new_path"] else None
            print(f"  [{i:3d}] *** TRY_REPATH from {ev['from']}  "
                  f"new_path={path_preview}...  "
                  f"(len={len(ev['new_path']) if ev['new_path'] else 0})")


def main():
    emu = EmulatorClient(SOCK)

    print(f"=== Diagnostic: navigate_to((31, 16)) on {SAVE} ===")
    do_load_state(emu, SAVE, redetect_shift=True)
    x0, y0 = _pos(emu)
    print(f"Loaded. Player at ({x0}, {y0})  on_bike={_on_bike(emu)}")

    # 1. Extract BFS plan without executing
    dump_bfs_plan(emu)

    # 2. Reload and run actual navigate_to with instrumentation
    do_load_state(emu, SAVE, redetect_shift=True)
    result, log = instrument_and_run(emu)

    x1, y1 = _pos(emu)
    print(f"\n== navigate_to result ==")
    print(json.dumps(result, indent=2))
    print(f"\nFinal position: ({x1}, {y1})  target: (31, 16)  "
          f"(interaction tile (31, 17))")

    print_event_log(log)


if __name__ == "__main__":
    main()
