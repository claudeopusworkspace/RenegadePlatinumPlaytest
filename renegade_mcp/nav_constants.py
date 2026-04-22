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


# ── Direction handling ──
DIR_ALIASES = {"u": "up", "d": "down", "l": "left", "r": "right"}
BFS_MOVES = [(0, -1, "up"), (0, 1, "down"), (-1, 0, "left"), (1, 0, "right")]
_DIR_DELTAS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE_DIR = {"up": "down", "down": "up", "left": "right", "right": "left"}
_OPPOSITE_DIR = OPPOSITE_DIR  # alias used by bike slope traversal

# Ledge behaviors: direction you must be moving to cross them
LEDGE_DIRECTIONS = {
    0x38: "down", 0x39: "up", 0x3A: "left", 0x3B: "right",
}

# ── Bike slopes ──
BIKE_SLOPE_BEHAVIORS = {0xD9, 0xDA}  # bike_slope_top, bike_slope_bottom
BIKE_SLOPE_TYPES = {"bike_slope"}
BIKE_SLOPE_BACKUP_TILES = 3  # tiles to back up before the running start
BIKE_SLOPE_MAX_FRAMES = 600  # safety cap for the continuous hold phase

# ── Bike jump ramps (Wayward Cave etc.) ──
# 0xD7 = BIKE_RAMP_EASTWARD, 0xD8 = BIKE_RAMP_WESTWARD (pokeplatinum decomp).
# The tile is hard-blocked (0x8000) on foot; when on a bicycle and stepping
# INTO the ramp in the matching direction, the engine launches the player
# 2 tiles (MOVEMENT_ACTION_JUMP_FAR_*, FX32_CONST(2)*16=2-tile displacement).
# No N/S ramp variants exist in Gen 4 Platinum.
BIKE_RAMP_BEHAVIORS = {0xD7, 0xD8}
BIKE_RAMP_DIRECTIONS = {0xD7: "right", 0xD8: "left"}
BIKE_RAMP_TYPES = {"bike_ramp"}
BIKE_RAMP_JUMP_TILES = 2  # total tile displacement from the entry tile

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
_3D_MAX_DEPTH = 5       # max ramp transitions in a single path search
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
    0x38: 'v', 0x39: '^', 0x3A: '<', 0x3B: '>',  # ledges
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
