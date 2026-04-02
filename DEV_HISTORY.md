# Dev History

Chronological log of tool development, bug fixes, and MCP improvements — separate from gameplay in GAME_HISTORY.md.

## Dev Session: move_info + Multi-Hit TIMEOUT Fix (2026-04-02)

### New Tool: `move_info`
- Standalone move stats lookup (type, power, accuracy, PP, class, priority) from ROM data (`move_data.json`). Pure data, no emulator needed.
- Enriched `read_party` and `read_battle` move displays — moves now show inline detail tags: `Bullet Seed [Grass · Physical · 25 pwr · 100% acc] (PP 29)` instead of bare `Bullet Seed (PP 29)`.
- Data was already extracted last session (`data/move_data.json`, 471 moves from `pl_waza_tbl.narc`); this session wired it into the formatters and added the MCP tool.

### Bug Fix: Multi-Hit Move TIMEOUT on Faint
- **Symptom**: `battle_turn(move_index=2)` (Bullet Seed, 5-hit) vs Roark's Nosepass returned TIMEOUT instead of SWITCH_PROMPT.
- **Diagnosis**: Wrote a text-region timeline scanner. Found that "Turtwig used Bullet Seed!" text persists for 1200+ frames (~20 sec) while all 5 hit animations play, consuming ~80 of the 150-poll budget. After "Nosepass fainted!", a ~300-frame animation gap (faint sprite + EXP bar filling) triggers `NO_TEXT_EXIT_THRESHOLD` (20 polls × 15 frames = 300 frames). All text goes through the same address (`0x02301BF4`), so the narrow scan region wasn't the issue.
- **Fix**: (1) In `battle_tracker.py`, triple the consecutive-none threshold when "fainted" is in the log — we know EXP + switch text is still coming. (2) In `turn.py`'s `_execute_action`, broaden TIMEOUT recovery to trigger on "fainted" in log (not just "grew to"), reusing `_recover_from_level_up`.
- **Test**: New `test_multi_hit.py` (2 tests) verifying SWITCH_PROMPT result and log completeness. Full suite: 27 passed, 1 skipped (21 min).

## Dev Session: Bug Fixes (2026-03-31)

No adventure progress — focused on fixing the two remaining backlog bugs:

1. **interact_with trainer-spotted race condition**: Reproduced in Oreburgh Gate using `route203_cave_entrance_debug` save state. Camper's trainer-spotted script seized player control mid-navigate, causing facing direction press to be silently ignored and dialogue check to return too early. Fixed by validating facing changed + falling back to `_post_nav_check` polling.

2. **read_dialogue multi-choice infinite loop**: Reproduced using `oreburgh_mine_roark_dialogue_bug` save state. Roark's stone quiz uses a ListMenu (shouldResume callback 0x02040A51) that doesn't set ctrlUI like Yes/No menus. Code kept pressing B → cancel → "try again" → repeat. Fixed by tracking seen text segments and returning `"multi_choice_prompt"` on conversation loop detection.

## Dev Session: auto_grind Improvements & Bug Fix (2026-03-31)

### Tool Improvements
- **auto_grind `iterations` parameter**: New optional arg stops after N wild encounters (alternative/complement to `target_level`). Useful for scouting routes without open-ended grinding. `auto_grind(move_index=0, iterations=5)` runs 5 encounters and stops.
- **auto_grind encounter log**: Every response now includes an `encounters` list with `species` (name) and `checkpoint_id` (hash). Reverting to a checkpoint lands at the start of that specific battle, ready to throw a ball — trade XP gained since for a catch opportunity. Tested on Route 202: Shinx + 2x Sentret, reverted to Shinx checkpoint and confirmed battle state.

### Bug Fix: Level-Up Recovery After Move-Learn
- **Root cause**: `_poll_after_action()` (shared exit path for move-learn, switch, faint flows) lacked level-up recovery. When Turtwig resolved a move-learn and Piplup (Exp Share) leveled up next, the "grew to" text scrolled past during the move-learn flow's B presses. The tracker was re-initialized after, so the poll saw a static stat screen with no text markers → TIMEOUT.
- **Fix**: `_poll_after_action` now calls `_recover_from_level_up` on any TIMEOUT where battle isn't over (not gated on "grew to" in log). Tested from `debug_piplup_levelup_in_battle` save state — recovered through Piplup Lv13 stat screen and reached SWITCH_PROMPT for Omanyte.

### Backlog Cleanup
- Removed stale `read_party` encryption timing issue (root cause fixed in earlier session).
- Removed `advance_frames` parameter naming note (convention, not a bug).
- Removed fixed `battle_turn` level-up bug (just fixed above).
- Remaining: auto_grind cancellation (MCP limitation), unconfirmed shop cursor bug.

## Dev Session: Elevation-Aware Mapping (2026-04-01)

### Elevation System Discovery
- Pokemon Platinum maps use **BDHC (Building Density Height Collision)** data embedded in ROM `land_data` files
- Each map has "plates" — rectangular surfaces at specific heights, including flat platforms and tilted ramps
- Oreburgh Gym has **4 elevation levels**: ground (h=0), mid walkways (h=32), side walkways (h=48), Roark's platform (h=64)
- Row 17 of the gym has a **bridge** — level 1 walkway over level 0 ground
- Player height readable from MapObject[0].pos.y (fx32 at 0x022A1AAC)

### Tile Behavior Discovery (0x30/0x31)
- `0x30` and `0x31` are **directional movement blockers** at elevation edges
- `0x30` blocks eastward movement, `0x31` blocks westward movement
- Used as a lightweight alternative to wall tiles at platform edges
- The visual "slopes" flanking the center stairs are actually wall tiles (#); 0x30/0x31 are the invisible edge barriers

### view_map Enhancements
1. **Elevation-aware rendering**: passable tiles show height level numbers (0-9), flat maps unchanged
2. **Ramp indicators**: `\` and `/` show descent direction on BDHC ramp plates
3. **Bridge notation**: `n*` marks tiles with multiple overlapping elevation levels
4. **Directional blockers**: `]` (can't move east) and `[` (can't move west) replace confusing hex codes
5. **Level filter**: `view_map(level=N)` isolates a single elevation, dimming others to `~`
6. **Elevation summary**: lists all levels, ramp connections, and player's current height

### Known Limitation
- `navigate_to` BFS is still 2D — doesn't account for elevation. Added to backlog. Oreburgh Gym is the simplest test case for 3D BFS work. Can plan routes manually using elevation display + `navigate` for now.

## Dev Session: Backlog Blitz — 4 QoL Fixes (2026-04-02)

Pure tool development session. Tackled the four most impactful QoL items from the backlog.

### 1. Stale Battle RAM / Slow Navigation (battleEndFlag)
- **Root cause**: After the Jubilife tag battle, Dawn's Piplup data persisted in battle slot 2. `read_battle` passed all per-slot validation (valid species, level, HP). `_post_nav_check` treated it as a real battle, called `_wait_for_action_prompt` which timed out (~30s) waiting for an action prompt that never came.
- **Fix**: Found `battleEndFlag` in the pret/pokeplatinum decomp (`BattleContext` struct, `battle_context.h:293`). Computed offset from known `battleMons` base: `0x022C5774 + 4*0xC0 + 0xDF = 0x022C5B53`. Verified empirically: 0 during active battle, 1 in overworld. Added as early-return gate in `read_battle` — all callers benefit.
- **Key decomp files**: `include/battle/battle_context.h` (struct layout), `include/battle/battle_mon.h` (BattleMon = 0xC0 bytes), `src/battle/battle_controller_player.c` (lifecycle).

### 2. Side Warp Transitions
- **Root cause**: `_handle_door_transition` only checked `DOOR_ACTIVATION` dict for the direction to press. Directional warps (0x62, 0x63, 0x6C, 0x6D) are in `DIRECTIONAL_WARP` dict, so `activation` was None and no direction was pressed. Polled for map transition that never happened.
- **Fix**: Fall back to `DIRECTIONAL_WARP.get(behavior)` when `DOOR_ACTIVATION` has no entry. Two-line change. Tested both exits of Oreburgh Gate (west→Route 203, east→Oreburgh City).

### 3. Trainer Dialogue Auto-Advance During Navigation
- **Root cause**: `_post_nav_check` detected overworld dialogue but returned the raw buffer without advancing. Trainer pre-battle taunts left the game stuck in dialogue, requiring manual `read_dialogue` before `battle_turn`.
- **Fix**: Chain into `advance_dialogue` when dialogue detected, then re-check for battle. Returns full conversation text + battle state ready for `battle_turn`. Tested on Route 204 north — trainer spotted, dialogue advanced, battle entered seamlessly.

### 4. Field Item Use (use_field_item)
- **New tool**: `use_field_item(item_name)` for no-target Items pocket items (Repel, Escape Rope, Honey).
- **ROM data**: Extracted `fieldUseFunc` from decomp's `pl_item_data.csv` into `data/item_field_use.json` (254 items). `ItemData.fieldUseFunc` at struct offset 10 determines field usability — 0 = hold-only, 19 = bag message, 21 = escape rope, etc.
- **Validation**: Pre-checks item is in Items pocket AND has a no-target fieldUseFunc. Silk Scarf correctly rejected. Repel tested (qty 9→8), clean overworld return confirmed.
- **Key decomp files**: `include/item.h` (ItemData struct), `include/constants/items.h` (ITEM_USE_FUNC_* constants), `res/items/pl_item_data.csv` (per-item data).

### Backlog Status
- **Resolved this session**: 4 items (stale battle RAM, side warps, trainer dialogue, field items)
- **Remaining open**: 3D elevation BFS, ledge directionality (both deferred — no gameplay blockers yet), tag battle edge-case testing (worked first try, low priority)

---

## Session 9 — Elevation-Aware 3D BFS (2026-04-02)

### Goal
Implement multi-level pathfinding for `navigate_to` so it can traverse maps with elevation (gyms, caves with raised platforms and ramps).

### Approach: Hierarchical BFS
Rather than rebuilding BFS with a full (x, y, z) state space, we brute-force over level transitions using the existing 2D BFS as a building block:
1. Try BFS restricted to current elevation level
2. If target unreachable: find all reachable ramp transitions on this level
3. For each ramp (sorted: toward target level first, then by proximity), "take" the transition and recurse on the new level
4. Depth-capped at 5 transitions, 5-minute wall-clock timeout

### Changes
- **`map_state.py`**: Added `ramp_index` field to ramp_info dicts in `analyze_elevation` for stable identity tracking.
- **`navigation.py`** (~270 new lines):
  - `_height_to_level` / `_get_tile_level`: elevation lookup helpers
  - `_bfs_pathfind_level`: single-level BFS with elevation constraint, directional block enforcement (0x30/0x31), and ramp transition collection
  - `_bfs_pathfind_3d`: hierarchical wrapper — recursive search across level transitions
  - `navigate_to`: detects 3D maps (single-chunk with BDHC elevation data), routes to 3D pathfinder; flat/chunked maps use existing 2D BFS unchanged
  - `DIRECTIONAL_BLOCKS` constant for platform-edge tile behaviors

### Testing (Oreburgh Gym — 4 elevation levels)
- L3→L0 straight down through 3 ramps: 20 steps ✓
- L3→L0 with lateral movement: 21 steps ✓
- L0→L2 ascending through 2 ramps: 20 steps ✓
- L2→L3 single ramp ascent: 9 steps ✓
- Route 204 (flat/chunked): 2D BFS unchanged ✓
- Route 203 cliff debug: ledges + slopes handled correctly, 43-step bypass around barriers ✓

### Backlog Status
- **Resolved this session**: 3D elevation BFS (single-chunk), ledge/cliff directionality (retested — works as expected)
- **Remaining open**: Multi-chunk 3D maps (deferred — no gameplay blockers), tag battle edge-case testing (low priority)

---

## Session 10 — Type Matchup Tool & Battle Effectiveness Guardrail (2026-04-02)

### Goal
Add type effectiveness checking as both a standalone tool and an automatic guardrail in `battle_turn` to prevent using immune/NVE moves by accident.

### Design Decisions
- **No ROM spoilers rule**: Woj vetoed `pokemon_info` (base stats, learnsets), `wild_encounters` (route tables), and trainer previews. Tools should emulate what a human player can see in the UI, not datamine ROM for foreknowledge. `type_matchup` and `move_info` are approved since players can always look these up.
- **Fairy type**: Renegade Platinum uses type ID 9 for Fairy (was "???" in vanilla Gen 4). Added Gen 6 standard Fairy matchups. Fixed `TYPE_NAMES` in `battle.py` to show "Fairy" instead of "???".
- **Status move exemption**: The effectiveness guardrail skips Status moves (e.g., Curse is Ghost-type but doesn't deal type-based damage when used by non-Ghosts).

### Changes

1. **`renegade_mcp/type_chart.py`** (new, ~180 lines)
   - Hardcoded Gen 4 + Fairy type effectiveness chart from pret/pokeplatinum decomp (`sTypeMatchupMultipliers` in `battle_lib.c`)
   - `effectiveness(atk_type, def_type1, def_type2)` → multiplier (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)
   - `describe(multiplier)` → human-readable label
   - `format_matchup()` → full formatted string
   - 18 types including Fairy, all 12 test cases passing

2. **`scripts/extract_move_data.py`** (new) + **`data/move_data.json`** (generated)
   - Extracts move type/power/accuracy/PP/class/priority from ROM's `pl_waza_tbl.narc`
   - Scans ROM FAT for NARC archives with ~470 entries of 16 bytes each
   - Identifies Renegade Platinum version by checking modified move values (Flamethrower 90 pow)
   - 471 moves extracted. Struct from pret/pokeplatinum `include/move_table.h`

3. **`renegade_mcp/data.py`** — added `move_data()` and `move_type(move_id)` loaders

4. **`renegade_mcp/battle.py`** — fixed `TYPE_NAMES[9]`: "???" → "Fairy"

5. **`renegade_mcp/server.py`** — two additions:
   - **`type_matchup` tool**: accepts `attacking_type` or `move_name` + `defending_types` (slash-separated). Looks up move type from `move_data.json`, computes multiplier, returns label + formatted string. Like Pokemon Showdown's damage calc.
   - **`battle_turn` guardrail**: new `force` parameter (default False). Before executing a move, `_check_move_effectiveness()` reads battle state, looks up move type, checks vs target types. Returns `EFFECTIVENESS_WARNING` with explanation if immune (0x) or NVE (≤0.5x). Status moves exempted. Pass `force=True` to proceed anyway.

### Testing
- Type chart: 12 test cases covering SE, NVE, immune, double SE (4x), doubly resisted (0.25x), immunity through dual types, Fairy matchups — all pass
- Move data: verified team moves (Bulldoze=Ground, Spark=Electric, Brick Break=Fighting, etc.) and known Renegade Platinum changes (Flamethrower 90 pow)
- Server.py: syntax validation pass, dry-run of type_matchup tool logic path

### Backlog Status
- **Resolved this session**: type_matchup tool, battle_turn effectiveness guardrail, Fairy type display
- **Remaining open**: heal_team, move_info (enrich existing displays), multi-chunk 3D BFS, tag battle testing
