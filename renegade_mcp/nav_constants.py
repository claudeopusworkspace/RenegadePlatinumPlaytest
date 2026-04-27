"""Shared constants and small utility functions for the navigation subsystem.

This module is the leaf of the navigation dependency tree — every other
nav_* / pathfinding / cycling_road / hm_traverse / fishing / interaction
module imports from here, but this module never imports from them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from renegade_mcp.map_names import lookup_map_name

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Movement timing ──
HOLD_FRAMES = 16       # walking: 1 tile per press
BIKE_HOLD_FRAMES = 4   # cycling: bike moves 1 tile per ~4 frames
SURF_HOLD_FRAMES = 8   # surfing: 1 tile per ~8 frames (2x walk speed)
WAIT_FRAMES = 8
SETTLE_FRAMES = 120
SLOW_TERRAIN_RETRIES = 3  # Re-press attempts on apparent block (deep snow, ice)

MAX_REPATHS = 15


def _get_move_hold(emu: EmulatorClient) -> int:
    """Return the per-tile hold frames based on whether the player is cycling."""
    from renegade_mcp.addresses import addr
    cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
    return BIKE_HOLD_FRAMES if cycling else HOLD_FRAMES


def step_hold(emu: EmulatorClient, direction: str, active_hold: int,
              aux_buttons: list[str] | None = None) -> dict:
    """Hold `direction` (+ optional aux buttons) until the player's coordinate
    on the movement axis changes, or max_frames elapses.

    Replaces the legacy `advance_frames(hold, buttons=[dir]) + advance_frames(WAIT)`
    pattern. Because `advance_frames_until` polls inside the bridge, the engine
    sees a single continuous hold across tile boundaries — which is what makes
    bike ramps/slopes and running-shoes speed behave correctly.

    Returns the raw advance_frames_until result. `triggered=False` indicates
    the call exhausted max_frames without the position changing — which the
    caller can treat as "blocked".

    Args:
        active_hold: Expected per-tile frames for the current locomotion
            (HOLD_FRAMES / BIKE_HOLD_FRAMES / SURF_HOLD_FRAMES). Used to size
            the safety cap — actual per-tile frames are usually less.
        aux_buttons: Extra buttons to hold alongside `direction`. Pass ["b"]
            for running shoes on foot (harmless indoors / on bike / surfing).
    """
    from renegade_mcp.addresses import addr
    axis_offset = 8 if direction in ("left", "right") else 12
    pos_addr = addr("PLAYER_POS_BASE") + axis_offset
    buttons = [direction] + (aux_buttons or [])
    return emu.advance_frames_until(
        max_frames=active_hold * 2 + 8,
        conditions=[{"type": "changed", "address": pos_addr, "size": "long"}],
        poll_interval=1,
        buttons=buttons,
    )


def drive_bike_subsegments(
    emu: EmulatorClient,
    subsegments: list[tuple[str, int, int]],
    settle_frames: int = 36,
    max_frames_per_tile: int = BIKE_HOLD_FRAMES * 6,
) -> list[dict]:
    """Drive a multi-direction sustained fast-bike hold via chained
    ``advance_frames_until`` calls with ``final_buttons`` handoff.

    Each sub-segment is ``(direction, target_x, target_y)``. The drive
    holds ``direction`` until the player's axis coordinate reaches the
    target (``>=`` for right/down, ``<=`` for left/up). The trailing
    render frame is set to the *next* sub-segment's direction via
    ``final_buttons`` — so the bike never sees an empty-input frame and
    fast-bike momentum is preserved across the turn (proved in
    ``scripts/spike_bike_snake_phase6_final_buttons.py``).

    On the LAST sub-segment, ``final_buttons=None``: inputs release for
    the trailing frame and ``settle_frames`` of no-input idle let any
    pending ramp-jump animation place the player on its natural landing
    without fast-gear drift past it.

    Returns the per-sub-segment ``advance_frames_until`` results so the
    caller can detect missed conditions (``triggered=False`` on any
    sub-segment indicates a sized-frame timeout).
    """
    from renegade_mcp.addresses import addr
    base = addr("PLAYER_POS_BASE")
    results: list[dict] = []
    for i, (direction, tx, ty) in enumerate(subsegments):
        is_last = i == len(subsegments) - 1
        next_dir = subsegments[i + 1][0] if not is_last else None
        axis_offset = 8 if direction in ("left", "right") else 12
        target = tx if direction in ("left", "right") else ty
        operator = ">=" if direction in ("right", "down") else "<="
        # Tile budget for this sub-segment: distance to target + accel
        # ramp slack. We don't know the exact tile count when the
        # sub-segment includes ramp jumps (one direction can cover 5
        # tiles via FAR jump), so cap at the distance + a generous
        # buffer for the ramp animation.
        cur_x = emu.read_memory(base + 8, size="long")
        cur_y = emu.read_memory(base + 12, size="long")
        cur = cur_x if direction in ("left", "right") else cur_y
        dist = abs(target - cur)
        max_frames = max(max_frames_per_tile * (dist + 1), 60)
        res = emu.advance_frames_until(
            max_frames=max_frames,
            conditions=[{
                "type": "value",
                "address": base + axis_offset,
                "size": "long",
                "operator": operator,
                "value": target,
            }],
            poll_interval=1,
            buttons=[direction],
            final_buttons=[next_dir] if next_dir else None,
        )
        results.append(res)
    if settle_frames > 0:
        emu.advance_frames(settle_frames)
    return results


# ── Direction handling ──
DIR_ALIASES = {"u": "up", "d": "down", "l": "left", "r": "right"}
BFS_MOVES = [(0, -1, "up"), (0, 1, "down"), (-1, 0, "left"), (1, 0, "right")]
_DIR_DELTAS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE_DIR = {"up": "down", "down": "up", "left": "right", "right": "left"}
_OPPOSITE_DIR = OPPOSITE_DIR  # alias used by bike slope traversal

# Ledge behaviors: direction you must be moving to cross them.
# Per pokeplatinum decomp (include/constants/field/map_tile_behaviors.h):
#   0x38 JUMP_EAST — triggered moving east (right)
#   0x39 JUMP_WEST — triggered moving west (left)
#   0x3A JUMP_NORTH — triggered moving north (up)
#   0x3B JUMP_SOUTH — triggered moving south (down)
# Confirmed by src/unk_0205F180.c:1772-1793 (direction switch → IsJump{North,South,West,East}).
LEDGE_DIRECTIONS = {
    0x38: "right", 0x39: "left", 0x3A: "up", 0x3B: "down",
}

# ── Bike slopes ──
# Slopes are N-S only in Gen 4 Platinum. 0xD9 (top) sits north of 0xDA (bottom);
# climbing means stepping NORTH (up) onto 0xDA from the approach tile south of
# it. Sliding down is auto-handled by the engine with no runway requirement.
#
# The engine's running-start detection rejects ascent attempts that arrive at
# the approach tile via a turn — empirically verified session 37 on
# `bug_bike_slope_turn_into_approach` (BUG-045). BFS enforces the same rule:
# entering a slope tile going `up` requires BIKE_SLOPE_RUNWAY_TILES of
# consecutive same-direction (up) motion ending at the slope tile itself
# (approach tile counts toward the runway, same convention as bike ramps).
# RUNWAY_TILES=4 matches the helper's BACKUP_TILES=3 plus the slope tile
# itself — 3 tiles of south-approach momentum then stepping onto the slope.
BIKE_SLOPE_BEHAVIORS = {0xD9, 0xDA}  # bike_slope_top, bike_slope_bottom
BIKE_SLOPE_TYPES = {"bike_slope"}
BIKE_SLOPE_BACKUP_TILES = 3  # tiles to back up before the running start
BIKE_SLOPE_RUNWAY_TILES = 4  # consecutive up-direction tiles required before slope entry
BIKE_SLOPE_MAX_FRAMES = 600  # safety cap for the continuous hold phase

# ── Bike jump ramps (Wayward Cave etc.) ──
# 0xD7 = BIKE_RAMP_EASTWARD, 0xD8 = BIKE_RAMP_WESTWARD (pokeplatinum decomp).
# On a bicycle, stepping INTO the ramp in the matching direction triggers
# one of two jump actions, selected by the player's running-start momentum
# at the ramp tile:
#
#   • FAR jump (`MOVEMENT_ACTION_JUMP_FARTHER_*`): fires with full momentum
#     (≥ 4 tiles of continuous same-direction travel including the approach
#     tile). Displaces 5 tiles from approach = 4 past the ramp. Empirically
#     verified on `session31_wayward_cave_bike_ramps`
#     (scripts/spike_ramp_poll_release.py): release at ramp tile x=10 + 32+f
#     idle → land at x=14.
#
#   • NEAR jump (`MOVEMENT_ACTION_JUMP_NEAR_SLOW_*`): fires from a standing
#     start (momentum = 0 at the approach tile). Displaces 2 tiles from
#     approach = 1 past the ramp. Empirically verified 2026-04-23 on
#     `spike_final_ramp_approach`: stationary at ramp-1, hold direction,
#     land at ramp+1. The gear byte (BIKE_GEAR_STATE_ADDR) does NOT
#     select between near/far — it controls bike tile-speed, but the
#     jump-action selector reads running-start momentum.
#
# In-between momentum (1 or 2 tiles of runway) produced an inconclusive
# result in our spike (the (28, 17) wall in Wayward Cave may have clamped
# the landing), so BFS intentionally does not model those regimes: an
# approach tile with momentum < RUNWAY but > 0 emits no ramp edge.
# Puzzles that hinge on mid-range momentum would need fresh spiking.
#
# No N/S ramp variants exist in Gen 4 Platinum.
BIKE_RAMP_BEHAVIORS = {0xD7, 0xD8}
BIKE_RAMP_DIRECTIONS = {0xD7: "right", 0xD8: "left"}
BIKE_RAMP_TYPES = {"bike_ramp"}
BIKE_RAMP_JUMP_TILES = 5          # far-jump displacement from approach tile (= ramp+4)
BIKE_RAMP_NEAR_JUMP_TILES = 2     # near-jump displacement from approach tile (= ramp+1)
BIKE_RAMP_RUNWAY_TILES = 4        # consecutive same-direction tiles required for FAR jump

# ── Bike bridges (Wayward Cave etc.) ──
# Wooden bike-only bridges whose body tiles reject on-foot entry. Mount the
# bike to cross, dismount on the first non-body tile on the far side. No
# momentum requirement — slow or fast gear both traverse cleanly.
#
# Body behaviors (pokeplatinum decomp map_tile_behaviors.h):
#   0x76 BIKE_BRIDGE_NS / 0x77 BIKE_BRIDGE_NS_ENCOUNTER
#   0x78 BIKE_BRIDGE_NS_WATER / 0x79 BIKE_BRIDGE_NS_SAND
#   0x7A BIKE_BRIDGE_EW / 0x7B BIKE_BRIDGE_EW_ENCOUNTER
#   0x7C BIKE_BRIDGE_EW_WATER / 0x7D BIKE_BRIDGE_EW_SAND
#
# Excludes 0x70 BRIDGE_START and 0x71 BRIDGE — those are the Cycling Road
# forced-slide bridge body and are handled by cycling_road.py via
# FLAG_ON_CYCLING_ROAD. 0x70 at the mouth of a bike bridge is walkable on
# foot AND bike; we intentionally do NOT require bike for 0x70 entry,
# which lets the mount happen on the bridge_start tile itself.
#
# Empirical invariant: the engine refuses `use_item("Bicycle")` while the
# player is on a body tile — "stuck mid-bridge" is not reachable.
BIKE_BRIDGE_BEHAVIORS = {0x76, 0x77, 0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7D}
BIKE_BRIDGE_TYPES = {"bike_bridge"}

# ── Water / terrain obstacles ──
WATER_BEHAVIORS = {0x10, 0x15}  # river, sea (surfable)
WATERFALL_BEHAVIOR = 0x13
ROCK_CLIMB_BEHAVIORS = {0x4A, 0x4B}  # N-S, E-W

# All terrain-based obstacles (water + waterfall + rock climb)
TERRAIN_OBSTACLES = WATER_BEHAVIORS | {WATERFALL_BEHAVIOR} | ROCK_CLIMB_BEHAVIORS

# ── HM obstacle objects (identified by graphics_id in zone_event data) ──
# HM_OBSTACLES is retained as a reference table — view_map uses decomp-sourced
# GFX_NAMES for labels, so trimming the auto-clear sets below doesn't affect
# visible metadata. See "HM auto-clear scope" note below the constants.
HM_OBSTACLES: dict[int, dict[str, str]] = {
    84: {"type": "strength_boulder", "move": "Strength",   "badge": "Mine"},
    85: {"type": "rock_smash",       "move": "Rock Smash", "badge": "Coal"},
    86: {"type": "cut_tree",         "move": "Cut",        "badge": "Forest"},
}

# ── HM auto-clear scope ──
# Renegade Platinum removes every path-gating Cut tree and every path-gating
# Rock Smash rock from Sinnoh. Drayano left decorative instances in place
# (e.g. Oreburgh Mine B2F rocks), but they never block a required route — the
# player can always walk around. Auto-clearing them through the HM animation
# is slower than routing around, so GFX 85 / 86 are now treated as impassable
# objects (they fall through to npc_set in pathfinding classification).
#
# The dual-path BFS and hm_traverse clearing sequence are kept intact for
# Surf, Rock Climb, and Waterfall, which are still mandatory. If a mandatory
# Rock Smash / Cut obstacle is ever discovered, re-enabling auto-clear is a
# one-line change: add the relevant GFX id(s) to CLEARABLE_OBSTACLES and the
# matching type string(s) to CLEARABLE_TYPES.
CLEARABLE_OBSTACLES: set[int] = set()    # was {85, 86} — see note above
CLEARABLE_TYPES: set[str] = set()        # was {"rock_smash", "cut_tree"}
SURF_TYPES = {"water"}
ROCK_CLIMB_TYPES = {"rock_climb"}
WATERFALL_TYPES = {"waterfall"}
MULTI_TILE_HM_TYPES = ROCK_CLIMB_TYPES | WATERFALL_TYPES
AUTO_NAVIGATE_TYPES = CLEARABLE_TYPES | SURF_TYPES | ROCK_CLIMB_TYPES | WATERFALL_TYPES
PUZZLE_OBSTACLES = {84}  # strength_boulder — Distortion World only; handle manually

# ── Follower NPC detection ──
# Movement type ids from pret/pokeplatinum (generated/movement_types.txt).
# An NPC with one of these movement types follows the player tile-by-tile,
# and the engine swaps them with the player whenever the player steps onto
# their tile — so BFS must treat follower tiles as passable, not blocking,
# otherwise narrow corridors (e.g. Wayward Cave's Mira escort) end up with
# every POI on the far side of the follower reported unreachable.
MOVEMENT_TYPE_FOLLOW_PLAYER = 48
MOVEMENT_TYPE_FOLLOW_PARTNER_TRAINER = 50
FOLLOWER_MOVEMENT_TYPES = frozenset({
    MOVEMENT_TYPE_FOLLOW_PLAYER,
    MOVEMENT_TYPE_FOLLOW_PARTNER_TRAINER,
})


def is_follower_npc(obj: dict) -> bool:
    """True if this map object is an active follower (Mira/Cheryl/rival/etc.).

    `obj` is a dict from `read_objects`. The check looks at the raw
    movement-type id rather than the human-readable label so it stays
    correct for ids the label table doesn't know about. Accepts either
    the raw id (stored under `movement_type_id` when added) or — for
    backward compatibility with callers that only preserved the label —
    the `type_NN` label form emitted by MOVEMENT_TYPES.get fallback.
    """
    raw = obj.get("movement_type_id")
    if raw is None:
        label = obj.get("movement_type", "")
        if isinstance(label, str) and label.startswith("type_"):
            try:
                raw = int(label[5:])
            except ValueError:
                raw = None
    return raw in FOLLOWER_MOVEMENT_TYPES

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

# ── Door/warp tile behaviors ──
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

DIRECTIONAL_WARP: dict[int, str] = {
    0x62: "right",  # WARP_ENTRANCE_EAST — walk east into cave
    0x63: "left",   # WARP_ENTRANCE_WEST — walk west into cave
    0x64: "up",     # WARP_ENTRANCE_NORTH — walk north into cave
    0x6C: "right",  # WARP_EAST — side entry, walk east
    0x6D: "left",   # WARP_WEST — side entry, walk west
    0x6F: "down",   # WARP_SOUTH — side entry, walk south
}

WARP_PASSABLE = {0x69} | set(DIRECTIONAL_WARP.keys())

DIRECTIONAL_BLOCKS: dict[int, str] = {
    0x30: "right",  # block_E — can't step east off platform
    0x31: "left",   # block_W — can't step west off platform
}

# ── 3D pathfinding constants ──
_3D_MAX_DEPTH = 15      # max ramp transitions in a single path search.
# Wayward Cave B1F's south-corridor → warp:0 path requires ~10 transitions
# (9 → 0 → 2 → 3 → 8 → 7 → 5 → 4 → 1 → 13 → 14 → 11 → 12 → 10 → 19 → 18),
# so a depth ≥ 11 is needed for that puzzle. Priority-sorted DFS prunes
# effectively in practice — empirically <0.1s wall-clock at depth 20.
_3D_TIMEOUT = 300       # wall-clock seconds before aborting 3D search

# Height units: 16 = one full tile height. Small dips (L0 grass/puddles in
# Eterna Gym, cracked/sunken floor tiles in gyms) sit a few units below the
# walking plane and are crossed in-game without a ramp animation. Treat two
# levels whose heights differ by at most this many units as walkable from
# each other without a dedicated ramp — otherwise the 3D BFS refuses to
# cross a 2-unit dip like the L0 strip at row 20 of Eterna Gym (map 67).
STEPPABLE_HEIGHT = 4

# ── Door transition polling ──
DOOR_TRANSITION_POLLS = 30   # polls to wait for map transition (30 * 15 = 450 frames)
DOOR_POLL_FRAMES = 15

# ── Auto-flee / encounter constants ──
MAX_FLEE_ENCOUNTERS = 10
POST_BATTLE_SETTLE = 300  # frames to wait after battle ends before resuming nav
_BATTLE_OVER = {"BATTLE_ENDED"}
_FAINT_STATES = {"FAINT_SWITCH", "FAINT_FORCED"}

# ── Post-navigation encounter/dialogue detection ──
POST_NAV_POLL_FRAMES = 15
POST_NAV_MAX_POLLS = 20  # 20 * 15 = 300 frames

# ── Encounter seeking ──
SEEK_MAX_STEPS = 200
SEEK_MAX_CASTS = 20     # Max fishing attempts before giving up
GRASS_BEHAVIOR = 0x02

# ── Fishing constants ──
_FISH_ANIM_OFFSET = 0xA0
_FISH_ANIM_BITE = 2
_FISH_MAX_POLL = 600    # ~10 sec timeout per cast
_ROD_NAMES = {"old rod", "good rod", "super rod"}
_FACING_VALUES = {"up": 0, "down": 1, "left": 2, "right": 3}
_FACING_DELTAS = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}

# ── Cycling road constants ──
CYCLING_ROAD_SLIDE_RATE = 4      # frames per tile when sliding south
CYCLING_ROAD_UPHILL_HOLD = 12    # frames to hold UP per tile (padded for safety)
CYCLING_ROAD_LATERAL_HOLD = 4    # frames to hold LEFT/RIGHT per tile
CYCLING_ROAD_POLL_INTERVAL = 2   # frames between position checks
CYCLING_ROAD_MAX_WAIT = 600      # max frames to wait for a slide to complete (~10 sec)

# ── HM obstacle clearing timing ──
HM_INTERACT_WAIT = 120   # frames after A press for text scroll + Yes/No prompt
HM_POST_CONFIRM_WAIT = 300  # frames after Yes for text + animation to complete
HM_SETTLE_WAIT = 120     # frames to settle back into overworld after animation

# ── Interact-with constants ──
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

# ── Behavior chars for failure diagrams ──
_DIAG_CHAR: dict[int, str] = {
    0x02: '"', 0x03: '"',  # grass
    0x10: '≈', 0x13: '≈', 0x15: '≈',  # water
    0x38: '>', 0x39: '<', 0x3A: '^', 0x3B: 'v',  # ledges (arrow = jump direction)
    0x69: 'D', 0x6E: 'D',  # doors
}


# ── Small utility functions ──

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
