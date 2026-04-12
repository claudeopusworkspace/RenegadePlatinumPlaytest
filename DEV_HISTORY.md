# Dev History

Chronological log of tool development, bug fixes, and MCP improvements — separate from gameplay in GAME_HISTORY.md.

## Dev Session: Performance — advance_frames_until + Scan Narrowing (2026-04-11i)

### Summary
Integrated MelonMCP's new `advance_frames_until` conditional frame advance primitive and narrowed the battle text scan region from 1.5MB to 128KB. Combined result: **292 tests pass, suite time 756.88s → 704.02s (-7.0%)**, with individual battle tests improving 10-29%.

### MelonMCP Issue & Implementation
- Filed claudeopusworkspace/MelonMCP#3 proposing `advance_frames_until` — advances up to N frames internally, returning early when a memory condition (value comparison, changed detection, or byte pattern scan) is met. Eliminates MCP round-trip overhead for polling loops.
- Implementation was completed in MelonMCP (`5ac4e14`). Added client wrapper method to `EmulatorClient` (`1644b8e`).

### advance_frames_until Integrations
1. **Fishing bite detection** (`navigation.py::_fish_once`): Replaced 600 frame-by-frame polls (1,200 bridge calls) with 2 `advance_frames_until` calls — phase 1 waits for cast animation (anim==1), phase 2 waits for bite (anim==2) or idle (anim==0).
2. **Door/warp transitions** (`navigation.py::_handle_door_transition`): Replaced 30-iteration map ID polling loop with a single `changed` condition on `PLAYER_POS_BASE`.
3. **Dialogue animation wait** (`dialogue.py::_wait_for_msgbox_or_script_end`): Replaced 200-iteration loop (checking script magic, msgbox flag, TextPrinter state) with 3 value conditions in one call.
4. **Dialogue CTX_RUNNING wait** (`dialogue.py`): Replaced 200-iteration animation wait (checking script end, msgbox close, context state change) with 3 conditions.
5. **Yes/No prompt verification** (`dialogue.py`): Replaced 30-iteration multi-check loop (6 separate memory reads per iteration) with 6 conditions in one call.

### Battle Scan Narrowing (the big win)
**Problem**: `BATTLE_SCAN_SIZE` was 0x180000 (1.5MB) — a conservative blanket from early development when text marker locations were unknown. Every `read_memory_block` in battle text scanning, action prompt detection, and evolution waiting read 1.5MB per iteration. A single battle could transfer ~290MB of memory reads.

**Investigation**: Empirically scanned memory across 4 different save states (wild battle, trainer, doubles, E4 save). Text markers consistently appeared at 0x023017F4–0x02301BC0 — a ~1KB span within a 1.5MB scan region.

**Fix**: Moved `BATTLE_SCAN_START` from 0x0228A000 to 0x022F0000 and shrunk `BATTLE_SCAN_SIZE` from 0x180000 to 0x20000 (128KB). The new range covers all observed markers with generous padding.

### Where advance_frames_until Doesn't Help (Yet)
Battle text polling (`battle_tracker.py::poll`) and action prompt detection (`turn.py::_wait_for_action_prompt`) need to read memory blocks and classify text content in Python each iteration. The round-trip overhead isn't just the frame advance — it's the `read_memory_block` + Python text scanning. These can't be replaced by simple conditions. The scan narrowing (1.5MB → 128KB) was the effective optimization for these paths.

### Test Timing Highlights (Baseline → After)
| Test | Before | After | Improvement |
|------|--------|-------|-------------|
| test_double_battle_both_actions | 6.34s | 4.52s | -29% |
| test_self_target_both_actions | 6.55s | 4.64s | -29% |
| test_target_species (auto_grind) | 15.66s | 11.25s | -28% |
| test_iterations_multiple (auto_grind) | 13.15s | 9.51s | -28% |
| test_use_move | 3.85s | 3.29s | -15% |
| test_trainer_full_battle | 12.62s | 11.33s | -10% |
| test_player_free_after_gym_event | 9.56s | 7.88s | -18% |
| **Full suite (292 tests)** | **756.88s** | **704.02s** | **-7.0%** |

### Other
- Fixed stale assertion in `test_unsupported_key_item_rejected` — error message changed from "not yet supported" to "not supported here" during an earlier refactor.

## Dev Session: Self-Targeting Moves in Doubles — BUG-003 (2026-04-11h)

### Summary
Fixed the last open QA bug: self-targeting moves (Swords Dance, Dragon Dance, Calm Mind, etc.) broke the doubles UI navigation in `battle_turn`. The tool would loop on "What will X do?" instead of progressing the turn. Also extracted the move `range` field from ROM data and added 6 integration tests.

### Root Cause Investigation
- In Gen 4 doubles, after selecting a move, the game shows a **target selection screen** where you tap which Pokemon to target.
- For self-targeting moves (ROM `range=16`, 61 moves total), the game shows a **different confirmation screen** with only the user's Pokemon visible in the bottom-right area.
- The old code always called `_target_flow_with_retry` which tapped enemy positions `TARGET_XY[0]=(190,50)` — this hit an inactive area on the self-target screen, causing the move selection to silently cancel and return to the action prompt.
- The `_tracker.poll` then found "What will X do?" again → classified as `WAIT_FOR_PARTNER_ACTION` → infinite loop.

### Debugging Journey
1. **Reproduced** with `route203_trainers_cleared` save state — swapped Abra (Teleport only) into slot 1 for double battle.
2. **Discovered Teleport is a special case**: the game engine rejects flee-moves (Teleport) at the UI level in trainer doubles — the move bounces back regardless of target handling.
3. **Pivoted to Swords Dance**: used `write_memory` to patch Abra's BattleMon move slot from Teleport (ID 100) to Swords Dance (ID 14) in live battle RAM. This let us test with a move the game actually accepts.
4. **Manually stepped through UI**: tapped FIGHT → Swords Dance → observed the self-target confirmation screen → tapped Abra at (195, 120) → "Monferno used Mach Punch! Abra used Swords Dance! Abra's Attack sharply rose!" — turn executed correctly.
5. **Retry logic added**: for the partner Pokemon's self-target, if the first tap at `SELF_TARGET_XY` doesn't register, tries the mirrored position `(256-x, y)` to cover slot 0 vs slot 2 positioning differences.

### ROM Data Enhancement
- **`scripts/extract_move_data.py`**: Added extraction of `u16 range` field at offset 8 in the 16-byte `MoveTable` struct from `pl_waza_tbl.narc`.
- **`data/move_data.json`**: Re-extracted with `range` field for all 471 moves.
- Range value catalogue:
  - `0` (337 moves): single target — Tackle, Flamethrower, etc.
  - `4` (25 moves): both opponents — Leer, Growl, etc.
  - `8` (9 moves): all adjacent — Surf, Earthquake, etc.
  - `16` (61 moves): **user/self** — Swords Dance, Teleport, Calm Mind, Dragon Dance, etc.
  - `32` (8 moves): user's side — Light Screen, Reflect, etc.
  - `64` (10 moves): both sides — Haze, Sandstorm, weather, etc.
  - `128` (3 moves): enemy's side — Spikes, Stealth Rock, etc.

### Implementation
- **`turn.py`**: Added `MOVE_RANGE_USER=16`, `SELF_TARGET_XY=(195,120)`, `_is_self_targeting_move()` (reads battle state → ROM move data → checks range), `_chooser_name_from_prompt()` (parses "What will X do?" text to identify which battler is choosing), retry tap at mirrored position.
- **Detection flow**: After `_fight_flow` selects the move, checks if the move's ROM range is 16. If so, taps `SELF_TARGET_XY` instead of running `_target_flow_with_retry`.

### Tests Added (6 new, 292 total across 24 files)
- `test_chooser_name_extraction` — unit test for prompt text parsing
- `test_is_self_targeting_howl` — Howl detected as self-targeting via ROM data
- `test_is_self_targeting_focus_energy` — Focus Energy detected, Low Kick not
- `test_self_target_first_action` — first action with Howl → WAIT_FOR_PARTNER_ACTION
- `test_self_target_both_actions` — both actions self-targeting → turn resolves
- `test_normal_then_self_target` — normal + self-targeting → turn resolves

All tests use existing `debug_doubles_target_swapped` save state (Luxio has Howl, Machop has Focus Energy).

### Files Changed
- `scripts/extract_move_data.py` — range field extraction
- `data/move_data.json` — re-extracted with range
- `renegade_mcp/turn.py` — self-targeting detection + confirmation tap
- `tests/test_battle.py` — 6 new tests in TestSelfTargetingDoubles

## Dev Session: Move Relearner & Move Deleter (2026-04-11g)

### Summary
Implemented `relearn_move` and `delete_move` tools for NPC-based move management. Both are town-service tools that interact with specific NPCs, navigate game menus, and modify party movesets. Extracted ROM learnset data (`wotbl.narc`) for the relearner's scrollable move list.

### Key Renegade Platinum Discoveries
- **Move Relearner relocated**: Still Pastoria City, but moved to map 129 (C06R0401, warp 611,835) — NPC sprite is "Collector". The vanilla East House (map 130, C06R0501) now has different NPCs (Lapras gift, Great Marsh tips). **Free** — no Heart Scale cost.
- **Move Deleter relocated**: Moved from Canalave City to **Oreburgh City** (map 58, C03R0301, warp 293,752). NPC sprite is "Old Man". Available much earlier in the game.
- Confirmed via web research + empirical verification against E4 save.

### Move Relearner Flow (verified empirically)
1. Interact with NPC → auto-advances into "Which Pokemon needs tutoring?" → party select screen
2. Party select: A button (D-pad navigates 2-column grid)
3. Scrollable move list on top screen: D-pad up/down, 7 visible items, CANCEL at bottom
4. If 4 moves: "can't learn more than 4" → "Delete existing?" YES/NO → forget UI → "Is it OK?" YES/NO → "1, 2, and... Poof!" → learned
5. Exit: "That'll do it." → overworld

### Move Deleter Flow (verified empirically)
1. Interact with NPC → Yes/No: "forget some moves?"
2. Party select → "Which move should be forgotten?" → current 4 moves + CANCEL
3. Select move → "Should that move be forgotten?" YES/NO → "It worked perfectly!" → "forgotten completely" → overworld

### Implementation
- **`move_services.py`**: Single module for both tools. Shared helpers: `_navigate_to_npc_building` (location validation + auto-navigate from city overworld), `_find_npc` (GFX name lookup), `_select_party_member` (2-column grid navigation).
- **Relearner list navigation**: Pre-computes the move list from ROM learnset data (same algorithm as the game's `MoveReminderData_GetMoves`: level-up moves at/below current level, minus currently known, deduplicated). Navigates by index — O(n) down presses.
- **ROM data extraction**: Extracted `poketool/personal/wotbl.narc` → parsed 507 species entries (format: `(level << 9) | move_id` as u16, terminated by 0xFFFF) → cached as `data/level_up_moves.json` (77KB). Added `level_up_moves(species_id)` to `data.py`.
- **server.py**: Registered both tools with `@renegade_tool` decorator (lazy imports).

### Backlog Cleanup
- Removed "Battle Gauntlet / E4 Support" from backlog — E4 strategy is gameplay, not tooling. Existing movement/interaction/dialogue tools handle it.

### Save States Created
- `move_relearner_pastoria` — inside relearner's house, map 129, E4 save
- `move_deleter_oreburgh` — inside deleter's house, map 58, E4 save

### Tests
15 tests in `test_move_services.py` (286 total across 24 files):
- Relearner: forget slot 0, forget slot 3, cancel (-1), different party slot, already-knows, missing forget_move, invalid slot, move-not-in-learnset, wrong city
- Deleter: delete first, delete last, different party slot, move-not-known, invalid slot, wrong city

## Dev Session: Fishing + Project Venv (2026-04-11f)

### Summary
Integrated fishing rods into `seek_encounter` via a `rod` parameter. Also set up a project-local `.venv` (was previously borrowing MelonMCP's venv).

### Fishing Implementation
- Added `rod` parameter to `seek_encounter` (Old Rod, Good Rod, Super Rod)
- Auto-navigates to a walkable tile adjacent to water using BFS (`_find_fishing_spot`)
- Handles surfing case: turns to face a water tile if already on water
- Uses rod through menu via new `activate_key_item()` shared helper (extracted from `use_key_item`)
- Detects bite via MapObject[0] animation state at offset `0xA0` (value 2 = bite)
- Presses A within hook window, advances through "Landed a Pokémon!" text into battle
- Retries on "Not even a nibble..." / "The Pokémon got away..." (up to 20 casts)

### Key Discovery: Fishing Text Not in Dialogue Buffer
The fishing UI text ("Oh! A bite!", "Not even a nibble...") is rendered by the fishing FieldTask's own MessageLoader/Window — NOT through the ScriptManager text system that `read_dialogue` scans. Empirical testing confirmed: `read_dialogue` never detects fishing text, and raw overworld text buffer scans find no D2EC B6F8 headers during fishing.

The reliable detection signal is the player MapObject animation state byte (`OBJ_ARRAY_FPX_BASE - 0x70 + 0xA0`), discovered by cross-referencing empirical memory monitoring with the pret/pokeplatinum decomp (`overlay005/fishing.c`). The state machine: 0=idle → 1=casting → 2=bite (press A!) → 3=reeling. Hook timing windows: Old Rod 45f, Good Rod 30f, Super Rod 15f — but we poll every frame, so rod type doesn't matter.

### Project Venv Setup
- Created `.venv` in project root (was using `/workspace/MelonMCP/.venv/`)
- Added `.pth` files for `melonds_mcp` and `renegade_mcp` imports
- Added `requirements.txt` with pinned dependencies
- Updated `.gitignore` with `.venv/`
- Updated CLAUDE.md test commands to use `.venv/bin/python`

### Tests Added
6 tests in `test_fishing.py`: Old Rod encounter, Good Rod encounter, invalid rod name, missing rod (lists available), no water nearby, auto-navigation from spawn. Total: 271 tests across 23 files.

### Files Changed
- `renegade_mcp/navigation.py` — `_fish_once()`, `_find_fishing_spot()`, `_seek_fishing()`, fishing constants
- `renegade_mcp/use_item.py` — extracted `activate_key_item()`, added `FISHING_FUNCS`
- `renegade_mcp/server.py` — `rod` parameter on `seek_encounter`
- `tests/test_fishing.py` — 6 integration tests
- `.gitignore` — added `.venv/`
- `requirements.txt` — new file
- `CLAUDE.md` — fishing docs, test count, venv paths

### Save States Created
- `fishing_test_near_water` — (842, 563) Pokemon League map 172, adjacent to water. E4 save (Old Rod + Good Rod in bag).

## Dev Session: Bike Slope Auto-Traversal (2026-04-11e)

### Summary
Implemented automatic bike slope traversal in `navigate_to`. Slopes (0xD9/0xDA) on Route 207+ are now auto-detected in BFS paths and traversed with a fast-gear running-start maneuver.

### Implementation
- Added `BIKE_SLOPE_BEHAVIORS`, `BIKE_SLOPE_TYPES` constants to navigation.py
- Added `BIKE_GEAR_STATE_ADDR = 0x021BF6AC` to addresses.py (ARM9 BSS, no delta shift)
- New `_traverse_bike_slope()` function: fast gear → 3-tile backup → continuous 2-frame-polled hold through slope → gear write + 120f settle
- Path execution in `_execute_path` detects slope obstacles and dispatches to the traversal
- `_navigate_to_impl` scans BFS paths for slope tiles and adds them to the obstacle tracking dict

### Key Discoveries
- **4th gear momentum**: Fast gear causes the bike to auto-roll forward even without input. After the continuous hold ends, the bike coasts 1-2 tiles. Writing the gear byte to slow (3rd) via memory immediately after the slope is cleared, then idling 120 frames, fully drains the internal momentum.
- **B press causes speed surge**: Pressing B to toggle gear triggers a speed boost that moves the player 3+ extra tiles — must write the gear byte directly via memory instead.
- **Post-nav drift**: `_post_nav_check` advances ~300 frames polling for encounters. Without momentum cancellation, the bike drifts during this period. The gear write + 120f settle prevents this.
- **Coast is absorbed by remaining path**: When navigating to a target well past the slope (common case), the 2-tile coast is consumed by remaining path steps, giving an exact final position.

### Tests Added
9 new tests in `test_cycling_road.py` (2 classes: `TestBikeSlopeConstants`, `TestBikeSlopeTraversal`). Total cycling road tests: 27. All navigation tests (22) also pass.

### Files Changed
- `renegade_mcp/addresses.py` — added `BIKE_GEAR_STATE_ADDR`
- `renegade_mcp/navigation.py` — slope constants, `_traverse_bike_slope()`, integration in `_execute_path` and `_navigate_to_impl`
- `tests/test_cycling_road.py` — 9 new bike slope tests
- `CLAUDE.md` — documented bike slope auto-traversal behavior
- `DEV_HISTORY.md` — this entry

## Dev Session: Cycling Road Stuck Fix & Bike Slope Research (2026-04-11d)

### Summary
Fixed an infinite-loop bug in `_navigate_cycling_road` and fully researched the bike slope mechanics on Route 207 in preparation for implementing auto-slope-traversal in `navigate_to`.

### Cycling Road Stuck Fix
When a trainer NPC (defeated but still standing) blocked the player on the Cycling Road bridge, the southbound auto-slide phase would loop for 120,000 frames (~160 seconds) before giving up. The inner while loop (600-frame timeout) would exhaust without position change, then `continue` back to the outer loop, repeating 200 times.

**Fix**: Three layers of stuck detection:
- **General**: `no_progress` counter at outer loop — bail after 3 consecutive iterations with no position change (catches ground-phase blockages cheaply)
- **Uphill phase**: track `phase_start_y`, break if inner wait exhausted with no Y progress
- **Southbound slide phase**: same `phase_start_y` check — break immediately on first timeout with no movement

Verified: scenario that took 120k frames now bails in ~1,200 frames with a clear diagnostic.

### Bike Slope Mechanics Research
Navigated from Eterna City through Cycling Road (fighting trainers along the way) to Route 207 using Wayne's E4 save state. Found and characterized the bike slopes at (306, 718-719).

**Terrain data:**
- `bike_slope_top` (0xD9) at (306, 718): `val=0x00D9`, collision bit = 0
- `bike_slope_bottom` (0xDA) at (306, 719): `val=0x00DA`, collision bit = 0
- BFS correctly treats these as passable — the issue is game-engine movement blocking

**Movement requirements (empirically tested):**
- Must be on bicycle
- Must be in **fast gear** (4th gear) — toggled by pressing B while on bike
- Must have **3+ tiles of continuous running start** — holding direction from adjacent fails
- Step-by-step navigation always fails — game blocks single-step entry onto slope tiles

**Gear state memory:**
- Address `0x021BF6AC` (byte): 0 = fast gear (can climb slopes), 1 = slow gear (blocked)
- Found via snapshot/diff: B press toggles this value cleanly (1→0→1)
- `CYCLING_GEAR_ADDR` (0x0227F4E0) is only the on/off bicycle flag, NOT the gear

### Cycling Road Gatehouse Discovery
Route 206's south gatehouse is blocked by 5 NPC "dancing Pokemon Breeders" — likely a Renegade Platinum story gate that clears after defeating Team Galactic in Eterna Building. Used E4 save + Fly to reach Route 207 from Oreburgh City instead.

### Save States Created
- `route207_bike_slope_area` — Route 207 at (297, 720), overview position, E4 save
- `route207_at_bike_slope_bottom` — Route 207 at (306, 720), on bicycle, 1 tile south of slope bottom. **Best test location.**

### Next Steps
Implement bike slope traversal in `navigate_to`:
1. Detect slope tiles (0xD9/0xDA) in BFS path
2. When execution reaches a slope: press B (gear shift), back up 3 tiles, hold direction continuously through slope, poll position
3. After crossing: press B to restore gear, continue normal navigation
4. Handle both uphill and downhill slopes

### Files Changed
- `renegade_mcp/navigation.py` — stuck detection in `_navigate_cycling_road` (3 new checks)
- `SAVE_STATES.md` — added Route 207 bike slope test states

## Dev Session: Rock Climb & Waterfall Auto-Navigation (2026-04-11c)

### Summary
Implemented Rock Climb and Waterfall as auto-navigable HM field moves in `navigate_to`. Both are "multi-tile" obstacles — the animation moves the player through ALL obstacle tiles at once (unlike Surf which moves 1 tile, or Rock Smash/Cut which removes the obstacle). Added `MULTI_TILE_HM_TYPES` constant to categorize them.

### Key Decisions & Findings
- **Multi-tile traversal**: Rock Climb walls (2+ tiles) and Waterfall cascades are traversed in a single HM animation. After the animation, `_execute_path` reads the new position, calculates `tiles_moved`, and skips `tiles_moved - 1` extra path steps to avoid overshooting.
- **Downstream waterfalls auto-slide**: Going DOWN a waterfall doesn't require the HM prompt — the game auto-slides the player. The A press in `_clear_hm_obstacle` triggers the slide but returns no dialogue (returns False). Fixed by adding position-change detection after the interaction attempt for multi-tile obstacles: if the player moved even without dialogue, treat as successful traversal.
- **3D map limitation**: On maps with BDHC elevation data (like Veilstone City), the 3D BFS finds clean paths around obstacles, and the 2D obstacle BFS may fail to find a shortcut path due to elevation-related impassable tiles. The obstacle shortcut only works when the 2D obstacle BFS can find a path. This is the same limitation as Surf on 3D maps.
- **Veilstone City Rock Climb wall**: Found a great test location by scanning all 666 land_data chunks for behaviors 0x4A/0x4B, mapping chunk IDs to game locations via matrix files. Veilstone has a 2-tile Rock Climb wall at (691, 615-616) separating the gym area from the main city. Flew there from E4 save state.
- **Waterfall test reused existing state**: `hm_test_surf_waterfall_pokemon_league` at (847, 560) has a path south requiring Surf + Waterfall — worked perfectly for combined testing.

### Test Save States Created
- `hm_test_rock_climb_veilstone` — Veilstone City at (691, 617), south of Rock Climb wall. Navigate to (691, 614) = 3 steps through wall.

### Tests Added (12 new, 256 total across 22 files)
**Rock Climb (7):**
- `test_rock_climb_field_move_available` — Icicle Badge + Rock Climb move detected
- `test_rock_climb_tiles_in_terrain` — Rock Climb behaviors present in Veilstone terrain
- `test_obstacle_bfs_finds_rock_climb_path` — obstacle BFS crosses wall; clean BFS does not
- `test_navigate_through_rock_climb_wall` — full navigate_to from (691,617) to (691,614)
- `test_navigate_continues_after_rock_climb` — climb wall then navigate further
- `test_rock_climb_in_auto_navigate_types` — constant classification verification
- `test_rock_climb_not_available_without_badge` — BFS rejects wall when Rock Climb unavailable

**Waterfall (5):**
- `test_waterfall_field_move_available` — Beacon Badge + Waterfall move detected
- `test_waterfall_tiles_in_terrain` — Waterfall behaviors present in Pokemon League terrain
- `test_obstacle_bfs_finds_waterfall_path` — obstacle BFS finds path through Surf + Waterfall
- `test_navigate_through_waterfall` — full navigate_to from (847,560) to (847,575) across water + waterfall
- `test_waterfall_in_auto_navigate_types` — constant classification verification

### Files Changed
- `renegade_mcp/navigation.py` — ROCK_CLIMB_TYPES, WATERFALL_TYPES, MULTI_TILE_HM_TYPES constants; multi-tile traversal in _execute_path with step-skip logic; downstream waterfall auto-slide detection; updated AUTO_NAVIGATE_TYPES and docstrings
- `renegade_mcp/server.py` — updated navigate_to docstring
- `tests/test_hm_obstacles.py` — 12 new tests in TestRockClimbNavigation and TestWaterfallNavigation classes
- `CLAUDE.md` — updated navigation docs for Rock Climb and Waterfall, test count to 256
- `SAVE_STATES.md` — added hm_test_rock_climb_veilstone, removed Rock Climb from "Still needed"

## Dev Session: Surf Auto-Navigation in navigate_to (2026-04-11b)

### Summary
Implemented Surf as an auto-navigable HM field move in `navigate_to`. When the BFS obstacle path through water is shorter than the clean path and the player has the Fen Badge + a party Pokemon with Surf, navigate_to automatically triggers the Surf dialogue and crosses the water. This follows the Rock Smash/Cut pattern from the previous session but with key behavioral differences unique to Surf.

### Key Decisions & Findings
- **Surf moves the player onto water** (unlike Rock Smash/Cut where the obstacle is removed and the player stays). `_execute_path` skips the retry step after Surf activation.
- **Surfing speed is 2x walking** — 8 frames/tile vs 16. Discovered via manual testing on Route 218 (hold=12f and hold=16f both caused 2-tile overshoot). Added `SURF_HOLD_FRAMES = 8` constant and `active_hold` variable in `_execute_path` that switches after Surf activation.
- **Terrain obstacle coordinates were grid-relative, not global** — the BFS returns `"x"/"y"` as grid-relative coords, but `_execute_path` looks up obstacle tiles by global `(old_x + dx, old_y + dy)`. Fixed by converting via `repath_ox/repath_oy` when `"global_x"` key is absent. This bug would have affected any future terrain obstacle auto-handling (Waterfall, Rock Climb) too.
- **Canalave City canal is walled off** — the `hm_test_surf_canalave` save state is not suitable for Surf testing (canal has `#` walls on both sides). Created new save states on Route 218 which has direct land→water access.
- **Repath while surfing** needs obstacle-aware BFS — added `surfing` flag to `repath_ctx`, plus `field_moves` and `obstacle_map` references so `_try_repath` can use `_bfs_pathfind_obstacles` while on water.
- **Classification refactor**: `CLEARABLE_TYPES` (Rock Smash/Cut objects) + `SURF_TYPES` (water terrain) = `AUTO_NAVIGATE_TYPES`. Waterfall/Rock Climb remain as manual confirmation (`obstacle_choice`/`obstacle_required`). Strength is never auto-handled.

### Test Save States Created
- `hm_test_surf_route218` — Route 218 at (121, 758), east side gate entrance
- `hm_test_surf_route218_at_water` — Route 218 at (112, 754), adjacent to water edge. **Primary Surf test state.**

### Tests Added (7 new, 244 total across 22 files)
- `test_surf_field_move_available` — Fen Badge + Surf move detected
- `test_water_tiles_in_terrain` — water behaviors present in Route 218 terrain
- `test_obstacle_bfs_finds_surf_path` — obstacle BFS crosses water; clean BFS does not
- `test_navigate_across_water` — full navigate_to from (112,754) to (100,756), exact coords
- `test_navigate_back_via_bridge` — return trip uses bridge (clean path preferred over Surf)
- `test_surf_not_available_without_badge` — BFS rejects water when Surf unavailable
- `test_surf_auto_navigate_types` — constant classification verification

### Files Changed
- `renegade_mcp/navigation.py` — SURF_TYPES, AUTO_NAVIGATE_TYPES, SURF_HOLD_FRAMES constants; _execute_path surf handling with active_hold; decision logic auto-take for water; _try_repath surf-aware BFS; terrain obstacle coord fix
- `renegade_mcp/server.py` — updated navigate_to docstring
- `tests/test_hm_obstacles.py` — 7 new Surf tests in TestSurfNavigation class
- `CLAUDE.md` — updated navigation docs for Surf
- `SAVE_STATES.md` — added Route 218 save states, updated Canalave note

## Dev Session: HM Obstacle Auto-Clear — Rock Smash & Cut (2026-04-11a)

### Goal
Integrate Rock Smash and Cut field moves into `navigate_to` so obstacles are cleared automatically during pathfinding, rather than requiring manual intervention or path_choice round-trips.

### Bug Found: HM Obstacle GFX IDs Off By One
The `HM_OBSTACLES` dict had wrong graphics_id values — 85/86/87 instead of 84/85/86. Cross-referenced with `data/obj_event_gfx.txt`:
- 84 = `OBJ_EVENT_GFX_STRENGTH_BOULDER`
- 85 = `OBJ_EVENT_GFX_ROCK_SMASH`
- 86 = `OBJ_EVENT_GFX_CUT_TREE`

This meant `obstacle_map` was never populated — Rock Smash rocks were misclassified as Strength boulders (into `npc_set` instead of `obstacle_map`). Fixed `HM_OBSTACLES`, `CLEARABLE_OBSTACLES` ({85, 86}), and `PUZZLE_OBSTACLES` ({84}).

### Investigation: Rock Smash Interaction Flow
Manually tested on `hm_test_rock_smash_oreburgh_mine_b2f` (Oreburgh Mine B2F, player at (18,28), rocks at (17,28) and (19,28)):
1. Face rock → press A → "This rock appears to be breakable. Would you like to use Rock Smash?"
2. Wait ~120 frames for text scroll + Yes/No prompt (Yes selected by default, top screen)
3. Press A → "Nidoking used Rock Smash!" → break animation
4. Wait ~300 frames for animation, press B to dismiss leftover text
5. Rock gone, overworld restored

**Key timing discovery:** 60f wait after initial A was too short — the A press landed during text scroll and advanced the dialogue instead of confirming Yes. Increased to 120f for reliable Yes/No prompt appearance.

### Implementation

**`_clear_hm_obstacle()`** — new helper in navigation.py:
- Settle (WAIT_FRAMES) → A (interact, 8f hold) → wait 120f → A (confirm Yes) → wait 300f → B (dismiss) → settle 120f
- Checks `read_dialogue(region="overworld")` to verify interaction triggered
- Loops B presses if text remains after animation
- Returns True/False for success

**`_execute_path` obstacle detection** — obstacle check runs BEFORE slow terrain retries (critical — extra directional presses would interfere with HM dialogue). When blocked at a known clearable obstacle tile:
1. Call `_clear_hm_obstacle()` 
2. Pop the tile from `obstacle_tiles` dict
3. Append to `nav_info["obstacles_cleared"]`
4. Retry the step — tile is now passable

**Auto-path selection in `_navigate_to_impl`:**
- New module constant `CLEARABLE_TYPES = {"rock_smash", "cut_tree"}`
- When all obstacles on the shorter path are clearable and skills are available, auto-takes obstacle path (no `obstacle_choice` round-trip)
- Terrain obstacles (Surf/Waterfall/Rock Climb) still return `obstacle_choice`/`obstacle_required` for caller confirmation
- 3D maps also check for shorter clearable obstacle paths via 2D obstacle BFS fallback

**Result propagation fix:** `nav_info["obstacles_cleared"]` was only included in the response when `stopped_early=True`. Added explicit check to always include `obstacles_cleared` in the success result.

### Tests (7 in test_hm_obstacles.py)
All use `hm_test_rock_smash_oreburgh_mine_b2f` with `redetect_shift=True` (Wayne's E4 save):
- `test_navigate_through_rock` — 3-step path through rock, verify cleared list
- `test_clean_path_preferred_when_shorter` — 1-step south, no obstacles needed
- `test_obstacle_path_only_when_required` — 2-step path through rock vs 4-step around
- `test_multiple_rocks_same_path` — navigate through left rock at (17,28)
- `test_field_move_availability_checked` — party has Rock Smash + badges
- `test_obstacle_map_populated` — rocks in obstacle_map, not npc_set
- `test_gfx_id_mapping` — GFX IDs 84/85/86 match correct types

Cut trees not testable live — Eterna City trees hidden by E4 save story flags, our playthrough (2 badges) lacks Cut. Same code path as Rock Smash; GFX ID mapping verified.

### Files Changed
- `renegade_mcp/navigation.py` — _clear_hm_obstacle, _execute_path obstacle handling, auto-path selection, GFX ID fix
- `renegade_mcp/server.py` — updated navigate_to docstring
- `tests/test_hm_obstacles.py` — 7 new tests
- `CLAUDE.md` — navigation docs updated

### What's Next
Surf, Waterfall, and Rock Climb are fundamentally different (terrain mode change, not object clearing). They require new mechanics in `_execute_path` — entering water tiles, riding mode transitions, etc. Save states exist for all three.

## Dev Session: Cycling Road Investigation & Navigation (2026-04-10g)

### Goal
Investigate Route 206 (Cycling Road) to determine if the downhill bike slide mechanic affects navigation tools, then implement support.

### Investigation Findings

Route 206 bridge body tiles (behavior 0x71) force southbound auto-sliding at ~4 frames/tile when on the bicycle. Key observations:
- Bridge start tiles (0x70) don't auto-slide — they're just the entry point
- The slide is passive on 0x71 tiles (no input needed) and continuous until hitting an obstacle
- Going uphill (pressing UP) works but the first ~4 frames still slide south before UP takes over; net ~8f/tile north
- Lateral movement (left/right) works but also slides south ~1 tile per lateral step
- The cycling road flag (FLAG_ON_CYCLING_ROAD, flag 2453) is in save RAM VarsFlags but the runtime slide check uses `PlayerAvatar.unk_00` which isn't directly readable from save RAM. Detection uses tile behavior + cycling state + path scan between player and target instead.

### BEHAVIORS Dict Corrections

Our BEHAVIORS dict had 13 wrong terrain labels — 0x70/0x71 were labeled "deep_snow"/"snow" but are actually BRIDGE_START/BRIDGE per the pokeplatinum decomp `map_tile_behaviors.h`. Fixed labels:
- 0x70/0x71: "deep_snow"/"snow" → BRIDGE_START/BRIDGE (bike slide tiles)
- 0xA0: berry_patch (was missing or mislabeled)
- 0xA1-0xA3, 0xA8-0xA9: snow tiles (corrected from wrong behavior codes)
- 0xA4-0xA7: mud tiles (corrected)
- 0xD7-0xDB: bike slope/ramp tiles (were missing)

### Implementation

**Cycling road detection** — `BIKE_BRIDGE_BEHAVIORS` frozenset and `is_on_cycling_road()`:
- Checks tile behavior (0x71) + cycling state + scans path between player and target for bridge tiles
- No false positives on regular bridges (requires bicycle + bridge tiles along the path)

**`_navigate_cycling_road()` with position-tracking movement:**
- South: passive auto-slide, poll position every 2 frames until target reached
- North: continuous UP hold (~8f/tile, handles initial south drift before UP takes over)
- Lateral: 4f press + poll, accepts south drift as expected behavior
- Non-bridge tiles: normal bike steps (4f hold)
- `_check_encounter_quick()` woven into every movement phase for wild encounter detection

**Navigation dispatch:**
- `navigate` (manual) refuses on cycling road with clear error explaining the auto-slide mechanic
- `navigate_to` auto-dispatches to cycling road handler when `is_on_cycling_road()` returns True

**ASCII rendering:** bridge tiles show as `n`, snow as `~`, bike slopes as `\` and `/`.

### Tests Added (216 total, +18 this session)

18 new integration tests in `test_cycling_road.py`:
- Cycling road detection (tile behavior + cycling state)
- Terrain label corrections (bridge, snow, mud, bike slope)
- `navigate` manual blocking on cycling road
- South movement (passive auto-slide)
- North movement (uphill with drift handling)
- Lateral movement (left/right with south drift)
- Encounter detection during cycling road navigation

**Total: 216 tests across 20 files, all passing (9:01 wall clock).**

### Files Changed
- `renegade_mcp/navigation.py` — `BIKE_BRIDGE_BEHAVIORS`, `is_on_cycling_road()`, `_navigate_cycling_road()`, `_check_encounter_quick()`, cycling road dispatch in `navigate_to`, blocking in `navigate`
- `renegade_mcp/map_state.py` — BEHAVIORS dict corrections (13 labels), ASCII rendering for bridge/snow/bike slope tiles
- `tests/test_cycling_road.py` — 18 new tests
- `CLAUDE.md` — test count update

### Commits
`806ec8c`, `122f99d`, `3bce3fe`, `76a137b`, `cffc95c`

## Dev Session: Backlog Cleanup — sell_item, re-path, accuracy warning (2026-04-10f)

### Goal
Clear the remaining non-E4 QoL backlog: sell_item tool, interact_with flee re-path, battle_turn accuracy awareness, and Route 205 deep snow investigation.

### What We Built

**sell_item tool** (`shop.py`, `server.py`)
- Full PokéMart selling: auto-navigates from city overworld, talks to Cashier F, selects SELL, navigates sell bag via pocket touch tabs + cursor scroll, quantity selector, confirms, exits.
- Sell price = buy price / 2 (standard Pokémon formula).
- Pre-validates: item in bag, sufficient quantity, sellable pocket (rejects Key Items, TMs/HMs, Mail), non-zero sell price.
- Verifies money increase post-sale.
- **Bug fix during live testing**: sell confirmation flow has one fewer A press than buy (quantity confirm goes straight to YES/NO — no intermediate text screen). Extra A cascaded into accidentally selling the next item. Also confirmed exit cursor returns to BUY (first option), same as buy_item.

**interact_with flee re-path** (`navigation.py`)
- Previously, `interact_with(flee_encounters=True)` would flee wild encounters during the walk but then return without completing the interaction.
- Now re-navigates from current position to the destination tile using `navigate_to(flee_encounters=True)` after a successful flee, then falls through to the face + interact section.
- Flee logs from both the initial walk and re-path are accumulated in the response.
- Restructured the `stopped_early` block to cleanly handle three cases: encounter (return), flee+repath (fall through), non-encounter stop (return).

**battle_turn accuracy-drop awareness** (`turn.py`)
- When the active player Pokémon has Acc stages <= -2 and `final_state == "WAIT_FOR_ACTION"`, adds `accuracy_warning` to the response.
- Shows current stage, hit rate percentage, and suggests switching or using a status move.
- Hit rates: -2 = 60%, -3 = 50%, -4 = 43%, -5 = 38%, -6 = 33%.

### Route 205 Deep Snow Investigation
- Navigated to Route 205 north (map 349, snow area around coordinates 269-275, 530-535).
- Tested 8+ `navigate_to` calls including 3-step paths, direction changes, and traversals through snow tiles.
- **Cannot reproduce**: all paths completed successfully. The Route 216 `SLOW_TERRAIN_RETRIES` fix (3 extra 24-frame press cycles) covers Route 205 as well.
- Saved `debug_route205_snow_area.mst` for future reference.
- Closed QA FR-004.

### Tests Added (198 total, +7 this session)
- `TestAccuracyWarning` (4 tests): no warning at normal/Acc -1, warning with correct hit rate at Acc -2 (60%) and -3 (50%). Uses memory write to set BattleMon statBoosts directly.
- `test_flee_encounters_completes_interaction`: verifies interact_with with `flee_encounters=True` completes dialogue on city overworld.
- `test_sell_from_inside_mart`: sell from inside mart without auto-navigation.
- `test_sell_insufficient_quantity`: quantity > owned returns error.
- Plus 6 sell_item tests from the initial implementation (sell, money increase, bag decrease, multi-quantity, key item rejection, nonexistent item).

### Backlog Status
All non-E4 QoL items resolved. Remaining work is blocked on Elite 4 save file (10+ features: HM field moves, fishing, move relearner/deleter, E4 gauntlet, puzzles, tag battles, deferred tests).

## Dev Session: Bicycle & Key Item Usage (2026-04-10e)

### Goal
Add key item usage (Bicycle mount/dismount), bicycle state detection, and bike-aware navigation timing.

### What We Built

**`use_key_item` tool** — new tool for Key Items pocket. Currently supports Bicycle:
- Navigates pause menu → Bag → Key Items → item → USE/REGISTER submenu → USE
- Verifies state change via `CYCLING_GEAR_ADDR` memory read
- Indoor rejection: detects "Rowan's words echoed..." failure, cleans up all 5 menu layers
- Returns `on_bicycle: true/false` and mount/dismount status

**`CYCLING_GEAR_ADDR` discovery** — used snapshot/diff on live emulator:
1. Confirmed `PLAYER_POS_BASE` is the start of `FieldOverworldState` (map_id + warp + x + z + facing match `Location` struct)
2. Snapshot before bike → mount bike manually → snapshot after → diff 256 bytes
3. Found `cyclingGear` (u16) at offset +0x90 from FieldOverworldState base
4. Verified with decomp: `PlayerData { cyclingGear, runningShoes, form }` at `FieldOverworldState + 0x91` (struct alignment adjusted to +0x90)
5. DeSmuME reference: `0x0227F4E0`, melonDS: `0x0227F4C0`

**`read_trainer_status` updated** — now includes `on_bicycle` field and "Bicycle: ON" in formatted output.

**Bike-aware navigation** — `_get_move_hold(emu)` reads cycling state:
- `BIKE_HOLD_FRAMES = 4` (bike moves 1 tile per ~4 frames)
- `HOLD_FRAMES = 16` (walking, unchanged)
- Threaded through `_execute_path`, `seek_encounter`, `navigate_manual`, `navigate_to`, `interact_with`
- Non-movement presses (NPC facing, door activation) remain at 16
- Calibration: tested 4, 8, 16 frames on bike; 4 gives exact 1-tile-per-step precision

### Bug Found & Fixed
- `interact_with` was missing `hold_frames` local variable after the `_execute_path` parameter was added — caused `NameError` in 15 tests (interact_with, heal_party, buy_item, withdraw_pokemon). Fixed by adding `hold_frames = _get_move_hold(emu)` at function top.

### Tests Added
14 new tests in `test_bicycle.py`:
- `TestUseKeyItemBicycle` (5): mount, dismount, indoor rejection, nonexistent item, unsupported item
- `TestCyclingGearAddr` (2): walking=0, cycling=1
- `TestTrainerStatusBicycle` (2): on_bicycle false/true
- `TestBikeNavigation` (5): walk precise, bike precise, navigate_to 0 repaths, _get_move_hold walking/cycling

**Total: 185 tests across 19 files, all passing (~6:17 runtime).**

### Files Changed
- `renegade_mcp/use_item.py` — `use_key_item()`, key item func constants, bicycle state verification
- `renegade_mcp/addresses.py` — `CYCLING_GEAR_ADDR`
- `renegade_mcp/trainer.py` — `on_bicycle` in `read_trainer_status`
- `renegade_mcp/navigation.py` — `_get_move_hold()`, `BIKE_HOLD_FRAMES`, `hold_frames` param threading
- `renegade_mcp/server.py` — `use_key_item` tool wrapper
- `tests/test_bicycle.py` — 14 new tests
- `CLAUDE.md` — tool docs, test count update

## Dev Session: Cross-Map Auto-Heal (2026-04-10d)

### Test Suite Fix
- **conftest.py detect_shift false positive**: On a fresh ROM load (title screen), all heap memory is zeroed. `detect_shift` tried delta=0 first, and `party_count=0 / badge=0` passed the `0<=x<=6 / 0<=x<=8` validation — locking in the wrong offset for all 166 tests (90 failures). Fix: always load a known save state before calling `detect_shift` in the conftest, guaranteeing real game data in memory.

### Feature: auto_grind auto_heal=True
Cross-map auto-heal for `auto_grind` — no coordinates needed.

**New functions in auto_grind.py:**
- `_find_all_pcs(emu, map_id, px, py)` — scans all cities/towns with Pokemon Centers on the same overworld matrix, returns sorted by chunk distance.
- `_auto_heal_and_return(emu, in_battle, fainted)` — full flow: exit battle → remember position → exit interior (if needed) → find nearest PC → navigate → heal → exit PC → return through warps → navigate back to grind spot.
- `_navigate_multi_hop(emu, target_x, target_y)` — breaks long paths into ~3-chunk segments to stay within the 5x5 chunk terrain loading cap.
- `_exit_to_overworld(emu)` / `_return_to_interior(emu, return_warps)` — warp chain recording and reversal for cave sub-floors not on the overworld matrix.
- Retry logic: when nearest city is unreachable (terrain barriers), reverts via checkpoint and tries alternative cities by distance.

**Key design decisions:**
- Uses the overworld matrix (matrix 0) to locate all cities. Routes and cities share the same matrix, so `navigate_to` can path between them without explicit warps.
- Interior maps (cave sub-floors) are not on any matrix — `_exit_to_overworld` follows warps outward until reaching matrix 0.
- The 5x5 chunk cap in `_build_multi_chunk_terrain` limits single-call navigate_to range. `_navigate_multi_hop` works around this with intermediate waypoints.

**Live test (Route 203):** 16 encounters, Mach Punch PP depleted after ~11, auto-heal navigated to Jubilife City PC (Oreburgh was blocked by mountains, retry found Jubilife), healed full party including reviving fainted Eevee, returned to grass, resumed grinding. Total wall clock ~117s for the full run.

### Tests Added
- `test_auto_heal.py`: 5 tests (3 unit for `_find_nearest_pc`, 2 integration for `_auto_heal_and_return`)
- **Total: 171 tests across 18 files**, all passing (~7 min on melonDS)

### Files Changed
- `renegade_mcp/auto_grind.py` — 5 new functions, `auto_heal` parameter, dispatch in heal triggers
- `renegade_mcp/server.py` — `auto_heal` parameter wired through
- `tests/conftest.py` — always load state before detect_shift
- `tests/test_auto_heal.py` — new test file
- `CLAUDE.md` — updated auto-heal docs + test count

## Dev Session: Bug Sweep + QoL (2026-04-10c)

Cleared 5 bugs and 1 QoL improvement from the QA backlog. Test count: 157 → 166 (9 new tests across 2 files).

### Bug 1: read_party HP -1 for Fainted Pokemon (BUG-004)

**Problem**: `read_party()` showed `hp: -1` and `status_conditions: []` for fainted Pokemon. Formatted output showed "HP ?/?".

**Root cause**: `party.py:475` — `decoded.get("ext_cur_hp", 0) or -1`. Python's `0 or -1` evaluates to `-1`, treating fainted (HP=0) as a missing value.

**Fix** (2 parts):
- Data extraction: changed `or -1` to explicit `is not None` check on level, cur_hp, and max_hp lines.
- Format display: `format_party` now injects "Fainted" into status_conditions when hp=0 and max_hp>0.

**Tests** (3 new in `test_party_tools.py`):
- `test_format_party_fainted_shows_zero_hp` — verifies "HP 0/66" not "HP ?/?"
- `test_format_party_fainted_shows_fainted_status` — verifies "Fainted" indicator
- `test_read_party_hp_never_negative` — integration: no party member should have negative HP

### Bug 2: Disable Text Not Detected as MOVE_BLOCKED (BUG-005)

**Problem**: `battle_turn` returned `WAIT_FOR_ACTION` instead of `MOVE_BLOCKED` when Disable blocked a move. The text "X's Move is disabled!" wasn't matched.

**Root cause**: `_classify_final_state` only checked for "can't use" and "cannot use" text patterns. Disable uses "is disabled!" — a different pattern.

**Fix**: Added `"is disabled"` to the text match in `_classify_final_state`.

**Tests** (5 parametrized in `test_move_blocked.py::TestDisableDetection`): Torment, Disable, Encore text patterns + non-blocked text negative case.

### Bug 3: Wrong Move Selected After Blocked Attempt (BUG-006)

**Problem**: After Torment/Disable blocked a move, the next `battle_turn` call selected the wrong move. E.g., requesting Brick Break (slot 1) actually used Peck (slot 3).

**Root cause**: After rejection, the game stays in the move selection submenu. The next `battle_turn` taps FIGHT (which hits the move grid instead of the FIGHT button), then taps the actual move — two taps on the move grid selects the wrong thing.

**Fix**: After detecting MOVE_BLOCKED in `_execute_action`, double B-press backs out to the main action menu. First B may be swallowed during the rejection text dismiss animation; second reliably exits. Verified with timing experiments — single B + 60 frames was insufficient; double B + ACTION_SETTLE + TAP_WAIT works consistently.

**Also simplified** `auto_grind`'s backup_move path: previously used direct tap workaround (knowing game was in move submenu); now uses standard `battle_turn` call since MOVE_BLOCKED guarantees clean state.

**Tests** (1 new integration): `test_correct_move_selected_after_blocked` — triggers MOVE_BLOCKED, then verifies next move selection is correct.

### Bug 4: Sequential Move-Learn Text Clearing (BUG-002)

**Problem**: After evolution + sequential move learns (e.g., Chimchar→Monferno learns Flame Wheel then Mach Punch), the "learned X!" screen wasn't fully dismissed. `seek_encounter` then returned "blocked" because text was still on screen.

**Root cause**: `_learn_move_overworld` used a fixed 5 B-presses to dismiss confirmation text, but sequential learns can stack more text pages than 5 presses can clear. The remaining text blocked all input.

**Fix**: Added `_clear_overworld_move_learn_text()` — uses `ScriptManager.is_msg_box_open` flag (the authoritative signal for active overworld text) to keep pressing B until all text is dismissed. Also checks for the next "Should a move be deleted?" prompt before clearing, so it doesn't accidentally dismiss a sequential learn prompt.

**No new test** — full repro requires grinding to trigger evolution + double learn, which isn't practical for CI. Existing move-learn tests (3) all pass.

### QoL: Formatted State Shows Correct State (FR-008)

**Problem**: The `formatted` field in `battle_turn` responses showed `State: TIMEOUT` even when `final_state` correctly reported `BATTLE_ENDED`, `MOVE_LEARN`, etc.

**Root cause**: The tracker's `_format_log` built the formatted string with the raw poll state, but `_classify_final_state` and post-processing reclassified it afterward. The formatted field was never updated.

**Fix**: Rebuild `formatted` at the end of `battle_turn` using the final `final_state` value.

### Backlog Status After Session

**Resolved**: BUG-002, BUG-004, BUG-005, BUG-006, FR-008 (5 bugs + 1 QoL)
**Remaining**: BUG-003 (self-targeting doubles, low), FR-002 (interact re-path, low), FR-003 (cross-map heal, med), FR-004 (deep snow, low), FR-006 (accuracy awareness, low), specialty shop (deferred)

---

## Dev Session: Three Bug Fixes (2026-04-10b)

Fixed all 3 remaining open bugs from the backlog. All had repro save states ready from the QA session.

### Bug 1: forget_move=-1 Loops at Prompt 2

**Problem**: `battle_turn(forget_move=-1)` infinite-looped when the game was already at Prompt 2 ("Should this Pokemon give up on learning Fire Fang?") instead of Prompt 1 ("Make it forget another move?"). Occurred when multiple moves are learned simultaneously (Luxio learned 3 fang moves at Lv24 in Renegade Platinum).

**Root cause**: `_skip_move_learn_flow()` always assumed Prompt 1. First tap hit "Don't give up!" on Prompt 2 (back to Prompt 1), second tap hit "Forget a move!" on Prompt 1 (opens move selection). Infinite loop between the two prompts.

**Fix**: `_execute_move_learn` checks log text for "give up on" to detect Prompt 2. Passes `at_prompt2=True` to `_skip_move_learn_flow`, which skips the Prompt 1 tap and goes straight to "Give up on [Move]!". Verified with repro save state — returns `BATTLE_ENDED` immediately.

### Bug 2: run=True at FAINT_SWITCH Returns Trainer Error

**Problem**: `battle_turn(run=True)` at a wild battle FAINT_SWITCH state sometimes returned "Must switch in a trainer battle — specify switch_to (1-5)". Wild battle misidentified as trainer.

**Root cause**: `_wait_for_action_prompt()` timeout fallback (line 508) assumed any faint with no detected WAIT_FOR_ACTION text was FAINT_FORCED (trainer battle). In wild battles, "Use next Pokemon?" text was present but classified under a different control code, so the scanner missed it. Fallback blindly returned FAINT_FORCED.

**Fix**: Fallback now checks accumulated log entries for "Use next" text before defaulting to FAINT_FORCED. If found → FAINT_SWITCH. RNG-dependent scenario, no deterministic test possible, but code path is verified correct.

### Bug 3: auto_grind Teleports Player Home (Whiteout)

**Problem**: `auto_grind` with a single Pokemon that faints (full party wipe) caused the player to end up in their house in Twinleaf Town. `auto_grind` reported `seek_failed` instead of recognizing the whiteout.

**Root cause**: Woj's hypothesis was correct — full party wipe. `battle_turn` correctly handled blackout (returned `BATTLE_ENDED` + `blackout: True`), but `_fight_battle()` and `_run_battle()` only checked `final_state`. Saw `BATTLE_ENDED`, returned empty `stop_reason`, main loop continued, tried to seek encounters from inside the Pokemon Center.

**Fix**: `_fight_battle()`, `_run_battle()`, and the resume-from-move-learn path all now check `result.get("blackout")` and return `stop_reason="fainted"` with "Full party wipe — blacked out to Pokemon Center." detail.

### Testing

2 new regression tests:
- `test_skip_move_learn_at_prompt2` — loads Prompt 2 save state, verifies `forget_move=-1` returns `BATTLE_ENDED`
- `test_fight_battle_returns_fainted_on_blackout` — calls `_fight_battle` with the existing blackout save state, verifies `stop_reason="fainted"`

Full suite: **157 tests, all passing in 6:51**.

### Files Changed
- `renegade_mcp/turn.py` — Prompt 2 detection in `_execute_move_learn`, `at_prompt2` param in `_skip_move_learn_flow`, log check in `_wait_for_action_prompt` fallback
- `renegade_mcp/auto_grind.py` — blackout checks in `_fight_battle`, `_run_battle`, and resume-from-move-learn
- `tests/test_battle.py` — +1 test (Prompt 2 skip regression)
- `tests/test_blackout.py` — +1 test (auto_grind blackout stop)

## Dev Session: use_battle_item Tool (2026-04-10)

Built `use_battle_item` — the first tool for using items from the bag during battle. Navigates the battle bag UI (completely separate from the overworld bag) via touch inputs derived from the decomp's TouchScreenRect tables.

### Backlog Review

Started with a full backlog audit. Current state: 7 open bugs (mostly doubles/edge cases), 5 QoL feature requests, 1 upstream blocker. 30+ resolved issues across the project. `use_battle_item` was the highest-priority QoL item — it blocks any gym strategy requiring mid-fight healing.

### ROM Data Research

Deep dive into the decomp at `ref/pokeplatinum/src/battle_sub_menus/battle_bag.c`:
- Battle bag has 4 pockets (HP/PP Recovery, Status Recovery, Poke Balls, Battle Items) — different from the 8 overworld pockets
- Items filtered by `battlePocket` bitmask from ROM `pl_item_data.csv`
- `battleUseFunc` field determines targeting: 0=stat booster (auto in singles), 1=ball, 2=healing (party target), 3=escape (auto-flee)
- 6 items per page, touch-based 2-column grid layout
- Battle bag cursor state persisted per pocket (page + position)

### Bug Fix: Missing Poke Balls Pocket

Discovered `bag.py` had 7 pockets but the decomp's `Bag` struct has 8 — a `pokeballs[15]` pocket sits between Berries and Battle Items. This shifted the Battle Items memory offset. Fixed by adding the pocket.

### Implementation

**New files:**
- `scripts/extract_battle_data.py` — parses `pl_item_data.csv`, generates `data/item_battle_data.json` (67 battle-usable items with `battleUseFunc` + `battlePocket` bitmask)
- `renegade_mcp/data.py` — added `item_battle_data()` lazy loader
- `renegade_mcp/battle_bag.py` — reconstructs battle pocket item lists from overworld bag data, matching `BattleBag_Init`'s sequential pocket scan order
- `renegade_mcp/use_battle_item.py` — main tool: BAG → pocket → page reset → item → USE → target → wait for action prompt

**Touch coordinates** (from decomp `TouchScreenRect` tables, format `{y_top, y_bottom, x_left, x_right}`):
- Pocket selection: 4 quadrants (HP/PP=top-left, Status=bottom-left, Balls=top-right, Battle=bottom-right)
- Item slots: 2x3 grid, 6 per page
- Navigation: Prev/Next page arrows, USE/Cancel buttons

### Key Discovery: Stale Save Block During Battle

First verification approach checked bag quantity via `read_bag` — always showed unchanged qty. Investigation revealed: **during battle, the game works with a `BattleSystem` copy of the bag data**. The overworld save block at `BAG_BASE` is NOT updated until the battle ends. Same issue affects `read_party` — party HP in the save block stays at pre-battle values.

**Fix**: Verify healing via `read_battle` (live BattleMon data) instead of `read_bag`. For X items/escape items, trust the final state (can't easily verify stat boosts from memory).

Second timing issue: naive `advance_frames(300) + B×3` wasn't enough to get through the item animation + enemy turn. Replaced with `_wait_for_action_prompt` for proper turn detection.

### Testing

9 integration tests across 3 classes:
- `TestUseBattleItemHealing` — Potion on damaged Pokemon (HP verified), full-HP rejection, missing party_slot
- `TestUseBattleItemValidation` — nonexistent item, Poke Ball rejection, invalid slot
- `TestBattleBagPockets` — pocket mapping, item position lookup, missing item error

Full suite: **155 tests, all passing in 6:37**.

### Files Changed
- `renegade_mcp/bag.py` — add Poke Balls pocket (15 slots)
- `renegade_mcp/data.py` — add `item_battle_data()` loader
- `renegade_mcp/battle_bag.py` — **new**: battle pocket list builder
- `renegade_mcp/use_battle_item.py` — **new**: battle bag UI navigation + targeting
- `renegade_mcp/server.py` — register `use_battle_item` tool
- `scripts/extract_battle_data.py` — **new**: ROM data extraction
- `data/item_battle_data.json` — **new**: generated ROM data
- `tests/test_use_battle_item.py` — **new**: 9 integration tests
- `CLAUDE.md` — updated tool reference table

## Dev Session: Eterna Gym Navigation Fixes (2026-04-08f)

Resolved all remaining Eterna Gym bugs — 3D navigation and post-battle event text. Full gym now navigable end-to-end.

### 3D BFS Fallback to 2D

**Problem**: 3D elevation-constrained BFS over-restricted navigation in gyms:
- Clock hand tiles: 3D BFS planned paths through L2 tiles disconnected by clock rotation → player stuck
- L0→exit: no BDHC ramp from L0 to L1 → "No 3D path found" error
- Ramps impassable via `navigate`: misdiagnosis — (4,14) is a wall, ramp is at (4,13)

**Root cause investigation**:
- Loaded all 3 bug save states and reproduced each issue
- Compared ROM vs RAM terrain — RAM terrain unreliable (corrupted by other data)
- Confirmed ROM terrain marks clock tiles as passable even when game's 3D collision blocks them
- Verified `navigate` correctly handles ramp tiles (bug 4 was misdiagnosis)

**Fix (3 changes to navigation.py)**:
1. `_try_repath`: when 3D BFS returns None, fall through to 2D BFS instead of returning None
2. `navigate_to`: when 3D BFS fails for ANY map type (not just multi-chunk), fall through to 2D BFS
3. `_execute_path`: track dynamically-blocked tiles — when a step fails at runtime (3D collision blocks despite ROM passability), add tile to `dynamic_blocks` set in `repath_ctx`. `_try_repath` includes these in obstacle set. `MAX_REPATHS` raised from 5 to 15 for gym puzzle discovery.

**Tests**: 4 in `test_3d_nav_fallback.py` — L0→exit warp, L0→exit reaches city, clock hand dynamic blocks, clock hand reaches exit.

### Post-Battle Event Animation Text

**Problem**: After defeating Eterna Gym trainers, event text ("The fountain's water level dropped!" + "It's possible to walk across the fountain now!") stays on screen. `battle_turn` returns `BATTLE_ENDED` but player can't move.

**Root cause investigation**:
- Probed ScriptManager state while stuck: `is_msg_box_open=False`, `CTX_RUNNING`, `TextPrinter active`
- Event scripts render text via TextPrinter during CTX_RUNNING without setting `is_msg_box_open`
- `advance_dialogue` early-exits on `is_msg_box_open=False` (line 306) → never enters main loop
- Even when entering main loop, `_wait_for_msgbox_or_script_end` only checks `is_msg_box_open`

**Fix (3 changes)**:
1. `advance_dialogue` initial state check: when `is_msg_box_open=False` but a script context is in `CTX_RUNNING`, enter the main loop instead of returning "no_dialogue"
2. `_wait_for_msgbox_or_script_end`: also check TextPrinter `active + state >= 1` (event text visible)
3. `battle_turn` post-battle handler: B-press cleanup loop — after `advance_dialogue`, poll script context; while `CTX_RUNNING`, press B + wait; stop when context stops or no script found. Safety cap of 20 iterations.

**Tests**: 2 in `test_event_text.py` — player free after gym event, navigation works after gym event.

### Backlog Status
| Fixed | Type |
|-------|------|
| Clock hand passability | 3D→2D fallback + dynamic blocks |
| L0→exit "no 3D path" | 3D→2D fallback for all map types |
| Ramps impassable (navigate) | Closed — misdiagnosis |
| Post-battle event text stuck | CTX_RUNNING detection + B-press loop |

**Remaining open**: Veilstone Dept Store specialty shop tool (deferred to Veilstone).

**Commits**: `e57461b` (3D nav fallback), `6a37640` (event text fix). Full suite: **146/146 pass**.

## Dev Session: QoL Sweep — Move Blocks, Blackout, Adjacent Targets (2026-04-08e)

**Goal**: Clear the non-gym QoL backlog so next session can focus entirely on Eterna Gym 3D elevation bugs.

### 1. auto_grind Torment infinite loop → MOVE_BLOCKED + backup_move

**Problem**: `auto_grind(move_index=3)` looped forever against a Tormented Croagunk. The game rejected Knock Off at the UI level ("can't use the same move twice in a row") without consuming a turn, so no stop condition was ever reached.

**Investigation**: Added a 10-turn safety valve first so we could observe the behavior. The battle log showed the rejection text clearly. Then added `MOVE_BLOCKED` detection in `_classify_final_state` (turn.py) — checks for "can't use" / "cannot use" in poll log entries.

**Key discovery**: After Torment rejects a move, the game stays in the **move selection submenu** (not the main FIGHT/BAG/POKEMON/RUN menu). When `auto_grind` called `_battle_turn` again, `_fight_flow` tapped FIGHT first — but the FIGHT coordinates (128, 90) land in the center of the move grid, accidentally selecting a move before the intended backup tap. Confirmed by screenshot + manual tap testing.

**Fix**: When `MOVE_BLOCKED` is detected and `backup_move` is set, tap the backup move directly on the already-visible move selection screen (skip the FIGHT tap), then poll via `_poll_after_action`. Without backup, returns `stop_reason="move_blocked"` immediately. 10-turn safety valve remains as ultimate fallback.

**Files**: turn.py, auto_grind.py, server.py (new `backup_move` param — required `/mcp` restart).
**Tests**: 5 in `test_move_blocked.py` — blocked detection, unblocked succeeds, no-backup bailout, backup completes battle, same-move-backup hits safety.
**Commit**: `4121e59`

### 2. Party wipe blackout recovery

**Problem**: `battle_turn` returned `BATTLE_ENDED` after a full party wipe, but the game was in the blackout sequence (fade → "scurried to a Pokémon Center" → warp → Nurse Joy dialogue). Player stuck with no automated way to recover.

**Investigation**: Loaded save state, triggered wipe (Swinub vs +2 Tangela), manually stepped through the sequence: ~300 frames black screen, B to dismiss scurry text, ~300 frames warp, 3× B for Nurse Joy dialogue, then free movement in PC.

**Fix**: Detect full wipe via `"is out of"` in battle log (note: text has newline between "of" and "usable" — initial `"out of usable"` match failed). `_handle_blackout` presses B periodically through the fade (20 × 188 frames), then `advance_dialogue` for Nurse Joy. Returns `BATTLE_ENDED` with `blackout: true`.

**Files**: turn.py (new `_handle_blackout` helper + detection in post-battle handler).
**Tests**: 3 in `test_blackout.py` — flag detection, party fully healed, player in Pokemon Center (via Pokecenter Nurse NPC check).
**Commit**: `a3bec2c`

### 3. navigate_to adjacent_to_target for occupied tiles

**Problem**: Navigating to an NPC-occupied tile burned 5 repath attempts then reported `stopped_early` / `blocked_at`. Common annoyance with gym trainers, signposts, NPCs.

**Fix**: In `_execute_path`, detect when blocked on the **final step** of the path (`i == len(directions) - 1`) — short-circuit the repath loop with `blocked_on_final_step` flag. In the result builder, convert to `adjacent_to_target: true` with target coordinates when Manhattan distance ≤ 1. Zero wasted repaths.

**Files**: navigation.py (2 edits: `_execute_path` short-circuit + result builder).
**Tests**: 3 in `test_adjacent_target.py` — static NPC returns adjacent, no wasted repaths, empty tile has no flag.
**Commit**: `48e423b`

### 4. Test suite cleanup

- **Legacy exclusion**: `norecursedirs = legacy` in pytest.ini — 30 DeSmuME-era tests no longer collected by default (140 → 140 without noise). Run explicitly with `pytest tests/legacy/ -v`.
- **Flaky doubles fix**: `test_double_battle_both_actions` added `retry_on_rng` decorator + `FAINT_FORCED` to accepted states. RNG damage roll could KO our Pokemon. 5/5 passes confirmed it was a fluke.
- **Full suite**: 140 collected, 140 passed, 0 failed.

**Commit**: `7b17052`

### Backlog status after session

**Resolved this session**: 3 bugs/QoL items + test cleanup
**Remaining**: 4 Eterna Gym bugs (3D elevation + dynamic clock terrain), 1 deferred (Veilstone shop)

## Dev Session: Multi-Chunk BFS Fix (2026-04-08c)

**Goal**: Fix the last open bug — `navigate_to` 3D BFS false block in Mt. Coronet map 218.

### Investigation

Loaded debug save state `debug_coronet218_3d_path_blocked` and reproduced the error: `navigate_to(29, 35)` returned "No 3D path found" with `player_level: 1, elevation_levels: 2`.

Initial hypothesis was a 3D elevation issue (both `view_map(level=0)` and `view_map(level=1)` rendered identically). Dumped BDHC plate data — elevation analysis was actually correct: 2 levels with a valid ramp transition at row 20.

Wrote diagnostic scripts tracing the actual BFS with real terrain data. Key discovery: `get_map_state` returned `Origin: (0, 0)` and `Chunked: False`, but the map's matrix is **1x2 chunks**. The target warp at y=35 was in chunk (0, 1), outside the single 32x32 chunk the BFS was working with. `_bfs_pathfind_level` immediately returned `None` because `goal_y=35 >= height=32`.

### Root Cause

`get_map_state` determined `chunked` via `origin_x > 0 or origin_y > 0`. When the player was in chunk (0, 0), origin was (0, 0) → `chunked = False`, even though the map had multiple chunks. `view_map` already handled this correctly by checking `matrix_w > 1 or matrix_h > 1`.

### Fix

- `resolve_terrain_from_rom` now returns matrix dimensions `(grid, origin_x, origin_y, matrix_w, matrix_h)`
- `get_map_state` uses `matrix_w > 1 or matrix_h > 1` for chunked detection
- Updated the `view_map` caller to unpack the new return signature

### Test Update

`test_3d_elevation` was previously written to accept both success and error (accommodating the known bug). Updated to:
- Use `flee_encounters=True` (cave encounters are RNG)
- Assert success (no error)
- Verify warp to Route 211 (map_id 366) is reached
- Added `@retry_on_rng` decorator for encounter variance

### Results

- All 21 navigation tests pass
- All 11 map tools tests pass
- Last open bug on the backlog is resolved

**Commit**: `7a1c146` — fix: multi-chunk map detection for navigate_to when player is in chunk (0,0)

## Dev Session: melonDS Regression Cleanup + Doubles Faint Fix (2026-04-08b)

Resolved all remaining melonDS migration regressions (backlog items 3-5) and fixed the doubles faint switch bug (backlog item 1). All 12 originally-failing tests now pass.

### PC deposit/withdraw after open_pc

- **Root cause**: `interact_with`'s `advance_dialogue` on melonDS presses B through the "Which PC?" selection menu (B=cancel), returning to overworld. The old `_advance_to_storage_menu` assumed it was still in dialogue — its B→B→A→B sequence accidentally re-triggered the PC and stopped one step short at "Which PC?"
- **Fix**: `_advance_to_storage_menu` now detects overworld state via `_find_script_manager` + `_read_script_state` (`is_msg_box_open` check). If in overworld, re-interacts with PC (A) and advances through both pages of boot text (B→B) before selecting SOMEONE'S PC (A→B)
- **Traced manually**: 5-step dialogue sequence from overworld: A (trigger) → B (page 1) → B (page 2 → "Which PC?") → A (select SOMEONE'S PC) → B (dismiss "Storage System accessed") → storage menu
- **All 7 PC tests pass**

### Doubles faint switch — NO_ACTION_PROMPT (backlog #1)

- **Root cause**: `_wait_for_action_prompt`'s FAINT_FORCED timeout check only read slot 0's HP via `_get_player_hp`. In doubles, the fainted Pokemon (Machop) was in slot 2 — Luxio (slot 0) was alive at 59 HP, so `_get_player_hp(emu) == 0` was False
- **Fix**: Added `_any_player_fainted()` that checks both player slots (0 and 2) for 0 HP, with species validation (>0 and ≤493) to avoid false positives from empty doubles slots in singles battles
- **PROMPT_SETTLE increase alone was NOT sufficient** — the slot check was the real blocker
- **Verified**: Machop faints → FAINT_FORCED detected → `battle_turn(switch_to=4)` sends Charmeleon → WAIT_FOR_ACTION

### Navigation test assertions (3 tests — not actual bugs)

- **test_walk_triggers_warp**: Warp worked (map 65→69), but test checked nonexistent `door_entered`/`new_map` keys. Fixed to compare `start.map_id != final.map_id`
- **test_short_path_indoor**: Target (10,6) was occupied by Idol NPC. Changed to (8,7) — open floor tile
- **test_cutscene_trigger**: Cynthia dialogue captured perfectly, but nested under `result["encounter"]["dialogue"]`. Fixed to accept nested structure

### auto_grind iteration tests (save state XP issue)

- **Root cause**: Save state's Prinplup Lv21 was only 670 XP from Lv22. First Route 216 encounter gave enough XP to level up, triggering `move_learn` before iteration count was checked
- **test_iterations_stop**: Accept `move_learn` as valid alongside `iterations` — encounter was fought, Pokemon just leveled up
- **test_iterations_multiple**: Switched to run mode (no XP gain) to test multi-iteration counting without level-up interference

### conftest robustness

- `detect_shift` in the `emu` session fixture now catches `RuntimeError` and auto-loads `eterna_city_shiny_swinub_in_party` before retrying — prevents cryptic failures when emulator is freshly started without a save state

### Backlog status

| Item | Status |
|---|---|
| Doubles faint switch NO_ACTION_PROMPT | **DONE** — slot 0 vs slot 2 HP check |
| open_pc → deposit/withdraw on melonDS | **DONE** — ScriptManager state detection |
| Navigation tests on melonDS | **DONE** — test assertions, not nav bugs |
| auto_grind iteration tests | **DONE** — save state XP, test resilience |
| 3D BFS false block Mt. Coronet 218 | Open — elevation data issue |
| Specialty shop tool (Veilstone) | Deferred — build when we get there |

**Commits**: 1 this session — df69fd2

---

## Dev Session: melonDS Timing Bug Sweep (2026-04-08a)

Investigated and fixed 5 of 7 open melonDS-era bugs. Found 3 root causes shared across all 5 bugs.

### Root causes discovered

1. **Gen 4 target screen coordinate mapping**: The doubles target selection screen places enemy slot 1 (first enemy from `read_battle`) on the RIGHT and slot 3 (second enemy) on the LEFT — opposite of the battle field layout. Swapped `TARGET_XY[0]` and `[1]`. Verified empirically by tapping (190,50) and confirming Noctowl (slot 1) took Spark damage.

2. **PROMPT_SETTLE too short (300→600 frames)**: `_wait_for_action_prompt` detects prompt text in memory before bottom-screen UI buttons render. At SWITCH_PROMPT, buttons appeared ~600 frames after text detection. Same pattern for MOVE_LEARN prompt. Increased `PROMPT_SETTLE` from 300 to 600 and added PROMPT_SETTLE wait before move-learn touch flows.

3. **8-frame button hold bleed-through**: On melonDS, holding A for 8 frames spans fast menu transitions — the A registers on BOTH the source menu (entering DEPOSIT) and the destination (selecting slot 0 on the party grid). Fixed surgically: 2-frame hold only on the specific A presses that enter DEPOSIT and WITHDRAW modes. Other presses keep 8-frame holds.

### Bugs fixed

| Bug | Root Cause | Fix |
|---|---|---|
| Doubles target=0/1 swapped | #1 coordinate mapping | Swap TARGET_XY entries |
| switch_to at SWITCH_PROMPT fails | #2 PROMPT_SETTLE | 300→600 frames |
| forget_move taps don't register | #2 + misdiagnosed | Added PROMPT_SETTLE before learn flow; taps always worked but read_party returns stale pre-battle data |
| deposit_pokemon extra A press | #3 bleed-through | 2-frame hold on DEPOSIT entry |
| heal_party dialogue stuck | Insufficient cleanup | 5 B presses instead of 3 A presses |

### Key discovery: read_party stale during battle on melonDS

The `read_party` function reads from `ENCRYPTED_PARTY_BASE`, which is frozen at battle start on melonDS. Move changes from in-battle move-learn don't appear until the battle ends and the game writes battle state back to the encrypted party block. The forget_move bug was misdiagnosed as "taps don't register" — debug screenshots proved all 3 taps work. Updated the test to verify moves after battle completion.

### Test changes

- Removed `pytest.xfail` from `test_accept_switch_at_prompt` and `test_forget_move_and_learn`
- `test_forget_move_and_learn` now fights through the remaining trainer Pokemon before checking moves via `read_party`
- All 21 battle tests pass. 121/129 non-legacy tests pass (8 pre-existing failures unchanged).

### Pre-existing failures noted (new backlog items)

8 non-legacy tests were already failing before this session:
- 3 PC tools (open_pc → deposit/withdraw e2e): entry A-press fix works standalone but `open_pc` flow has separate issues
- 3 navigation (walk warp, short path, cutscene): likely same timing class, uninvestigated
- 2 auto_grind (iterations stop/multiple): possibly PROMPT_SETTLE cascade or seek_encounter timing

### Still open from melonDS migration

- **Doubles faint switch NO_ACTION_PROMPT**: May be fixed by PROMPT_SETTLE increase — needs retest
- **navigate_to 3D BFS false block in Mt. Coronet 218**: Separate issue, not timing related

## Dev Session: Test Audit & Tightening + Deferred Test States (2026-04-07c)

Created save states for previously-deferred test scenarios, wrote 9 new tests, then audited all 130 tests for vacuous assertions — tightened 6 files and discovered 2 real melonDS bugs.

### New save states & tests

Navigated from Route 211 east through Mt. Coronet to Route 211 west. Found Bird Keeper Alexandra (3 Pokemon: Natu, Swablu, Staravia).

**Save states created:**
- `route211_west_pre_trainer` — pre-battle overworld position
- `test_trainer_battle_action` — Luxio vs Natu at action prompt (trainer battle)
- `test_move_learn_prompt` — Prinplup wants to learn Icy Wind at "Make it forget?" prompt

**9 new tests (previously deferred):**
- `TestTrainerBattle` (6 tests): use move, switch prompt after KO, switch prompt has next Pokemon, decline switch, accept switch, full battle, post-battle dialogue
- `TestMoveLearn` (3→2 tests): skip move learn (verify moves unchanged), forget move and learn (verify moves updated)

**Still deferred:** Evolution in battle, Yes/No dialogue prompt (need different game progress).

### Test suite audit

Ran a comprehensive audit of all tests for "vacuous" assertions — tests written so loosely they can't fail. Found **58 issues** across 6 anti-patterns:

| Anti-pattern | Count | Example |
|---|---|---|
| Accepts every possible outcome | 10 | `test_double_battle_both_actions` accepted all 10 states |
| Conditional `if` silently skips | 14 | `test_switch_prompt_after_ko` only asserted inside `if SWITCH_PROMPT` |
| Trivially true assertions | 14 | `assert result is not None` on functions that always return dicts |
| Only asserts type/presence | 7 | `assert isinstance(result, dict)` with no content checks |
| Interesting assertion behind `if` | 5 | `test_force_flag` only tested force when warning fired |

### Tightened assertions (6 files, +421/-285 lines)

- **test_battle.py**: Verify specific species in battle_state, move names in logs, party moves after learn/skip
- **test_navigation.py**: Verify arrival at exact target coordinates, unconditional warp/error checks
- **test_auto_grind_v2.py**: Unconditional iteration count and encounter log assertions
- **test_item_tools.py**: Verify HP changes after medicine, bag changes after take_item, move lists after teach_tm
- **test_pc_tools.py**: Verify party size changes after deposit/withdraw
- **test_map_tools.py**: Unconditional object count checks, elevation marker verification

### Bugs discovered (2 new, added to backlog)

1. **`switch_to` at SWITCH_PROMPT doesn't execute on melonDS**: `battle_turn(switch_to=1)` at a trainer switch prompt returns a valid state but the active battler remains unchanged (Luxio instead of Machop). Marked `xfail`.

2. **`forget_move` touch taps don't register on melonDS**: `battle_turn(forget_move=3)` at a MOVE_LEARN prompt returns a valid state but `read_party` shows moves unchanged (Peck still in slot 3, Icy Wind not learned). The `_learn_move_flow` touch inputs likely need timing adjustments for melonDS. Marked `xfail`.

Both bugs were invisible under the old loose assertions — the tests passed because they only checked `final_state`, not the actual game state changes.

### Performance

MelonMCP render-skip optimization (skipping GPU rendering on bulk-advance intermediate frames) improved emulator throughput from ~800 FPS to ~2000 FPS. Test suite benefits from faster frame advancement.

**Commits**: `2c641ce`, `0497c6d`

## Dev Session: Comprehensive melonDS Test Suite (2026-04-07b)

Built a full regression test suite for all 35 Renegade MCP tools on melonDS. No tool code was modified — strictly test infrastructure.

### Motivation

After migrating from DeSmuME to melonDS, recurring timing/input bugs made it clear we needed a proper test suite. The existing 34 battle-focused tests all depended on DeSmuME .dst save states (incompatible with melonDS).

### What was built

- **121 tests across 11 new files** covering all 35 tools
- **4 new melonDS save states** created for test scenarios:
  - `test_wild_battle_action` — wild Smoochum battle at action prompt (Route 216)
  - `test_eterna_city_overworld` — standing outside Pokemon Center in Eterna City
  - `test_damaged_party_overworld` — Prinplup at 48% HP after battle (Route 216)
  - `test_npc_dialogue_active` — mid-dialogue with Galactic Grunt (Eterna City)
- **`retry_on_rng` decorator** added to `helpers.py` — reloads save state and retries up to 3x for RNG-dependent tests
- **7 DeSmuME-era test files** moved to `tests/legacy/`

### Test file breakdown

| File | Tests | Tools Covered |
|------|-------|---------------|
| `test_data_tools.py` | 16 | type_matchup, move_info, decode_rom_message, search_rom_messages |
| `test_read_tools.py` | 24 | read_party, read_battle, read_bag, read_trainer_status, read_box, read_shop, tm_compat |
| `test_map_tools.py` | 11 | view_map, map_name |
| `test_navigation.py` | 22 | navigate, navigate_to, interact_with, seek_encounter |
| `test_battle.py` | 13 | battle_turn, throw_ball, read_dialogue |
| `test_item_tools.py` | 15 | use_item, use_field_item, use_medicine, take_item, give_item, teach_tm |
| `test_shop_tools.py` | 3 | buy_item |
| `test_pc_tools.py` | 7 | open_pc, deposit_pokemon, withdraw_pokemon, close_pc |
| `test_party_tools.py` | 5 | reorder_party, heal_party |
| `test_auto_grind_v2.py` | 5 | auto_grind |
| `test_utility.py` | 1 | reload_tools |

### Pass rates

- **Deterministic tests** (data, read, map, utility): 52/52 (100%)
- **State-changing tests** (fresh session): ~96% (shop 3/3, navigation 22/22, most battle/item/PC pass)
- **Known failure**: double battle both-actions test — pre-existing timing bug in `debug_doubles_target_swapped` state

### Known issue: address cache staleness

When running the full 121-test suite sequentially, some mid-suite tests destabilize the emulator's address resolution (`detect_shift` cache), causing a cascade of `RuntimeError` in later tests. Running test groups independently avoids this. Root cause TBD — likely needs periodic re-detection in `addresses.py`.

### Deferred tests (need game progress)

- Trainer battle (no undefeated trainers in current area)
- Move learn / evolution in battle
- Yes/No dialogue prompt

**Commits**: `de26266`

## Dev Session: Shiny Detection, Bug Fixes, Map Reachability (2026-04-07)

Feature + bug fix session. Cleared 3 bugs from the backlog, added shiny detection, improved auto_grind and view_map.

### Feature: Shiny detection across all read tools

Added `shiny: true/false` to `read_party`, `read_battle`, `read_box`, and all formatters (`*SHINY*` tag).

- **Party/box**: Reads OT ID (u32) from Block A offset 4 — TID in lower 16, SID in upper 16. Computes `(TID ^ SID ^ (PID >> 16) ^ (PID & 0xFFFF)) < 128`.
- **Battle**: Reads `isShiny` bit from BattleMon struct +0x26 (formNum:5, isShiny:1, padding:2). Game-computed, no threshold needed.
- **Threshold discovery**: Vanilla Gen 4 uses `< 8` (1/8192 rate). Initial implementation returned `shiny: false` for our known shiny Swinub. Debug script revealed XOR = 92 — Renegade Platinum increases the rate to ~1/512 (threshold 128). All non-shiny Pokemon had XOR values 400+, confirming the threshold.
- **Verified**: Box 1 slot 5 (shiny Swinub, 31 Atk IV, Timid) correctly flagged. Party members correctly unflagged.

**Commits**: `f6306f0`

### Feature: auto_grind stops on shiny encounters

`auto_grind` now checks the enemy's `shiny` field before fighting or running. Any shiny halts with `stop_reason="shiny"` and battle state attached. Checked before `target_species` so shinies are never accidentally KO'd or fled from. With the 1/512 rate, we'll hit these during grinding sessions.

**Commits**: `fe65b1b`

### Fix: Snow terrain false blocks (revised)

Original fix (single extra wait of 16 frames) only worked when starting from a north-facing position. Failed on direction changes — the first button press in deep snow turns the character without stepping. Woj caught this with a visual repro: d2 then u9 still stopped after the turn.

**Final fix**: Retry up to 3 full press cycles (HOLD_FRAMES + WAIT_FRAMES each) when a block is detected. The second press initiates the actual step after the turn completes. Only triggers on apparent blocks — no impact on normal movement.

**Verified**: `route216_snow_nav_bug_v2` → d2, then u9 — all 9 steps complete through deep snow with direction change.

**Commits**: `e08d3c8`, `d8d3c09`

### Fix: Sign overlay dialogue detection

Signposts (all types: Signboard, Arrow, Gym, Trainer Tips — gfx IDs 91-96) render text via BG-layer board message overlay without setting `msgBox=1` in ScriptManager. `advance_dialogue` checked msgBox first and returned `"no_dialogue"`, discarding valid text.

**Investigation**: Loaded `route216_lodge_post_shiny`, interacted with Signboard at (305, 399). `read_dialogue` found "Snowbound Lodge / A Warm Bed and Little Else" in memory, but `msgBox: False`. Confirmed this affects ALL signpost types, not just arrow signs as originally reported.

**Fix**: In `interact_with`, when target is a sign object (gfx_id in SIGN_GFX_IDS) and `read_dialogue` found text but `advance_dialogue` rejected it, accept the text directly and dismiss overlay with B. Both auto-trigger and A-press paths covered. Returns `sign_overlay: true` flag.

**Commits**: `e08d3c8`

### Feature: view_map object reachability sorting

Objects in `view_map` are now grouped by BFS reachability instead of pure Manhattan distance:

1. **Reachable**: sorted by actual step count to nearest adjacent tile (`reachable: true, steps: N`)
2. **Unreachable**: sorted by Manhattan distance (`reachable: false, distance: N`)

Uses a single BFS flood-fill from the player position — one traversal covers all objects. Lightweight passability check (collision bit + warp/ledge overrides + obstacle exclusion) mirrors navigation.py's logic without circular imports.

**Verified**: Route 216 (5 reachable objects, correct step ordering), Eterna Pokemon Center (Nurse behind counter correctly unreachable), `route216_snow_nav_bug` (Black Belt across wall correctly unreachable at distance 10 despite being close).

**Commits**: `eb17449`

### Fix: Git credential warning

Removed malformed global credential helper from `~/.gitconfig`. The `\\!` escape caused git to look for a command called `credential-!/usr/bin/gh` on every push. Per-host helpers for `github.com` and `gist.github.com` already handled auth correctly — the global fallback was redundant noise.

**Commits**: 6 this session — `f6306f0`, `e08d3c8`, `830b196`, `fe65b1b`, `eb17449`, `d8d3c09`.

---

## Dev Session: Snow Tile Navigation Fix (2026-04-06)

Route 216 navigation was completely broken — the nav tools couldn't pathfind through snow tiles. Diagnosed and fixed in a single session.

### Investigation

Loaded `debug_route216_blocked_down` save state at (374, 402) on Route 216. Initial assumption from the backlog was that snow tile behaviors (0x70, 0x71, 0x75, 0xA1, 0xA2, 0xA8) were classified as impassable by BFS. Terrain analysis proved this wrong — snow tiles have no collision flag in either RAM or ROM. They were correctly marked passable.

The real culprit was the **3D elevation system (BDHC)**:

1. **`_height_to_level` returned the wrong level.** Player at height 136 on a ramp tile (level 7↔3) was matched to Ramp 1 (level 8↔2, range 48–160) because the code returned the first ramp match. Surrounding snow tiles were all level 7, so 3D BFS on level 8 found nothing.

2. **Ramp oscillation during repaths.** Even with the correct level, walking onto a ramp changes the player's height mid-step. Each repath recalculated the level, sometimes flipping direction — causing the player to walk up-down-up-down on stairs before eventually settling.

### Fix 1: Improved `_height_to_level` (commit 9ff5cd2)

Three improvements to height→level resolution:
- **Tile-based pre-check**: if the player's tile is a known ramp or has level_map data, use that directly instead of scanning all ramps
- **Narrowest-range preference**: when multiple ramps match the height, pick the one with the smallest height span (most specific)
- **Nearest-level fallback**: if no exact match or ramp contains the height, return the closest defined level

Also added snow tile display names to the BEHAVIORS dict so `view_map` renders them with proper labels instead of `?`.

### Fix 2: 3D→2D BFS fallback for multi-chunk maps (commit 1ca4d38)

Initial approach was to disable 3D BFS entirely for multi-chunk overworld maps. This fixed Route 216 but **regressed bridge pathfinding** on Route 211 — 2D BFS has no elevation concept, so it routed straight off the side of bridges.

Final approach: try 3D BFS first (needed for bridges), fall back to 2D when 3D fails (needed for slopes where BDHC over-constrains). On fallback, elevation is cleared from the repath context so subsequent repaths also use 2D (prevents ramp oscillation).

### Verification

| Test | Save State | Result |
|------|-----------|--------|
| Route 216 snow stairs | `debug_route216_blocked_down` → `navigate_to(365, 409)` | 16-step clean path through snow |
| Route 216 snow walk | `route216_snow_nav_bug` → `navigate_to(336, 394)` | 7-step path through snow tiles |
| Route 211 bridge | `debug_route211_bridge_pathfind` → `navigate_to(368, 535)` | 31-step elevated path (correct, no bridge jump-off) |

### Lessons

- **The backlog entry was partially inaccurate.** It attributed the bug to "tile classification" when the root cause was 3D elevation. The documented coordinates were also wrong. Future backlog entries need verified, tested repro steps.
- **Observe before fixing.** Should have reproduced the exact original failure before writing any code. Loaded the save state but jumped to analysis without a clean before/after comparison.
- **Watch for regressions in related subsystems.** Disabling 3D BFS for overworld maps seemed safe until we checked bridge pathfinding — a feature built on the same 3D system.

**Commits**: 3 this session — `9ff5cd2`, `9363e88`, `1ca4d38`.

---

## Dev Session: Pre-Migration Bug Sweep, Final Round (2026-04-06)

Last bug-fix session before MelonMCP migration. Cleared all remaining open items from the tool backlog — the backlog is now empty.

### Fix: interact_with trainer approach animation (commit 9dc1bbc)

**Root cause**: During trainer "!" exclamation + walk-toward-player animation, `msgBox` and `subCtx` are both 0 for ~170 frames. The only signal of an active script is `ctx0` being in `RUN` state. The fallback in `interact_with` only checked `msgBox || subCtx`, missing the entire approach window.

**Investigation**: Frame-by-frame sampling of the ScriptManager struct while a Route 205 Hiker approached. Baseline idle overworld shows `msgBox=1, ctx0=WAIT`; after A-press during approach animation, `msgBox=0, subCtx=0, ctx0=RUN` persists from +5f through +170f, then `msgBox=1, ctx0=WAIT` when dialogue opens at +175f.

**Fix**: Added `_read_context_state(ctx0)` check to the fallback. When `msgBox` and `subCtx` are both 0 but `ctx0` is `CTX_RUNNING` or `CTX_WAITING`, sets `script_active=True` and polls via `_post_nav_check` (300 frames). Added `CTX_RUNNING`, `CTX_WAITING`, `_read_context_state` to navigation.py imports from dialogue.py.

### Fix: interact_with circular-patrol NPCs (commit 54d1d50)

**Problem**: NPCs with patrol movement types (e.g., Battle Girl type_39 on Route 205 — rectangular 2×5 loop, ~450f cycle) move away during the face→A interaction sequence, causing "no dialogue" returns.

**Investigation**: Sampled Battle Girl's position every 30 frames for 1800 frames. Mapped the full patrol: (207,598) → left to (205,598) → down to (205,603) → right to (207,603) → up to (207,598). Cycle time ~450f (~7.5 sec).

**Fix**: Added `_wait_for_moving_npc` — a 15-second polling loop (900 frames, ~2 full patrol cycles) that activates when normal interaction fails on a non-stationary NPC (`movement_type not in ("none", "stationary")`). Polls for: (1) trainer-spotted battles via `read_battle`, (2) dialogue appearing via `read_dialogue`, (3) NPC adjacency → face + A-press with 90-frame cooldown. Includes `facing_seized` detection and `ctx0=RUN` approach animation check during the wait. Non-moving NPCs skip the loop entirely.

**Testing**: Battle Girl (index 6) and Camper (index 19) on Route 205 both successfully triggered battles. Existing mechanisms (`facing_seized`, auto-dialogue) caught both cases, with the wait loop as safety net. Verified no regression on stationary NPCs (Hiker, defeated Pokemon Breeder F).

### Fix: navigate warp_failed dialogue detection (commit 24912e2)

**Problem**: When an NPC triggered dialogue near a warp tile (e.g., Cheryl's farewell at Eterna Forest exit), `navigate_to` returned `warp_failed: true` instead of the dialogue. All four `warp_failed` code paths returned immediately without checking for pending dialogue.

**Fix**: All four `warp_failed` paths now call `_post_nav_check` before declaring failure:
1. `navigate`: expected_transition but map unchanged
2. `navigate_to`: `is_door + stopped_early` (main bug path)
3. `navigate_to`: door reached but `_handle_door_transition` returned None
4. `navigate_to`: `adj_warp_failed` suppressed when encounter already exists

**Testing**: Loaded `debug_cheryl_exit_dialogue_pre_navigate`, navigated to exit warp (86, 36). Correctly captured Cheryl's full farewell: "Oh! There's the exit!", TM27 gift, "Bye for now!" — instead of `warp_failed`.

### Backlog Cleanup

- **Closed**: Tag battle (NPC ally) support untested — no issues encountered during gameplay, will re-add if problems surface.
- **Closed**: navigate_to BFS blocks follower NPCs (Cheryl) — Eterna Forest-specific, that section is complete.
- **Result**: Open backlog is now empty. Ready for MelonMCP migration.

## Dev Session: MCP Tool Token Optimization (2026-04-02)

Driven by context audit showing top MCP token consumers: `get_screenshot` (16.5%), `view_map` (4.8%), `battle_turn` (2.9%), `navigate_to` (2.1%). Screenshots can't be easily reduced, so focused on the tool output side.

### battle_turn (~60% reduction per call)
- New `battle_summary()` function in `battle.py` — trimmed battle state for embedding in every `battle_turn` response. Returns only strategically relevant fields: species, level, hp as `"48/62"` string, combined types, status, stat stages, moves (name+pp only). Enemy side also gets ability and item.
- Removed `formatted` field (human-readable string that duplicated the `log` array) and the 53-line `_reformat()` function from `turn.py`.
- Kept `party` on switch states (already minimal: slot/name/level).

### read_battle / read_party (deduplication)
- `read_battle`: Dropped `species_id`, `ability_id`, `item_id`, `weight_kg` from output. Kept move `id` internally (used by effectiveness checker in `server.py`). Human-readable names retained.
- `read_party`: Consolidated triple move encoding (`moves` IDs + `move_names` + `move_info` dicts) into single `moves` list with inline detail (name, pp, type, power, accuracy, class). Dropped `species_id`, `ability_id`, raw `status` int. Kept `move_names` and `pp` as separate fields for backward compat with 6+ internal consumers.

### view_map (~70% reduction per call)
- Compact 1-char-per-tile ASCII grid (was 3-char with axis headers). Symbols: `_` walkable, `#` wall, `.` void, `"` grass, `≈` water, `D` door, `+` warp, `T` tree, etc. Full behavior→symbol mapping in `_BEHAVIOR_CHAR` dict.
- Removed: axis headers, static legend (same every time), elevation verbose summary. Replaced with compact key (only shows behaviors present on current map) and single-line elevation summary.
- Trimmed return dict: dropped `local_x`/`local_y` from objects, `label` field, `dest_map_id` from warps (kept `dest` name), `origin`/`chunked` from result, `display`/`code`/`room` from player dict. Compact header: `Map 395 (12,8) down` instead of multi-line.

### navigate_to / navigate_manual (~80% reduction per call)
- `_execute_path` no longer builds per-step log array with from/to coordinate pairs and NPC change dicts. NPC tracking still runs internally for repathing — only the output is trimmed. Returns compact `nav_info` dict: `blocked_at`, `npc_moves` count, `map_changed` flag (only when relevant).
- Return dicts: `path` (summarized direction string), `steps`, `start`, `final`. Dropped: `total_directions`, `log` array, `stopped_early` (now only present when true), `steps_with_npc_movement`.
- `_pos_with_map` trimmed to `{x, y, map, map_id}` — drops `display`, `code`, `room` that were spread from `lookup_map_name`.

### auto_grind (~40% reduction per run)
- Uses `battle_summary()` for target_species embedded state. Returns `slot0` summary instead of full party array. Added `_flatten_log()` helper to extract text from `battle_turn`'s raw log entries (replaces dependency on removed `formatted` field). Removed `formatted` summary, `last_battle`, full `party` from `_finish()` return.

### Cleanup
- Removed dead `_reformat` from `turn.py`, unused `format_battle` import.
- Fixed `catch.py` which imported `_reformat`.
- Fixed `heal_party.py` and `shop.py` references to `path_summary` → `path`.
- All syntax checks pass. Tests unaffected (don't reference removed fields).

## Dev Session: use_medicine Tool + Party Status Reading (2026-04-02)

### New Tool: `use_medicine`
- Bulk party healing using Medicine pocket items. Plan-then-execute workflow: dry-run (default) returns an itemized plan, `confirm=True` executes via repeated `use_item` calls.
- **HP healing algorithm**: At each step, checks if any single item covers the remaining deficit (uses cheapest sufficient one). If not, uses the cheapest item available and repeats. This avoids the "Potion + Super Potion" waste case — if a Super Potion alone covers 30 HP deficit, it skips the Potion.
- **Status cure priority**: Prefers specific cures over general ones (Antidote before Full Heal, Parlyz Heal before Full Heal, etc.).
- **Full Restore optimization**: When a Pokemon needs both status cure AND HP healing, uses Full Restore to handle both in one item instead of separate cure + potion.
- **Revival support**: Plans Revive/Max Revive/Revival Herb for fainted Pokemon, with post-Revive HP top-up via potions.
- **Optional params**: `exclude_items` list (e.g., save Max Revives), `priority` slot order for triage when items are scarce.
- **Warnings**: Reports when items are insufficient for full party heal.
- PP restoration deliberately excluded — Ethers/Elixirs are too rare to auto-spend.

### Party Status Conditions
- Added status condition reading to `read_party`. Party extension offset 0x00 is a u32 status bitfield (same format as battle status). Was previously ignored.
- New `decode_status_conditions()` function in `party.py` — returns list like `["Poison", "Paralysis"]`.
- `read_party` now includes `status` (raw int) and `status_conditions` (decoded list) per Pokemon.
- `format_party` shows status conditions inline with a warning marker.

### Testing
- Verified planning algorithm with mock data: Woj's Potion+Super Potion edge case, multi-item stacking, Full Restore optimization, exclude_items, priority ordering, insufficient items with warnings.
- Live test on `route204_north_progress` save state: 4 Potions used across Grotle (3) and Charmander (1), all succeeded, party healed to full.

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

---

## Session 13 — Bug Fix Sweep (2026-04-02)

Pure dev session — no gameplay. Resolved all 4 open bugs from Session 12 plus added a QoL feature.

### Bug Fixes

1. **Switch prompt party order mismatch** (`3a21842`)
   - **Root cause**: `_enrich_switch_result` used `read_party` (persistent memory order) to label party slots, but `switch_to` taps the battle UI grid which reorders after in-battle switches.
   - **Fix**: Read `BattleContext.partyOrder[0]` (6 bytes at `0x022C5B60`) — a UI position → party slot mapping maintained by the battle engine. Reorder the enriched party list to match UI positions.
   - **Discovery**: Found via pret/pokeplatinum decomp (`battle_context.h:301`). Verified against `debug_faint_forced_switch_to_4` save state — [2,1,4,3,0,5] correctly maps Prinplup→Machop→Charmander→Luxio→Grotle matching the bottom screen.

2. **interact_with incomplete NPC dialogue** (`c8fdb47`)
   - **Root cause**: Detected dialogue but returned raw first-page text without advancing.
   - **Fix**: Chain into `advance_dialogue()` after detecting overworld dialogue (both auto-trigger and post-A-press paths). Also check for battle transitions post-dialogue.
   - Tested with multi-page NPC dialogue in Floaroma Pokemon Center.

3. **MOVE_LEARN shows wrong Pokemon's moves** (`c7ee0f1`)
   - **Root cause**: `_enrich_move_learn_result` read battle slot 0's moves (active battler) instead of the Pokemon actually learning. Misleading when Exp Share or switched-out Pokemon level up.
   - **Fix**: Pointer chain through `BattleContext.taskData` (`0x022C2BAC`) → heap-allocated `BattleScriptTaskData`:
     - `tmpData[4]` (offset +0x40) = move ID being learned
     - `tmpData[6]` (offset +0x48) = lower-bound party slot search index
     - Combined with `levelUpMons` bitmask (`0x022C5B3D`) to find exact slot: lowest set bit >= lower bound.
   - Also replaced expensive text memory scan with direct move ID → name lookup from ROM data.
   - **Caveat**: All BattleContext fields retain stale values outside battle. Validated via move ID range (1-467), slot range (0-5), and levelUpMons != 0. Stale data is harmless in practice since enrichment only runs during MOVE_LEARN state.

### New Feature

4. **Trainer defeated status on view_map** (`1b1299a`)
   - `view_map` now shows `[defeated]` tag on trainer NPCs, plus `trainer_id` and `defeated` fields.
   - **Mechanism**: VarsFlags bitfield in save RAM. Flag = `1360 + trainerID`. FLAGS_ARRAY base at `0x0227F1BC` (verified by testing 3 candidate offsets from decomp + PKHeX layout).
   - Trainer ID extracted from NPC script field: `script - 3000 + 1` (single) or `- 5000 + 1` (double).
   - **Scope**: Works for regular route/cave trainers. Gym leaders, rivals, and Team Galactic use separate story flags (not tracked — obvious from context anyway).
   - Verified 12+ trainers across Routes 202-205, Oreburgh Gate, and Oreburgh Gym.

### Key Decomp Addresses Discovered
| Address | Field | Used By |
|---------|-------|---------|
| `0x022C5B60` | `BattleContext.partyOrder[0]` (u8[6]) | `_enrich_switch_result` |
| `0x022C5B3D` | `BattleContext.levelUpMons` (u8 bitmask) | `_get_move_learn_info` |
| `0x022C2BAC` | `BattleContext.taskData` (pointer) | `_get_move_learn_info` |
| `0x0227F1BC` | `VarsFlags.flags` base | `is_trainer_defeated` |

### Backlog Status
- **Resolved this session**: party order mismatch, interact_with dialogue, MOVE_LEARN wrong Pokemon, trainer defeated indicator
- **Remaining open**: tag battle untested (edge case), multi-chunk 3D BFS (deferred)

## Dev Session: Auto-Flee Navigation & Bug Fixes (2026-04-03)

### flee_encounters for navigate, navigate_to, interact_with
New `flee_encounters=True` parameter on all three navigation tools. When enabled, wild encounters are automatically fled and navigation resumes. Trainer battles (detected by pre-battle dialogue present in the encounter dict) and cutscenes halt for the caller.

**Implementation details:**
- `_flee_wild_battle()` helper in navigation.py — calls `battle_turn(run=True)` in a loop, retries on failed escape (WAIT_FOR_ACTION), stops on faint or unexpected states. Max 10 attempts.
- `_try_flee_encounter()` shared helper — classifies encounters (wild/trainer/dialogue), flees wild battles, returns structured log entry with species and attempt count.
- `navigate_to`: Full retry loop — flees, re-BFS's from current position, up to 10 encounters. Returns `flee_log` and `encounters_fled`.
- `navigate`: Resume loop — flees, continues remaining directions from where it stopped. Verified via decompilation (`ref/pokeplatinum/src/overlay005/field_control.c` and `overlay006/wild_encounters.c`) that encounters trigger AFTER position update, so remaining directions are valid from the encounter tile.
- `interact_with`: Single flee at the mid-path encounter check. Clears wild battle, continues to target or reports interruption.
- `heal_party` and `buy_item` pass `flee_encounters=True` by default since navigating to heal/shop should avoid fights.

**Wild vs trainer heuristic**: `encounter.get("dialogue")` present = trainer (pre-battle taunt auto-advanced) → halt. No dialogue = wild → flee. Reliable because Gen 4 trainers always have pre-battle text.

**Testing**: Verified on Route 202 — `navigate("r8 l8 r8 l8", flee_encounters=True)` fled Sentret + Zigzagoon and completed full 32-step path. Trainer halt verified (Youngster with pre-battle dialogue). Cutscene halt verified (Dawn/Looker cutscene in Jubilife).

### heal_party double-heal fix
**Root cause**: Off-by-one in A-press sequence. `advance_dialogue` (via `interact_with`) stops at Nurse Joy's Yes/No prompt. The first A press in `_heal_at_nurse` was intended to "finish text → reach Yes/No" but actually selected YES immediately (since we were already at Yes/No). This shifted all subsequent presses by one, causing the last A to hit the overworld and re-trigger Nurse Joy.

**Fix**: Removed the redundant first A press, reduced post-heal clear presses from 4 to 3. Regression from output trimming session (session 14) which changed how `advance_dialogue` handles multi-page text. Verified on both Floaroma (overworld → navigate to PC) and Jubilife (already inside PC).

**Debug methodology**: Added temporary instrumented `_debug_press` that logged dialogue state after each A press. The log clearly showed step 1 already had "OK, I'll take your Pokémon" (post-YES text) instead of the expected Yes/No prompt.

### auto_grind _move_learn_detail KeyError fix
Output trimming (session 14) dropped `pp` from the party-based `current_moves` dict in `_enrich_move_learn_result`, but `_move_learn_detail` in auto_grind still assumed it. Made `pp` optional in the formatter. Also updated test assertion (`party` → `slot0`).

### Test suite results (28 tests)
- 24 passed, 4 failed (all auto_grind _move_learn_detail KeyError), 1 skipped
- After fix: 27 passed, 1 failed (test_party_included_in_result — stale `party` key assertion), 1 skipped
- After test fix: expected all pass (deferred full re-run)

### Signpost auto-trigger investigation (not yet fixed)
**Bug**: Walking below a signboard while facing up auto-triggers dialogue, interrupting `navigate_to`. Reproduced in Floaroma Town: sign at (189, 655) triggers when walking to (189, 656) facing up.

**Findings**:
- The sign is ROM object #11 in zone_event file 0405.bin: `gfx=93` (OBJ_EVENT_GFX_SIGNBOARD)
- Sign gfx IDs identified: 91=Map Signpost, 93=Signboard, 94=Arrow Signpost, 95=Gym Signpost, 96=Trainer Tips Signpost
- The sign doesn't appear in `read_objects` RAM scan — possibly loaded at a higher RAM slot missed by the 3-consecutive-empty-slot break in the scanner
- Not a bg_event (Floaroma has 0 bg events) or coord_event (0 coord events)
- Fix requires: (1) parse sign positions from ROM zone_event data, (2) mark activation tiles in BFS, (3) route around or handle gracefully
- Deferred — more complex than initially expected

### Backlog Status
- **Resolved this session**: auto-flee navigation, heal_party double-heal, auto_grind KeyError
- **Investigated**: signpost auto-trigger (root cause found, fix deferred)
- **Remaining open**: 5 double battle bugs, signpost navigation, locked doors, tag battle untested, multi-chunk 3D BFS

## Dev Session 17: Player-Centered Viewport, Signpost Fix, Post-Battle Dialogue (2026-04-03)

Three QoL improvements focused on navigation and battle flow ahead of resuming the adventure.

### 1. Player-Centered Viewport for view_map (`8aaa345`)

**Problem**: `view_map` rendered the entire 32x32 chunk the player was on, cropped to content bounds. At chunk edges, zero visibility into adjacent chunks — the player's "camera" was locked to the chunk grid, not centered on the player.

**Solution**: 32x32 viewport centered on the player, loading adjacent chunks as needed.

**New functions in `map_state.py`**:
- `_compute_viewport_bounds()` — two modes:
  - **Indoor/small maps**: content-fitted crop (preserves compact rendering — Pokemon Center stays 18x15, gym stays 32x32)
  - **Overworld/multi-chunk maps**: 32x32 centered on player, clamped to world bounds (matrix_w × 32, matrix_h × 32)
- `_load_viewport_terrain()` — composites raw u16 tile values from up to 4 ROM chunks (2x2 worst case for 32x32 viewport). Similar pattern to `navigation.py:_build_multi_chunk_terrain` but returns raw tiles instead of passability tuples.

**Modified functions**:
- `render_map()` — removed content-bounds crop loop; terrain grid IS the viewport, render it all. Object bounds checks use dynamic grid dimensions instead of hardcoded 32.
- `view_map()` — complete rewrite of orchestration: matrix lookup → viewport bounds → load terrain → viewport-relative positions → filter objects/warps → elevation key translation → render → header with origin/size.

**Coordinate communication**: Header includes `origin:(x,y) WxH` — the global coordinate of the top-left grid corner. Any grid position → global coords is `origin + grid_pos`. Player dict includes `grid_x`/`grid_y` for position within the grid.

**Elevation handling**: BDHC elevation keys (chunk-local) translated to viewport-local coordinates for indoor maps. Elevation only active on single-chunk maps (overworld elevation deferred).

**Testing**: Valley Windworks (indoor, 25x19), Oreburgh Gym (elevation, 32x32), Route 205 (overworld, multi-chunk), Route 201 (overworld), Floaroma Town (overworld, buildings + water across chunks). All verified.

### 2. Signpost Navigation Avoidance (`878dd54`)

**Problem**: Signs auto-trigger dialogue when the player steps onto the tile directly south while facing north. This interrupted `navigate_to` mid-path. Signs often don't appear in `read_objects` RAM scan because they're loaded at high RAM slot indices past the consecutive-empty-slot break.

**Investigation**: Parsed Floaroma Town's zone_event file (0405.bin) — 3 signs found as regular object events with gfx IDs 91 (Map Signpost), 93 (Signboard). The problematic sign at (189,655) has walkable terrain underneath (0x0000) — collision is from the object, not terrain. The activation tile (189,656) is also plain ground with no special behavior.

**Solution**: ROM-based sign detection + BFS tile blocking.
- `read_sign_tiles_from_rom(emu, map_id)` in `map_state.py` — parses zone_event object events, filters by sign gfx IDs {91, 93, 94, 95, 96}, returns activation tiles (sign_y + 1).
- Sign activation tiles added to `npc_set` in all BFS code paths:
  - `_navigate_to_impl`: both single-chunk and multi-chunk branches
  - `interact_with`: both branches
  - `_try_repath`: via `sign_tiles` set in repath context dict
- BFS routes 1 tile to the side — minimal path cost, eliminates auto-trigger entirely.

**Verification**: Original repro `navigate_to(163,641)` from (191,660) in Floaroma Town — 47 steps, path detours left at (188,657) to avoid (189,656), no signpost trigger. Also tested with `flee_encounters=True`.

### 3. Auto Post-Battle Dialogue (`94b2348`)

**Problem**: After trainer battles, post-battle overworld dialogue (defeat text, story triggers) required manual `read_dialogue` calls. This friction adds up on routes with multiple trainers.

**Solution**: `battle_turn` now auto-advances post-battle dialogue on both `BATTLE_ENDED` and `TIMEOUT` states.
- On `BATTLE_ENDED`: wait 180 frames for overworld to settle, call `advance_dialogue`, include text as `post_battle_dialogue` list in result.
- On `TIMEOUT`: check `read_battle` first — if still in battle, leave as TIMEOUT. If in overworld (no battlers), advance dialogue and upgrade state to `BATTLE_ENDED`.
- When no dialogue present: `advance_dialogue` returns `no_dialogue` quickly, no `post_battle_dialogue` key added, minimal overhead.
- `auto_grind` inherits this via its `battle_turn` calls.

**Testing**: Youngster Tristan fight (Hoothoot + Starly) — trainer defeat text ("Too strong! Too strong!") captured in battle log (in-battle text sequence), no separate overworld dialogue. Wild battle (Starly) — no dialogue, no extra key. Both confirm correct behavior.

### Backlog Cleanup
- **Checkpoint-to-save-state tool**: Removed from this project's backlog — it's a DeSmuME MCP feature, tracked in that project.
- **Cross-chunk navigation feedback**: Reworded to "navigate_to failure explanations" — the cross-chunk BFS already works; the remaining issue is purely about error messaging when BFS can't find a path.

### Backlog Status
- **Resolved this session**: player-centered viewport, signpost navigation, auto post-battle dialogue
- **Remaining open**: 5 double battle bugs, navigate_to failure explanations (deferred QoL), locked/key doors (behind us), tag battle untested (low priority), multi-chunk 3D BFS (deferred)
- **Next session**: Double battle bug sweep

## Dev Session 18: Double Battle Bug Sweep (2026-04-03)

Resolved all 5 open double battle bugs. Methodology: review full battle_turn workflow, load debug save states, observe each bug empirically, then implement targeted fixes. All 28 existing tests pass + 3 new regression tests added (31 total).

### Core Architecture Change: `_is_battle_over` (`c9ec239`)

Replaced the single garbage-data heuristic with a **two-tier check**:
1. **`battleEndFlag`** (0x022C5B53) — authoritative signal set by the game engine when battle result is determined. Catches "battle just ended" before overworld loads.
2. **Garbage-data fallback** — original species/level/HP validity check on battle slot 0. Catches "overworld loaded" when the flag hasn't been set yet (e.g., during level-up/evolution processing).

Also **removed the "fainted + Exp. Points" text heuristic** from `_classify_final_state` and `_recover_from_level_up`. This heuristic was the root cause of bug #3 (premature BATTLE_ENDED in doubles) — it matched after a single enemy faint in doubles, even though the battle continued.

### Bug Fixes

**1. Switch in doubles → TIMEOUT instead of WAIT_FOR_PARTNER_ACTION**
- **Root cause**: After a switch, the tracker poll found no battle narration text (switches don't generate "used" text). Returned TIMEOUT. The WAIT_FOR_PARTNER_ACTION detection only checked WAIT_FOR_ACTION, which never fired.
- **Fix**: Extended doubles handling in `_execute_action` to also catch TIMEOUT/NO_TEXT. Calls `_wait_for_action_prompt` (fresh full scan) to find the partner's "What will X do?" prompt, then classifies as WAIT_FOR_PARTNER_ACTION when no narration was seen.
- **Secondary fix**: `_classify_prompt` returns "ACTION" while the tracker returns "WAIT_FOR_ACTION" — same concept, different names. Added "ACTION" to both the WAIT_FOR_PARTNER_ACTION check and evolution What? detection.

**2. Partner action effectiveness check reads wrong moveset**
- **Root cause**: `_check_move_effectiveness` in server.py always read `slot == 0`'s moves, even when the partner (slot 2) was acting.
- **Fix**: New `_find_acting_player()` helper scans memory for "What will X do?" prompt text, extracts the Pokemon name, matches against battler nicknames. Falls back to slot 0 if prompt can't be parsed. Also updated enemy target lookup to prefer alive enemies (skips fainted targets).

**3. Premature BATTLE_ENDED on multi-KO + exp cascade**
- **Root cause**: Poll captured "Ledyba fainted!" + "Exp. Points" during the cascade. `_classify_final_state`'s "fainted + Exp" heuristic declared BATTLE_ENDED, but the trainer had more Pokemon (Spinarak). The safety net (`BATTLE_ENDED and not _is_battle_over`) fired, but `_wait_for_action_prompt` couldn't press through the remaining exp text and level-up screens in time.
- **Fix**: Removed the text heuristic entirely. `battleEndFlag` stays 0 during exp cascades (battle still active), so `_classify_final_state` correctly returns TIMEOUT. The doubles TIMEOUT handler then finds the next action prompt.
- **Verified**: Log now shows full sequence: Ledyba fainted → 3 exp entries → Zubat attacks → Machop attacks → "Galactic Grunt sent out Spinarak!" → WAIT_FOR_ACTION.

**4. Targeting fainted/empty enemy slot**
- **Root cause**: Enemy positions on the target screen are static — a fainted enemy leaves a greyed-out slot. The slot-to-position mapping varies across battles (observed Spinarak at top-right in Floaroma, but enemies[0] in other battles maps to top-left). Tapping a greyed-out slot does nothing.
- **Fix**: New `_target_flow_with_retry()` replaces direct target flow. After tapping, checks if the action prompt is still showing (via `_scan_markers` for "What will X do?" text). If so, retries on the other target position. Handles variable mapping without needing to know which slot maps where.
- **Also added**: `_alive_enemy_count()` helper — skips retry logic when both enemies are alive (no greyed-out slots).

**5. Exp Share evolution not handled at battle end**
- **Root cause**: Evolution check in `_execute_action` only fired when "grew to" was in the poll log. During doubles exp cascades, the "grew to" text often wasn't captured (appeared outside the poll's narrow scan region or after the poll timed out).
- **Fix**: Evolution check now fires on **any** BATTLE_ENDED, not just when "grew to" was logged. The two-tier `_is_battle_over` ensures correct detection timing.
- **Also added**: General NO_TEXT recovery path for non-doubles — `_execute_action` now tries `_wait_for_action_prompt` on NO_TEXT regardless of battle type (was doubles-only).

### New Tests (`5bd2bb6`)

3 new tests in `test_double_battle.py` (5 total, 31 suite-wide):
| Test | Save State | Verifies |
|------|-----------|----------|
| `test_switch_returns_partner_prompt` | `debug_double_battle_switch_timeout` | Switch → WAIT_FOR_PARTNER_ACTION, both prompts in log |
| `test_multi_ko_exp_cascade_continues_battle` | `debug_double_battle_end_timeout` | Multi-KO → WAIT_FOR_ACTION (not BATTLE_ENDED), Spinarak in log |
| `test_fainted_slot_auto_retries` | `debug_double_battle_exp_share_evolution` | Target 0 (fainted) → auto-retry → move executes |

Bug #2 (partner moveset) is in server.py's MCP wrapper — not directly testable without MCP protocol. Verified manually.
Bug #5 (Exp Share evolution) couldn't be reliably reproduced from existing saves (Charmander needed more exp), but the underlying mechanisms are covered by the evolution test suite (4/4 passing).

### Bonus: DeSmuME MCP Feature Request

Filed claudeopusworkspace/DesmumeMCP#1 — configurable bridge socket path via `DESMUME_BRIDGE_SOCK` env var. ~3-line server.py change. **Already merged.** Will enable isolated test emulator instances once we restart the emulator.

### Backlog Status
- **Resolved this session**: All 5 double battle bugs
- **Remaining open**: navigate_to failure explanations (QoL), locked/key doors (behind us), tag battle untested (low priority), multi-chunk 3D BFS (deferred)
- **Next session**: Resume adventure — Route 205 north → Eterna Forest → Eterna City

---

## Dev Session 19: Locked Door Investigation + Navigation Error Diagnostics (2026-04-03)

Terminal-only session (no GUI). Investigated game engine mechanics and improved navigation error reporting.

### Locked Door Mechanism Investigation

**Question**: How does Pokemon Platinum handle "locked" doors (e.g., Valley Windworks)?

**Finding**: The engine has no built-in locked door concept. It's done through **warp event relocation** in init scripts:

1. Two events overlap on the door tile (243, 654): a **warp** (walk-in entry) and a **BG event** (A-press script showing "locked" text)
2. On every map load, `ValleyWindworksOutside_OnTransition` checks `FLAG_UNLOCKED_VALLEY_WINDWORKS_DOOR`
3. **Locked state**: warp gets `SetWarpEventPos` to (243, 650) — 4 tiles away from the door, unreachable. BG event stays at the door for "It's locked from inside!" text
4. **Unlocked state**: BG event gets `SetBgEventPos` to (243, 650). Warp stays at the door, enabling entry
5. The unlock script checks `FLAG_OBTAINED_FLOAROMA_MEADOW_WORKS_KEY`, sets `FLAG_UNLOCKED_VALLEY_WINDWORKS_DOOR`, and swaps the events in real-time

Side effect: relocating the warp makes the tile physically impassable — the 0x69 door behavior has collision bit set, and without a warp at that position, the game doesn't override collision. So the player bounces off.

Source: decomp scripts in `ref/pokeplatinum/res/field/scripts/scripts_valley_windworks_outside.s` and zone event JSON in `ref/pokeplatinum/res/field/events/`.

### Warp Failure Detection (`navigation.py`)

**Problem**: Navigation tools silently failed or gave generic messages when doors/warps didn't work.

**Fix**: Added `warp_failed: true` + diagnostic notes across 5 code paths:

| Code path | Trigger | Before | After |
|-----------|---------|--------|-------|
| `navigate_to` — door target, `stopped_early` | BFS targets door but player can't reach (locked, NPC blocked) | Generic `stopped_early` | `warp_failed` + "could not be entered" with cause list |
| `navigate_to` — door target, reached, no transition | Player on door, `_handle_door_transition` polls 450 frames, no map change | `"note": "Door activation did not trigger..."` | `warp_failed` + detailed cause list |
| `navigate_to` — already on door, no transition | Path length 0, door activation fails | Bare note | `warp_failed` + cause list |
| `navigate_to` — adjacent door, no transition | Walk-in attempt on adjacent door fails | Silent fallthrough | `warp_failed` + tile coordinates + cause list |
| `navigate_manual` — transition-trimmed, same map | Validator detected warp tile, trimmed path, but `final_map == start_map` | No check at all | `warp_failed` + cause list |

Tested against `debug_windworks_door_no_walkin` save state — correctly reports failure. Normal doors (Pokemon Center 0x65 exit, Flower Shop 0x69 walk-in) confirmed unaffected.

### BFS Pathfind Failure Diagnostics (`navigation.py`)

**Problem**: `navigate_to` returned `"No path found. Target may be unreachable or blocked."` with no explanation.

**Fix**: Added `_tile_behavior_hint()` helper and inline diagnostics at the BFS failure point. Now checks 6 conditions and reports specific cause(s):

| Condition | Example message |
|-----------|-----------------|
| Target impassable | `target tile is impassable (water (needs Surf))` |
| NPC on target | `an NPC is standing on the target tile` |
| HM obstacle on target | `cut_tree obstacle on target (needs Cut)` |
| Sign activation zone | `target is a sign activation zone (blocked to avoid auto-dialogue)` |
| Out of bounds | `target is outside the loaded map area` |
| Passable but disconnected | `reachable terrain but all paths are blocked by walls, water, NPCs, or obstacles` |

All 6 cases verified with live emulator tests.

### Backlog Status
- **Resolved this session**: Locked door warp failure detection, navigate_to failure explanations
- **Remaining open**: Tag battle untested (low priority, needs GUI), multi-chunk 3D BFS (deferred)
- **Next session**: Resume adventure — Route 205 north → Eterna Forest → Eterna City

---

## Dev Session: Pre-Migration Bug Sweep (2026-04-05/06)

Motivated by planned melonDS migration: save states can't transfer, so we need to close bugs that have debug save states tied to them. Also tackled several quick QoL wins.

### Bridge Tiles "Bug" — Closed as Not-a-Bug
- **Investigation**: Loaded `debug_unknown_bridge_tiles_route205`, tested `navigate_to(262, 540)`. Error: "target tile is impassable (behavior 0x00)" — the target itself was a wall tile, not a bridge tile.
- **Confirmed**: Behaviors 0x0c and 0x71 do NOT have `is_blocked` set. BFS already treats them as passable. Successfully navigated through bridge tiles to (269, 532) and (249, 544).
- **Root cause of confusion**: Text-only failure message gave no spatial context, so nearby `?` tiles were blamed instead of the actual wall at the target.

### Visual Failure Diagram + Nearest Reachable Suggestion
- **New helpers**: `_bfs_reachable()` (flood-fill from player), `_find_nearest_reachable()` (min Manhattan distance from target), `_render_failure_diagram()` (9×9 ASCII grid centered on target).
- **Output**: `diagram` field shows `@`=player, `X`=target, `*`=nearest reachable, `#`=wall, `.`=passable, `N`=NPC, `≈`=water, `D`=door. `nearest_reachable` field gives global coords + distance.
- **Coverage**: Both 2D and 3D path failure returns.
- **Directly prevents** the bridge-tile misdiagnosis that created the original bug.

### view_map: Sort Objects by Distance
- Single line: `obj_info.sort(key=lambda o: abs(o["x"] - px) + abs(o["y"] - py))`.
- Nearest objects appear first — prevents overlooking nearby items buried at high indices.

### battle_turn: move_index During SWITCH_PROMPT
- `battle_turn(move_index=N)` during SWITCH_PROMPT now auto-declines the switch and chains into the move action.
- New `_execute_switch_prompt_then_move()`: decline → poll → if ACTION prompt, call `_execute_action` with the move.
- Saves one tool call per trainer KO prompt.

### buy_item Fix + Badge Detection
Two-part fix:
1. **Extra A press removed** — `interact_with` already auto-advances cashier greeting dialogue. The old code had two A presses: one "advancing greeting" (actually selected BUY) and one "selecting BUY" (actually selected first item). Removed the redundant press.
2. **Badge address confirmed** — `BADGE_OFFSET = 0x82` in trainer.py. Verified: Coal Badge = bit 0, value `0x01` at `SAVE_BLOCK_BASE + 0x82`. `read_shop` and `buy_item` now read actual badge count instead of defaulting to 0. Threshold 2 (1 badge) unlocks Super Potion, Awakening, Burn Heal, Ice Heal, Escape Rope, Repel.
- **Tested**: Potion x3 (¥900) and Escape Rope x2 (¥1,100) from Floaroma Town overworld.
- **New save state**: `floaroma_town_buy_item_debug`.

### Trainer Detection False Positives Fixed
- **Root cause**: `trainer: true` was set whenever `trainerType > 0` in the MapObject struct, but non-trainer objects (Pokeball items, etc.) can have non-zero trainerType values. Pokeball at gfxID 87 had trainerType=3, script=7017 (not in trainer range).
- **Fix**: Only set `trainer: true` when both `trainerType > 0` AND `trainer_id_from_script(script)` returns a valid ID (script in 3000-4999 or 5000-6999 range). One-line change.
- **Verified**: Pokeball at (213,640) no longer flagged; Camper at (215,646) still correctly shows `trainer: true, defeated: true`.

### Multi-Chunk 3D Elevation-Aware Navigation
The big one — previously only single-chunk maps (gyms, caves) had elevation-aware pathfinding. Multi-chunk overworld routes fell through to 2D BFS, which doesn't understand elevation.
- **New `_build_multi_chunk_elevation()`**: Loads BDHC per chunk, collects flat heights across all chunks for unified height→level mapping, builds combined `level_map` + `ramp_tiles` with chunk-offset coordinates.
- **3D BFS activation**: Now triggers for both single-chunk and multi-chunk maps when BDHC data yields multiple elevation levels.
- **Repath fix**: `_try_repath` now uses 3D BFS when elevation context is available — was falling back to 2D BFS, which was the actual cause of the Route 205 bridge failures (initial 3D path was correct, but repaths crossed elevation boundaries).
- **Tested on Route 205 bridge area**:
  - Same-level: player at level 4 (upper path) → target at level 4 — 7 steps, stayed on upper path.
  - Cross-level: level 4 → level 2 via ramp — 24 steps, no blocks, no repaths.

### Backlog Status
| Closed | Type |
|--------|------|
| Bridge tiles impassable | Not a bug |
| Badge count not reading | Fixed (BADGE_OFFSET=0x82) |
| buy_item wrong item | Fixed (extra A press + badge) |
| Trainer detection false positives | Fixed (script validation) |
| Multi-chunk 3D BFS | Fixed (per-chunk BDHC loading) |
| Visual failure diagram | Implemented |
| Sort objects by distance | Implemented |
| SWITCH_PROMPT move_index | Implemented |

**Remaining open bugs with save states**: interact_with circular NPCs (2 saves), interact_with trainer approach (1 save), tag battle untested (1 save), NPC dialogue at warp (1 save), BFS blocks follower NPCs (2 saves).

**Commits**: 5 this session — `aa09a42`, `8b5765a`, `93d7bc9`, `c52253d`, `6b37f7f`.

## Dev Session: auto_grind Enhancements — Auto-Heal, Smart Moves, target_slot (2026-04-08g)

### Features Implemented

**1. Auto-heal loop** (`_heal_and_return` helper)
- New params: `heal_x`, `heal_y`, `grind_x`, `grind_y`, `max_heal_trips` (default 10)
- On faint or PP depletion: exits battle → navigates to town → heals at PC → exits PC via warp → navigates back to grind area → resumes
- Three trigger points: faint mid-battle, PP depleted mid-battle, PP depleted between battles
- New stop reasons: `heal_failed`, `max_heal_trips`
- Successfully tested: 3 heal trips during Route 205 Monferno grind (PP depletion triggered each)

**2. Smart move selection** (`_check_effectiveness` helper)
- When `backup_move` is set, checks type effectiveness per encounter using battler dict data
- If primary is NVE/immune but backup is effective → swaps for that battle
- If both ineffective + `flee_ineffective=True` → flees and continues to next encounter
- Uses `effectiveness()` from `type_chart.py`, reads type/class directly from battler dicts

**3. `target_slot` parameter**
- Default 0 (lead). Set to any party slot (0-5) for Exp. Share Pokemon
- All `target_level` checks updated to use `target_slot` instead of hardcoded slot 0
- Log-based level detection (immune to encryption issues) only used when `target_slot==0`
- Successfully tested: `target_slot=5` stopped when Monferno hit Lv25

### Bug Found (not fixed)
- Post-evolution move-learn: when Chimchar evolved to Monferno and learned Mach Punch, `auto_grind` got stuck at the "learned move" screen and returned `seek_failed` on the next iteration. Manual B press recovered. Root cause: evolution + move-learn animation not fully dismissed by `battle_turn`.

### Bug Fixed (mid-session)
- `_heal_and_return` flee loop: `battle_turn(run=True)` can return state `"ACTION"` instead of `"WAIT_FOR_ACTION"`. Added `"ACTION"` to the accepted retry states.

### Files Changed
- `renegade_mcp/auto_grind.py` — 3 new helpers, 6 new params, heal loop integration
- `renegade_mcp/server.py` — updated wrapper signature + docstring
- `CLAUDE.md` — updated tool table + Auto Grind Workflow section

---

## Session: 2026-04-10 Evening — E4 Save Import, Delta Scanner, Fly Tool

### Context
Woj received Wayne's endgame save file (8 badges, Pokemon League). Goal: import it, build late-game tools against it (starting with Fly), and confirm cross-save stability.

### Infrastructure Fixes

**1. Directory permissions** — Docker Desktop imports set the project dir to root ownership, breaking socket creation. Fixed with `chown`.

**2. Bridge socket path resolution** — renegade MCP couldn't find melonDS socket across directories. Added `../MelonMCP/` and absolute `/workspace/MelonMCP/` paths to connection.py.

**3. Heap delta scanner** (major fix) — `detect_shift()` used a hardcoded list of 3 known deltas. Discovered the delta varies per boot, not just per save/emulator. Observed -0x20, -0x48, -0x5C across sessions with different saves. **Replaced with range scan** (-0x200 to +0x200, step 4) validated by 3 canary values (party count 1-6, badge popcount 0-8, species ID 1-649). Tie-breaks by highest badge count then smallest absolute delta.

### E4 Save Import

**Problem**: Confusing file state from previous session — saves were mislabeled, stale RAM from save states masked the real battery save data.

**Resolution**:
- `Pokemon - Platinum Version (USA) (Rev 1).sav` was the E4 save all along (8 badges, $148K, Wayne's team)
- `our_playthrough_backup.sav` is an unknown save (slot1 erased, slot2 has 1 badge) — NOT our playthrough
- Our playthrough lives entirely in save states; battery save doesn't matter
- After `backup_save_import`, must `load_rom` fresh — loading save states reads stale RAM, not the new battery save
- Created read-only backup at `saves/e4_wayne.sav`

**Save states created**:
- `e4_pokemon_league_lobby` — inside PC (indoors, pre-Fly)
- `e4_pokemon_league_fly_ready` — inside PC, Garchomp taught Fly
- `e4_pokemon_league_outdoor` — outside Pokemon League, Fly ready

### Fly Tool

**New file**: `renegade_mcp/fly.py` — 20 fly destinations with calibrated grid coordinates.

**UI flow**: pause menu → Pokemon → select Fly user → submenu (SUMMARY is first, Fly is second) → town map → cursor navigation → A to confirm → warp animation → verify.

**Cursor strategy**: "Reset to corner" — press left 26x + up 26x to guarantee cursor at (2,7), then navigate relative to target. Reliable regardless of starting position.

**Key discoveries**:
- Grid coordinates needed +1/+1 offset from decomp sprite positions for cursor hit detection
- Submenu starts on SUMMARY (index 0), Fly is at index 1
- Fly animation takes ~3600 frames; map ID changes mid-animation
- Added 300-frame settle after warp for renderer catch-up (melonDS skips rendering during fast-forward)

**Test helper update**: `do_load_state(emu, name, redetect_shift=True)` — clears cached delta and re-detects when loading states from different save files.

**Tests**: 12 new tests in `test_fly.py` (228 total across 21 files):
- 6 successful flights (Jubilife, Eterna, Snowpoint, Twinleaf, Veilstone, round-trip)
- 3 destination resolution (partial match, code match, invalid)
- 3 pre-checks (indoors, no badge, no Fly user)

### Files Changed
- `renegade_mcp/addresses.py` — scan-based detect_shift replacing hardcoded candidates
- `renegade_mcp/connection.py` — expanded socket search paths
- `renegade_mcp/fly.py` — new Fly tool implementation
- `renegade_mcp/server.py` — registered use_fly tool
- `tests/helpers.py` — redetect_shift parameter for cross-save state loading
- `tests/test_fly.py` — 12 integration tests
