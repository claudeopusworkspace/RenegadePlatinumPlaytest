# Obstacle-Aware Pathfinding — Design Document

## Status: DESIGN ONLY — Not yet implemented

## Background

`navigate_to` currently uses BFS with a simple passable/blocked grid. Map objects (NPCs, obstacles) block tiles via `npc_set`. Water tiles are always blocked. There is no concept of "conditionally passable" tiles or clearing obstacles mid-path.

## Obstacle Types

### Category A — Map Objects (zone_event ObjectEvents)

Identified by `graphicsID` in the zone_event data. Appear as entries in the dynamic object list at runtime.

| Graphics ID | Type | HM Move | Badge | Clearable? |
|---|---|---|---|---|
| 85 | Strength Boulder | Strength (HM04) | Mine | **No — puzzle-dependent, never auto-push** |
| 86 | Rock Smash Rock | Rock Smash (HM06) | Coal | Yes — destroyed on interaction |
| 87 | Cut Tree | Cut (HM01) | Forest | Yes — destroyed on interaction |

**Key detail:** These are the same data structure as NPCs. Only distinguishable by graphics ID. Currently all treated as impassable in `npc_set`.

### Category B — Terrain Tiles (behavior byte in terrain grid)

| Behavior | Hex | Type | HM Move | Badge |
|---|---|---|---|---|
| Water (river) | 0x10 | Surfable water | Surf (HM03) | Fen |
| Water (sea) | 0x15 | Surfable water | Surf (HM03) | Fen |
| Waterfall | 0x13 | Waterfall climb | Waterfall (HM07) | Beacon |
| Rock Climb N-S | 0x4A | Climbable wall | Rock Climb (HM08) | Icicle |
| Rock Climb E-W | 0x4B | Climbable wall | Rock Climb (HM08) | Icicle |

**Surf is special:** Entering water changes movement mode entirely. While surfing, water is passable and land is blocked. Exiting water is also a mode transition. Both entering and exiting should be treated as "obstacles" requiring a skill.

## Badge Requirements (from `field_move_tasks.c`)

| Move | Badge Constant | Badge Name |
|---|---|---|
| Rock Smash | BADGE_ID_COAL | Coal Badge (Roark) |
| Cut | BADGE_ID_FOREST | Forest Badge (Gardenia) |
| Strength | BADGE_ID_MINE | Mine Badge (Byron) |
| Surf | BADGE_ID_FEN | Fen Badge (Crasher Wake) |
| Waterfall | BADGE_ID_BEACON | Beacon Badge (Volkner) |
| Rock Climb | BADGE_ID_ICICLE | Icicle Badge (Candice) |

## Proposed `navigate_to` Behavior

### Default call: `navigate_to(x, y)`

1. Run BFS twice:
   - **Clean BFS**: obstacles and water treated as impassable (current behavior)
   - **Obstacle BFS**: clearable obstacles treated as passable if party has the required move + badge. Strength boulders always impassable. Surf/water passable if party has Surf + badge.

2. Based on results:

| Clean path? | Obstacle path shorter? | Skills available? | Action |
|---|---|---|---|
| Yes | No obstacle path or same length | N/A | **Move normally** (no change from today) |
| Yes | Yes, shorter | Yes | **Don't move.** Return both path lengths + required skills. Ask caller to choose. |
| Yes | Yes, shorter | No | **Move normally** via clean path (skills unavailable, no choice to make) |
| No | Yes | Yes | **Don't move.** Return obstacle path info + required skills. Only option needs confirmation. |
| No | Yes | No | **Report no path.** Obstacle path exists but skills unavailable. |
| No | No | N/A | **Report no path.** (same as today) |

3. Return data when asking:
```python
{
    "status": "obstacle_choice",  # or "obstacle_required"
    "clean_path_steps": 24,       # null if no clean path
    "obstacle_path_steps": 12,
    "obstacles": [
        {"type": "rock_smash", "x": 14, "y": 8, "move": "Rock Smash", "badge": "Coal"}
    ],
    "skills_available": True,
    "message": "Shorter path (12 steps) requires Rock Smash at (14,8). "
               "Clean path available (24 steps). Call again with path_choice='obstacle' or 'clean'."
}
```

### Follow-up call: `navigate_to(x, y, path_choice="obstacle")`

- Takes the obstacle path
- When reaching a clearable obstacle (Rock Smash rock, Cut tree): stop, face it, interact, clear it, continue
- When reaching water entry (Surf): stop, activate Surf, continue in surf mode
- Strength boulders: NEVER on the auto-path (always treated as impassable)

### Follow-up call: `navigate_to(x, y, path_choice="clean")`

- Takes the longer obstacle-free path

## Implementation Changes Needed

### 1. Object classification in `_build_terrain_info`

Split dynamic objects into categories:
```
npc_set         → truly impassable (NPCs, strength boulders)
obstacle_set    → conditionally passable {(x,y): {"type": "rock_smash", "gfx_id": 86, ...}}
```

Need to read `graphicsID` from the zone_event ObjectEvent data for each object. Current `view_map` already reads objects — need to include gfx ID in the output.

### 2. Dual BFS

Run BFS twice with different passability rules:
- Clean BFS: `obstacle_set` tiles are blocked
- Obstacle BFS: `obstacle_set` tiles are passable (if skills available), water tiles passable (if Surf available)

The obstacle BFS path needs to record WHICH obstacles it passes through (for the return data and for clearing during navigation).

### 3. Skill availability check

New helper: `party_has_field_move(emu, move_name) -> bool`
- Checks party for a Pokemon with the move (by name, from `read_party`)
- Checks badge status (from `read_trainer_status`)
- Returns True only if BOTH conditions met

### 4. Obstacle clearing during navigation

When navigating an obstacle path:
- Walk to tile adjacent to obstacle
- Face the obstacle
- Interact (A button)
- Handle "Would you like to use [HM]?" → YES
- Wait for animation
- Continue path

This is the same interaction pattern for Rock Smash, Cut, Waterfall, and Rock Climb. Strength is excluded.

### 5. Surf mode awareness

Deferred until we have Surf + save states to test. Design notes:
- Player state indicates surfing vs walking (memory address TBD)
- When surfing: water passable, land blocked (inverse of normal)
- Entering water = "obstacle" requiring Surf activation
- Exiting water = "obstacle" requiring stepping onto land tile
- BFS needs to track movement mode along the path (walk → surf → walk transitions)

## Edge Cases

- **<4 moves teach_tm flow**: If a party member needs to learn an HM mid-game and has <4 moves, the teach flow skips the forget prompt. Not yet handled in `teach_tm` (TODO noted in code).
- **Multiple obstacles on one path**: The obstacle BFS path may pass through 2+ obstacles. All need to be cleared sequentially.
- **Obstacle on the goal tile**: Rare but possible. The goal tile IS the obstacle (e.g., navigating to a rock to examine it).
- **Strength boulders blocking the ONLY path**: Report no path, even though the obstacle exists. Player must solve the puzzle manually.
- **Object visibility flags**: Some obstacles may be hidden by event flags (e.g., already cleared in a previous visit). The `hiddenFlag` field in ObjectEvent controls this — need to check flag state at runtime.

## Files to Modify

| File | Changes |
|---|---|
| `navigation.py` | Dual BFS, obstacle classification, `path_choice` param, clearing logic |
| `map_state.py` | Read gfx ID from zone_event objects, expose in object data |
| `server.py` | Update `navigate_to` tool signature with `path_choice` param |
| `view_map` output | Tag obstacles with type info (optional, for visibility) |

## Data Files Available

- `data/obj_event_gfx.txt` — Graphics ID → name lookup (line number = ID)
- Badge status readable via `read_trainer_status` tool (already implemented)
- Party moves readable via `read_party` tool (already implemented)

## Reference: Decompilation Source Files

- `ref/pokeplatinum/src/field_move_tasks.c` — Field move trigger and badge check logic
- `ref/pokeplatinum/src/map_tile_behavior.c` — Tile behavior query functions
- `ref/pokeplatinum/include/constants/field/map_tile_behaviors.h` — All tile behavior constants
- `ref/pokeplatinum/src/unk_0203C954.c` — Map object detection when facing a tile
- `ref/pokeplatinum/generated/object_events_gfx.txt` — Graphics ID enum
