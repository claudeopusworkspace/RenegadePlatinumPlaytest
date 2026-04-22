# Dev History

Chronological log of tool development, bug fixes, and MCP improvements — separate from gameplay in GAME_HISTORY.md.

Older entries (2026-04-14 and earlier) live in [DEV_HISTORY_ARCHIVE.md](DEV_HISTORY_ARCHIVE.md).

## Dev Session: Berry-patch state in view_map (2026-04-22 session 30c)

Ran in parallel with a live playthrough agent on `.melonds_bridge.sock`; all dev work used a dedicated test emulator on `.melonds_test_bridge.sock` and throwaway probe scripts in `/tmp`.

Soil map-objects (graphics_id 100) previously surfaced as bare `"Berry Patch"` labels with no state. They now resolve to their `BerryPatch` record and carry full state in the interactible preview — berry ID, growth stage, yield, moisture, mulch, `harvestable`.

### How it works

- `MapObject.data[0]` (offset 0x38 in the 0x128-byte slot, after 9 u32 header fields + 5 direction ints) holds the 0-127 berry patch index. `map_state.read_objects` now unpacks 15 u32s instead of 9 and exposes `data0`.
- The `BerryPatch` array — 128 entries of **14 bytes each**, not 16 — lives at `SAVE_BLOCK_BASE + 0x20C4`. Added as `BERRY_PATCH_BASE = 0x02280294` in `addresses.py` (rides the default `save_block` delta group).
- New module `renegade_mcp/berry_patches.py` decodes one record: berry ID (1-based, `item_id = berry_id + 148`), growth stage enum, yield, moisture rating, mulch type, is-growing flag, plus convenience fields (`harvestable`, moisture label, berry name via `data.item_names()`).
- `_classify_object` tags soil previews with `patch_id`. `_build_interactibles` (which has `emu` in scope) reads the record and merges it into `preview.patch`, upgrading labels to e.g. `"Rawst Berry (ripe x1)"`, `"Razz Berry (growing)"`, or `"Empty Berry Patch"`.

### Investigation notes

- Decomp sub-agent claimed struct size was 16 (alignment padding). Empirical probe against `session30_route206_under_bridge` proved it's 14: stride=16 produced garbled yields and stages; stride=14 decoded cleanly with the opening slots matching `sBerryInitTable` (Oran, Cheri, Chesto, Pecha, Oran, Pecha, Razz, Bluk…). Last field is `u8 isGrowing`, so alignment only requires struct size to be even — 14 already is.
- Can't derive MiscSaveBlock's address arithmetically from `SAVE_BLOCK_BASE` (which is actually the PLAYER save-table entry). Each save section has its own `pageInfo[id].location` computed at runtime from the preceding entries' sizes. Found it instead via the rival-name signature ("WOJ" + 0xFFFF terminator), which lives at a known offset inside MiscSaveBlock (`+0x824` past the berry array, through 36 bytes of `PersistedMapFeatures`).
- Slots 120-127 can hold uninitialized sBerryInitTable tail bytes with out-of-range values; the reader returns `None` for `berry_id > 64` or `stage > 5` and the caller falls back to `"Empty Berry Patch"`.

### Verification

New test `TestBerryPatchState::test_soils_resolve_to_planted_rawst_and_razz` in `tests/test_map_tools.py` — four soils at (293-294, 627) and (295-296, 691) on `session30_route206_under_bridge` all decode to planted FRUIT-stage patches (Rawst × 2, Razz × 2). Existing 87 map/hm_obstacles/bug020 tests still green after the `read_objects` unpack widening. Memory note in `reference_berry_patches.md`; address table in `MEMORY_MAP.md`.

## Dev Session: Fix view_map under-bridge elevation misclassification (2026-04-22 session 30b)

Three-pronged fix for an interlocking bug cluster on Route 206 at (310, 608) (Cycling Road bridge overhead, player on the ground plate underneath). Repro: `session30_route206_under_bridge`. Before the fix, `view_map` reported bridge-level Cyclists as reachable from under the bridge, AND the ground-level Wayward Cave warp sitting directly beneath one of those Cyclists as unreachable. Same (x, y), opposite verdicts — clear signal that elevation info was being dropped inconsistently between the BFS and the POI classifier.

### Investigation

Followed the "instrument before theorize" rule. Added a debug dump inside `view_map` capturing the 3D BFS state at key tiles, then ran it via `reload_tools` so the live MCP process (with correct heap-shift detection) produced the data. Found three independent defects chained together:

1. **ML teleports** — `_record_transitions` in `pathfinding.py` treated any tile whose BDHC reported multiple flat plates as a free level-switch point. Route 206 has ~16 under-bridge tiles where the bridge plate at h=112–140 physically overlaps the ground plate at h=16. The unconditional ML transition let the L1 flood "climb" to L11/L12/L14 in one step (a 96–124 unit vertical leap) and flood the bridge plate, making every on-bridge POI appear 2D-reachable.
2. **Ramp shadows flat plates** — `_tile_on_level` returned early whenever a tile was in `ramp_tiles`, never consulting `level_map`. For tiles like (299, 617) which BDHC reports as BOTH a 14→12 bridge ramp AND a ground L1 flat plate, the function said "not on level 1" and blocked the L1 flood from crossing its own plate. Ground player couldn't walk under the bridge ramp even though the ground was clearly there.
3. **2D-keyed reach + elevationless NPCs** — `_bfs_reachable_3d` flattened its output to `dict[(x, y), int]`, losing the level dimension the flood had just computed. `npc_set` was a 2D `set[(x, y)]`, so a Cyclist at (299, 611) h=140 on the bridge blocked the ground plate at the same tile. And `_build_interactibles` checked 4-adjacent reachability against the 2D reach without regard to the POI's own level — so a bridge trainer whose approach tile happened to also be reached at ground level was flagged reachable.

The probe found the final piece: **objects carry a Y-height field in the MapObject struct that `read_objects` was discarding**. The three u32s at OBJ+0x70 are (fpx, fpy_height, fpz) — `read_player_height` has been reading the middle u32 all along, and it's the object's own world height for the other 63 slots too. Parsing it gave clean elevation tags per POI: Bridge Cyclists at h=96–152, under-bridge items/hikers at h=16, post-gatehouse objects at h=0.

### Fix

All edits in `renegade_mcp/`:

- **`pathfinding.py::_record_transitions`** — ML transition gated by `_steppable()` (height diff ≤ STEPPABLE_HEIGHT=4). Overlap tiles no longer teleport between physically separated plates.
- **`pathfinding.py::_tile_on_level`** — rewritten to check both ramp plate and flat plate independently; accept the tile if either source permits the level. Ground under an overhead bridge ramp is no longer hidden.
- **`pathfinding.py::_flood_fill_level`** — `npc_set` accepts 3D `{(x, y, level)}` in addition to 2D (auto-detected from first element's tuple arity). 3D mode blocks only `(nx, ny, current_level)`, so a bridge-level NPC doesn't wall off the ground plate beneath them.
- **`pathfinding.py::_bfs_reachable_3d`** — return type changed from `dict[(x, y), int]` to `dict[(x, y, level), int]`. Preserves the level dimension the per-level floods compute anyway; its one caller (view_map) needs that dimension for POI classification.
- **`map_state.py::read_objects`** — now parses `fpy_height` from the discarded middle u32, applies fx32 → float conversion matching `read_player_height`, and exposes `obj["height"]`.
- **`map_state.py::view_map`** — builds a 3D npc_set using each non-follower NPC's level (via `_height_to_level(o["height"], mc_elev, tile_x, tile_y)`), computes `object_levels[idx]` for the classifier, derives a 2D-collapsed `reachable_tiles` for back-compat, and packages the 3D reach + elevation + origin + per-object levels into a `reach_info_3d` dict passed down.
- **`map_state.py::_build_interactibles`** — when `reach_info_3d` is present, 4-adjacent check becomes `(adj_x, adj_y, obj_level) in reach3d` instead of `(adj_x, adj_y) in reach2d`. Falls back to the original 2D path on flat maps where no 3D data exists.
- **`map_state.py::_merge_adjacent_warps`** — warp reachability requires the warp's own tile to be in `reach3d` at SOME level that the tile actually has in `level_map[(wx, wy)]`. Picks the smallest step count across candidate levels.

### Verification

Ran `view_map` live on the repro save:

| POI | Before | After |
|-----|--------|-------|
| obj:2 Cyclist (299, 611) h=140 | reachable 35 steps ❌ | **unreachable** ✓ |
| obj:3 Cyclist (304, 622) h=124 | reachable 21 steps ❌ | **unreachable** ✓ |
| obj:4 Cyclist (304, 631) h=112 | reachable 30 steps ❌ | **unreachable** ✓ |
| warp:7 Wayward Cave (299, 611) | unreachable ❌ | **reachable 26 steps** ✓ |
| obj:21 Hiker (311, 622) h=16 | reachable 14 | reachable 14 ✓ |
| obj:22 Hiker (292, 643) h=0 | reachable 56 ❌ | **unreachable** ✓ (post-gatehouse, actually on map 351) |

Other bridge-level trainers that were previously reachable-only-via-phantom-bridge-flood (obj:1, 5, 7) stay unreachable; post-gatehouse objects (obj:9 Arrow Signpost, obj:17/18 Berry Soils at h=0, obj:19 Trainer Tips Signpost) correctly become unreachable — they were spuriously reachable before because the BFS was flooding across elevation boundaries.

4 new tests in `TestBug038UnderBridgeReachability` (warp reachability, two bridge-cyclist unreachability asserts, ground-hiker still-reachable regression guard). Full suite: **520 passed @ 2:31 (N=8)**. BUG-029's two tests still pass — the new `_tile_on_level` logic is strictly more permissive for legitimate tiles and the BUG-029 repro (on-bridge player, bridge Pokeball reachable, under-bridge Pokeball unreachable) is unaffected.

### Take-away

The probe-first discipline paid for itself. The 2D-vs-3D npc_set and the ML-teleport gate were obvious in hindsight, but the `_tile_on_level` ramp-shadows-flat case would have been easy to miss — I had to be *sitting* on `_dbg_lines.append(f"_tile_on_level(75,73,1)=False ... ramp(from=14,to=12)")` before I realized a tile could have both plate types. Also — the object height field was in the struct all along. 60 other tools use the MapObject array; nobody parsed the middle u32 because `read_player_height` reads it separately and nothing had a reason to ask "how high is that Cyclist?" Cheap reads, high leverage — worth sweeping the other struct fields when working in this area next.

### BUG-040 filed + closed in session

Tracking ID BUG-040 assigned to the elevation misclassification cluster. Opened, fixed, tested, and committed within the same session. No bug-backlog entry added to memory (per repro documentation feedback — the fix is in the code and the tests pin the behavior; commit message + this entry carry the narrative).

## Dev Session: Fix view_map BFS chunk window (2026-04-22 session 30)

Pure dev session — no gameplay advance. Woj asked me to investigate save `bug_view_map_false_unreachable_wayward` (Wayward Cave main, (73, 29)): `view_map` was reporting 11 unreachable interactibles including `warp:1 to Route 206 (41, 53)` — the entry warp we had physically used earlier in the playthrough. One commit landed: `48432e4`.

### False hypothesis first

Initial read of the terrain dump + BDHC looked damning: all 4 loaded chunks reported a single flat height (16), chunk (1,1) had one isolated ramp with a −16/+16 span that no other plate connected to, and map 285 (the Wayward Cave sub-cave) clearly forms a bridge between the two disconnected halves of map 284. Filed BUG-039 as a cross-map reachability problem, suggested fixes ranging from a dest-map heuristic up to a full cross-map BFS.

Woj pushed back: "if this is the case, why does manually entering the coordinates for (41, 53) into navigate_to manage to navigate to the warp from the save state in question? I'm fairly certain it doesn't cross through any warps." Ran `navigate_to(x=41, y=53)` — succeeded in 137 steps with a single-map path: `left 19 → up 14 → left 8 → up 12 → left 18 → ...`, looping up through the northern branch at y≈3 (which spans x=27..46), down the west side, and back east to the warp. Entirely within map 284. Cross-map hypothesis disproven.

### Real root cause

`view_map` called `_build_multi_chunk_terrain(emu, map_id, px, py, vp_x+vp_w-1, vp_y+vp_h-1)` — the "target" passed to the chunk-bounding logic was the **viewport's bottom-right corner**, not any actual POI. For player chunk (2, 0) and viewport-br chunk (2, 1), the function loaded chunks (1..2, 0..1) = x[32, 96), leaving chunk column 0 (x[0, 32)) unloaded. The northern-branch connector at y≈3 passes through x=27..31 — tiles that don't exist in the BFS terrain grid — so the flood couldn't close the loop back down to (41, 53), and the 6 west-wing trainers at x<32 weren't even in bounds. `navigate_to` sidestepped this accidentally: when it knows the real target coord, the same function expands `min_cx` down to 0 and loads the full matrix.

### Fix

- **`pathfinding.py`** — added `extra_targets: list[tuple[int,int]] | None` parameter to `_build_multi_chunk_terrain`. When supplied, every point contributes to the chunk-bounding box. 5x5 cap preserved; the trimming rule now branches: with extras (view_map), center on the player (flood origin) so we'd rather drop distant POIs than miss the player's own chunk; without extras (navigate_to, interaction), keep the old player↔target midpoint so both endpoints stay in bounds.
- **`map_state.py`** — `view_map` now collects every object tile plus every warp tile from `read_warps_from_rom` and passes them as `extra_targets`. Docstring comment cross-references BUG-039.

### Verification

Re-ran the repro after `reload_tools` + `load_state`:
- Before: **11 unreachable**.
- After: **4 unreachable** — `warp:0 (30,55)`, `warp:2 (28,54)`, `warp:3 (55,54)`, `obj:1 Pokeball (57,53)`. All four are in the southern ground plaza that really is 2D-disconnected within map 284 and only reachable via map 285. Left as-is; cross-map BFS isn't worth the complexity for a handful of dungeon warps.
- Reachable POIs show exactly the step counts the full-matrix diagnostic predicted: `warp:1 (41, 53)` = 138 steps, west-wing trainer interaction tiles = 104..135 steps.

Full suite: **516 passed in 2:31 @ N=8**. Diagnostics preserved: `scripts/diag_view_map_bug.py` (narrow-window behavior, BDHC per-chunk dump, behavior-byte histogram, raw terrain passability overlay) and `scripts/diag_view_map_fullmatrix.py` (proves the full-matrix flood reaches every in-map POI).

### Take-away

The surprising part wasn't the bug — it was how plausible the cross-map theory looked before I tested the alternative. Two things saved us. (1) Woj cross-checked with `navigate_to` and it produced an actual 137-step path, which is something my diag script hadn't done. (2) Expanding the same BFS over the full matrix was cheap (one `_load_viewport_terrain` call) and immediately showed 1447 reached tiles vs 749. Once that number nearly doubled, the cross-map theory was dead — you can't pick up 700 single-map tiles by adding a map boundary. General lesson: when a reachability tool disagrees with ground truth, instrument the *same* algorithm with looser inputs before theorizing about topology. Cheap dial turns beat clever theories.

## Dev Session: Retire BUG-024 length guard (2026-04-22 session 29)

Mid-playtest, the BUG-024 "wander guard" (introduced session 19) fired inside Wayward Cave on what looked like legitimate navigation: `navigate_to(x=73, y=29)` from (72, 10) returned `No reasonable path ... BFS path is 136 steps for a 20-tile Manhattan distance`. The cave's east half has two chambers connected by a single ~100-step winding corridor — the path is real, the ratio just exceeds `max(manhattan*5, manhattan+30)`. Breaking the trip into two legs worked around it, but every cave/dungeon run was going to keep eating this false positive.

### What the guard was for, and why it's now redundant

BUG-024 repro is `route206_cyclingroad_end_nav_repro`: player standing on a side-S warp tile at (302, 681) at the south end of a Cycling Road gate house, target is the side-N warp at (302, 688) — 7 Manhattan tiles away, no walkable connection, only reachable by stepping through the gate house via warp. Pre-fix, BFS found a 93-step detour that looped most of the overworld and ended nowhere useful. The fix rejected paths exceeding the ratio threshold with a clear error + warp hint.

Retested live with the guard disabled. Expected the pathological wander to return. It didn't — the **BUG-030 elevation validator** (session 21) now rejects the same call earlier, with a more specific message:

```
"No reasonable path at your current elevation (level 3).
 The 2D fallback would step between incompatible layers.
 Try a ramp or warp first, or use `navigate` with explicit directions."
note: "You are standing on a directional warp tile.  Trigger it
 with `press_buttons(['down'])` to transition, then navigate
 from the other side."
```

Player on the Cycling Road bridge is level 3; target under the bridge is level 0. BUG-030's validator catches the layer-crossing attempt before the length guard ever gets a chance to look at the path. Same outcome (clean error, warp hint, no player movement) — different trigger point. The existing `TestQaBug024SideWarpCluster` test class already documents this in its docstring: *"Post-BUG-030: navigate_to no longer falls back to 2D BFS on elevated maps, so the refusal now fires from the elevation path rather than the sanity-cap step-count check."* The assertions (`"No reasonable path"` substring, `manhattan == 7`, `"down"` in note, no movement) all still pass via the BUG-030 path.

### Fix

`renegade_mcp/navigation.py:1225-1257` — deleted the length-guard block, left a comment explaining the BUG-024 scenario is now caught by BUG-030's elevation validator. No tests changed; `TestQaBug024SideWarpCluster` asserts on behavior-outcome and already passes via the elevation path (confirmed by the docstring note added in session 21).

### Flat-map warp clusters — unresolved residual risk

Theoretically, a gate house or side-warp cluster on a *flat, single-elevation* map could still produce the original pathological wander. The BUG-030 validator only rejects layer-crossing, so it wouldn't catch a wander on a flat map. I haven't found such a map in practice yet. If one surfaces, the right fix is probably the surgical option floated in session 29 (skip the guard when origin tile is *not* a warp) — the BUG-024 pathology requires the player to be standing on a warp for BFS to re-seed on the wrong cluster member.

### BUG-038 repro filed (not fixed)

Separate from the guard work: mid-Ruin-Maniac-fight, Togepi rode an Exp. Share from Lv1 to Lv9 in one battle, cascading through multiple move-learn prompts. Two tool issues surfaced: `battle_turn(forget_move=0)` at one learn advanced straight to SWITCH_PROMPT without a "learned Metronome" log entry (commit happened, but the log skipped it), and `battle_turn(forget_move=-1)` at a later learn returned `final_state=NO_TEXT` while the "Make it forget another move?" box was still on-screen. Also mid-transition `read_party` returned stale save-block data. Checkpoint saved as `bug_togepi_cascade_levelup` (frame 42674 of this playthrough) with full repro steps documented in SAVE_STATES.md + memory backlog. Not blocking — we worked around with manual B-presses.

## Dev Session: Party sub-menu offsets + reorder_party verify (2026-04-21 session 27)

Short targeted fix session, one commit (`e6513bb`). Playtest instance filed BUG-033: `reorder_party(from=0, to=3)` reported `success: true` but nothing swapped. Grotle at slot 0 knows Cut, Monferno at slot 3.

### BUG-033: `reorder_party` silently reports success when source Pokemon knows a field move

**Root cause verified in decomp** (`src/applications/party_menu/main.c:1793` — `GetContextMenuEntriesForPartyMon`): the overworld party context menu is built as `Summary → [field moves in moveset order] → Switch → Item → Cancel`. The field-move list comes from `sFieldMoves` (main.c:245) — 15 Gen-4 moves (Cut, Fly, Surf, Strength, Defog, Rock Smash, Waterfall, Rock Climb, Flash, Teleport, Dig, Sweet Scent, Chatter, Milk Drink, Softboiled). A move appears as a row iff the Pokemon knows it — independent of whether the move is currently usable in the environment.

Grotle's Cut pushes Switch from row 1 to row 2, so the tool's `down x1 → A` landed on Cut instead. "Can't use Cut here" dialog opened, subsequent D-pad / A presses got absorbed by dialogue text, and the tool returned unchanged party data with `success: true`.

**Two distinct bugs, one repro save** (`bug_reorder_party_fails_silently_with_field_move`):
1. Cursor nav didn't account for field-move rows pushing Switch / Item down.
2. Tool never verified the swap actually committed before returning success.

### Fix

- **New `renegade_mcp/party_submenu.py`** — shared helpers consuming a `read_party` mon dict:
  - `FIELD_MOVES` frozenset (all 15 moves, lowercase).
  - `count_field_moves(mon)` — total field moves in moveset.
  - `count_field_moves_before(mon, target_move)` — for `use_fly`'s navigate-to-Fly-row use case.
  - `switch_row(mon)` → `1 + count_field_moves(mon)`.
  - `item_row(mon)` → `2 + count_field_moves(mon)`.
- **`reorder_party.py`** — reads party before the operation, computes `switch_row(source_mon)` for the cursor offset, then after closing menus re-reads and compares `species_id` before/after. If either slot doesn't hold the expected species, returns `success: False` with a diagnostic message naming both sides. Species ID comparison rather than name (name can be a nickname; same-species pairs would slip a name check).
- **`give_item.py` / `take_item.py`** — replaced the hardcoded `ITEM_OPTION_OFFSET = 2` with `item_row(target_mon)`.
- **`fly.py`** — consolidated its local `_count_field_moves` onto `count_field_moves_before`. The old local list was missing Flash, Teleport, Dig, Sweet Scent, Chatter, Milk Drink, Softboiled — harmless for Fly's current tests (no party Pokemon with Fly + Teleport in the same moveset), but a latent mismatch now erased.
- **`teach_tm.py` / `use_item.py`** — inspected, no change needed. TM flow goes bag → USE → YES → party select → auto-advance (no sub-menu). Item flow goes bag → item → USE → party select (no sub-menu).

### Tests

- **18 unit tests** in `tests/test_party_submenu.py` — no emulator, pure dict-shape exercises. Covers empty moveset, non-field moves, single/multiple field moves, case-insensitivity, `target_move` first / last / missing.
- **1 new integration test** `TestReorderParty::test_swap_when_source_knows_field_move` — loads the repro save, asserts slot 0 knows a field move as precondition, calls `reorder_party(0, 3)`, asserts species IDs actually swap. Pins the regression.
- The existing two reorder tests use `eterna_city_shiny_swinub_in_party` where slot 0 is Luxio (no field moves), which is why they passed while the bug was live — swapping to a save with a field-move holder was the unlock.
- Full suite: **516 passed in 2:30 @ N=8**.

### Take-away

The local `_count_field_moves` in `fly.py` was already doing the right thing for its own use case, but the pattern never got lifted to a shared helper. Three tools (`reorder_party`, `give_item`, `take_item`) independently hardcoded a static offset that was only valid when the Pokemon knew zero field moves. Worth a scan for similar "looks constant, actually depends on Pokemon state" offsets in UI drivers. Also a reminder: every UI-driving tool should verify the state actually changed. `give_item` and `take_item` already did; `reorder_party` didn't; now it does.

## Dev Session: Nav bug parade + pytest owns the fleet (2026-04-21 session 26)

Long session. Ran in parallel with a playtest instance that filed six repro saves as it hit fresh issues in Wayward Cave. Pattern was: playtest instance checkpoints the anomaly, writes repro notes, I diagnose and fix while they keep playing. Six commits landed: `b862449`, `8b024dc`, `5fbeb64`, `11c4c25`, `cf16155`, `bd12380`.

### BUG-034: Mira reported unreachable despite standing 14 steps away

Repro save `session23_end_with_mira`, player at (42, 53), Mira at (38, 42). `view_map` dropped Mira into `unreachable_interactibles` even though the corridor between them was wide open.

**Root cause.** On chunked maps, `_build_multi_chunk_elevation` returns `None` when BDHC reports a single flat height across all loaded chunks (common for one-floor caves). With `reach_3d_ok = False`, the 2D fallback flooded only the **15×15 render viewport**, not the full multi-chunk extent. Mira at y=42 is 4 tiles north of the viewport top (y=46); the flood hit its own edge and classified everything outside as unreachable.

**Fix (`map_state.py`).** Stash the `mc_ox/mc_oy/mc_w/mc_h` extent when `_build_multi_chunk_terrain` succeeds. On fallback, call `_load_viewport_terrain(…, mc_ox, mc_oy, mc_w, mc_h)` to build a u16 terrain for the whole multi-chunk extent and flood on that instead of `vp_terrain`. The 3D path for elevated maps (Cycling Road under-bridge) is untouched — when `mc_elev` resolves, `reach_3d_ok = True` and the flat-fallback branch never runs. Test: `TestFlatMultiChunkReachability`. Full suite 492 passed in 2:34.

### BUG-035: Follower Mira blocks BFS; (0,0) hidden objects pollute output

Second repro save, same cave. Player at (39, 42) facing left, Mira at (38, 42) — the only east-west link in the chamber. Every POI west of her plus east-wing trainers/Pokéballs all dropped into `unreachable_interactibles`. Also 11 "Rock Smash" entries at (0, 0) cluttered the list at distance=95.

**Root cause.** Gen 4 follower NPCs (Mira, Cheryl, rival escorts) swap places with the player when the player steps onto their tile — the tile is effectively passable. But every BFS call site added non-player objects to `npc_set` unconditionally, walling off narrow escort corridors. Separately, Drayano disables unused `zone_event` entries by parking them at (0, 0) instead of deleting them, producing a dozen decoy POIs per map.

**Fix.** Confirmed against `pret/pokeplatinum`'s `generated/movement_types.txt`: `MOVEMENT_TYPE_FOLLOW_PLAYER = 48`, `MOVEMENT_TYPE_FOLLOW_PARTNER_TRAINER = 50`. Exposed `movement_type_id` as a new field on `read_objects` output. Added `is_follower_npc(obj)` helper in `nav_constants.py`. Every BFS call site now skips followers at the source: `view_map`'s 3D + 2D flood, `_build_terrain_info`, `_classify_objects_for_grid`, `_read_npc_positions`, and `interaction.py`'s multi-chunk builder. `_build_interactibles` drops any object whose `(x, y) == (0, 0)` before classification.

**Scoping guardrail.** Only mv=48/50 qualify. In `session23_end_with_mira`, idle post-battle Mira has mv=16 (`LOOK_SOUTH`) and still blocks. `test_non_follower_npc_still_blocks` pins this so a future refactor can't accidentally widen the follower check.

### BUG-036: `flee_encounters=True` ignores wild doubles

Third repro. `navigate_to(poi="obj:15", flee_encounters=True)`, path "right x3" to Hiker Lorenzo. A tag-partner 2v2 wild double (Luxray + Mira's Kadabra vs Geodude + Baltoy) fires mid-approach. Tool surfaces the battle uncontested — flee never attempted.

**Diagnosis.** Not a doubles problem at all. Verified against decomp that `BATTLE_TYPE_AI_PARTNER = DOUBLES | 2vs2 | AI` — no `BATTLE_TYPE_TRAINER` bit, so flee is permitted and a single RUN tap escapes the whole side. The flee plumbing in `interact_with` only sat in the `stopped_early` branch (encounter fires mid-walk). When `_execute_path` signed off on all 3 steps and the encounter triggered during the subsequent face-target turn, `facing_seized=True` latched and the branch at `interaction.py:443` returned the encounter directly without ever consulting `flee_encounters`.

**Fix.** In the `facing_seized` branch, route wild encounters through the same `_try_flee_encounter` helper the `stopped_early` branch uses. On successful flee, settle the overworld, re-attempt the turn, and fall through to the existing A-press path so the NPC's dialogue / trainer battle runs cleanly. Flee failures carry the same `flee_failed` exit shape. Test: `test_flee_encounters_during_face_target` on new save `bug_flee_encounters_ignores_wild_double`.

### FR-010: BFS cap 150 → 250 for winding dungeons

Woj's ask after practical use. 150 was tight enough that Wayward Cave's end-of-map POIs (and likely Mt. Coronet / Victory Road) fell into `unreachable_interactibles` despite being walkable. Bumped `MAX_REACH_STEPS` in `map_state.py`; updated the matching figure in `server.py`'s `view_map` docstring. Suite still green in 2:32.

### Test infrastructure: pytest owns the fleet lifecycle

**Trigger.** Earlier in the session I `pkill`'d the fleet, committed, and left. The playtest instance's very next `pytest` silently landed on the playthrough emulator — because conftest's fallback list included `.melonds_bridge.sock`. Save states got loaded over the playtest's active state. Checkpoint ring buffer saved the work; discussed with Woj, agreed on a rewrite.

**Changes (`cf16155`).**
- `scripts/start_test_emulators.py` refactored to expose importable `start_fleet(count)` / `stop_fleet(procs)` on top of the existing CLI wrapper. `start_fleet` now probes each socket for liveness before returning, rather than just checking file existence — tighter against boot races.
- `tests/conftest.py` adds `--fleet-size=N` (default 8, 0 skips auto-spawn). `pytest_xdist_auto_num_workers` — master-only hook, inherently skipped in xdist worker subprocesses — spawns the fleet when none is live and stashes the procs on a module-level list. `pytest_sessionfinish` tears down only what we spawned; reused pre-booted fleets are left alone.
- `.melonds_bridge.sock` removed from `_BACKENDS` fallback. Remaining fallback (`.melonds_test_bridge.sock`, standalone) now liveness-probed. The `emu` fixture `pytest.skip`s with a specific message if nothing's up.

**One landmine caught mid-flight.** Initial attempt put the spawn in `pytest_configure`. xdist's `pytest_cmdline_main` runs BEFORE `pytest_configure`, so by the time the fleet existed xdist had already decided on `-n 0`. Full suite ran sequentially in 13:45 instead of 2:37. Moved to `pytest_xdist_auto_num_workers` (earliest master-only hook xdist sees), documented in the conftest comment so future-me doesn't re-make the same mistake.

**Verified.** Cold-boot auto-spawn → 497 passed in 2:32, 0 stragglers. Reuse path (`--fleet-size=0` with a pre-booted fleet) — detected, reused, not torn down. `--fleet-size=2` — boots 2 emus in ~4s, runs, cleans up.

### BUG-037: `read_objects` silently drops up to 23 objects per sparse array

Last repro. Player at (44, 14), `view_map` reports 1 reachable + 4 unreachable — Mira, 10 trainers, 11 hidden rocks, a Pokéball all missing from **both** lists. Playtest notes flagged possible correlation with an earlier checkpoint revert; that was a red herring.

**Root cause.** `read_objects` had a `consecutive_empty >= 3 → break` heuristic dating from the DeSmuME port. The assumption ("slots are packed") is wrong for Gen 4's `LocalMapObjectManager`: it evicts distant NPCs out of their slots as the player walks around, so a save where the player has roamed can end up with slots 0/1 populated, 2/3/4 cleared, 5-27 still live. Scanner bailed at slot 5 and silently dropped every one. Happy-path saves we use in tests have the array packed, so nobody had noticed.

**Fix (`map_state.py`).** Read the whole 64-slot array as one `read_memory_block` (~19 KB, one round-trip) and parse headers locally with `struct.unpack_from`. No early-exit. Faster than the old per-slot loop even for dense maps (1 round-trip vs up to 20), and the sparse case just works. Test: `test_sparse_object_array_fully_scanned` on `bug_mira_and_east_interactibles_missing` asserts slots 5-15 + 27 all surface. 497 passed in 2:32.

### Session take-aways

- **Three of the six repros involved Wayward Cave + Mira.** Follower escorts stress overworld systems in ways solo play doesn't — narrow corridors with an NPC on the only east-west link, follower+player tag-partner doubles, dynamic slot eviction as the player wanders between the cave's four separated chambers. Worth pulling a few more escort saves from future sessions (Cheryl in Eterna Forest, Buck in Stark Mountain) to shake out the remaining edges.
- **Silent early-exit heuristics are the worst kind of bug.** `read_objects`'s `break` and `view_map`'s viewport-only 2D flood both shipped long ago and only showed up once a specific map geometry + specific player position exposed them. Added regression saves for both so they can't slip back.
- **`pkill`-to-commit loops are no longer a live-emu risk.** pytest owns the fleet now. `pytest_xdist_auto_num_workers` is also the only xdist hook that runs early enough AND master-only — future fleet-lifecycle work should start there, not in `pytest_configure`.

## Dev Session: N=8 fleet unlocked (2026-04-21 session 25)

Short follow-up to session 24. Woj restarted the container with `--shm-size=8g`, which resolves the SIGBUS ceiling diagnosed in MelonMCP#9 (closed upstream — low ROI for an emulator-side fix once the tmpfs sizing was understood).

### What changed
- Container now ships with `/dev/shm = 8.0G` (verified via `df -h /dev/shm`). Inside the container we still can't `mount -o remount` — `CapBnd=0x00000000a80425fb` lacks `CAP_SYS_ADMIN` bit 21 — so this is strictly a container-create flag.
- Reinstalled 8 ad-hoc apt packages lost in the restart: `gh ninja-build gdb strace fzf tmux ffmpeg sqlite3`. `gh` auth picked up automatically from preserved `~/.config/gh/hosts.yml` (volume-mounted, survives restart).
- `scripts/start_test_emulators.py` default: `--count 2` → `--count 8`. Help text reworded around the `--shm-size` container requirement instead of a manual `mount` runbook.
- CLAUDE.md test-suite section updated: baseline `~2:30 @ N=8`, container requirement callout, no more mount incantation.

### Ground-truth timings
- Single emulator (sequential): ~13:00
- N=2 fleet: 7:07 (1.9×)
- **N=8 fleet: 491 passed in 2:31 — 5.4× over single, 2.8× over N=2**

Sub-linear scaling from 2→8 is expected: savestate-load + per-worker fixture setup don't parallelize, and `--dist loadfile` means the slowest test file sets the tail. 2:31 is well below the threshold where running the full suite feels expensive — objective met.

### Not changed
- Launcher/conftest 2s and 1.5s staggers kept — defensive, harmless at any N, cheap insurance if tmpfs ever gets tight again.
- `flock`-based `load_state` serialization fallback (the user-space option from the memory note) left unimplemented. Not needed now; easy to add if a future container regresses without `--shm-size`.

## Dev Session: MCP tool trim + 2-way parallel test fleet (2026-04-21 session 24)

Housekeeping pass followed by test-infra work. Full suite green end-to-end (`60fb0ba` + `707106f`); runtime down from 13:27 → 7:07.

### MCP surface-area trim

`interact_with` and `map_name` removed as MCP tools. Both were superseded:

- `navigate_to(poi="obj:N")` dispatches `interact_with` internally for every dynamic-object POI in `view_map`'s `interactibles` list — same face+A flow. The internal `interact_with(emu, ...)` Python function stays; heal_party / shop / pc / move_services / navigation all import it as a shared primitive for coord-mode A-presses against static fixtures (PCs, bookshelves), which Claude never called directly anyway.
- `map_name` was redundant with nav position dicts that already carry `{map_id, name, display, code, room}`. Replaced by folding the same dict into `view_map`'s return under a new `location` key (was bare `map_id: int`). Header line now reads `Oreburgh Gate (D04) (x,y)…` instead of `Map 258 (x,y)…`.

Six macros deleted (`mash_a/b`, `walk_{up,down,left,right}`) — all early-session concepts superseded by `navigate_to` / `read_dialogue` auto-advance.

### CLAUDE.md rewrite (353 → 158 lines)

Stripped everything that duplicates tool docstrings — Battle Workflow, Fishing, Auto-Grind, Navigation-param details, Quick Reference workflows, Memory snapshot steps. Kept: save-state infrastructure, battery-save workflow, the `@renegade_tool` contributor pattern, navigation philosophy (don't trust screenshots), DS screen layout, bag/keyboard touch coordinates, game progress, test suite, genuine gotchas. Saved `feedback_no_mcp_docs_in_claudemd.md` so we stop falling back into this — per Woj, we've cleared it before and drifted.

Updated the "Next" stub to reflect session-23's objective (find Mira's lost item) rather than the old "fix map rendering first" that session-24's own work handled.

### Parallel test fleet

Goal: make `pytest tests/` feedback-loop-short enough that running it on every change feels free. Baseline was 13:27 sequential (491 tests).

**Infrastructure (commit `60fb0ba`):**
- `scripts/start_test_emulators.py` fans out N isolated melonDS instances, each with `.workers/worker_{i}/` (ROM copy + symlinks to shared `savestates/macros/data`, its own `.sav`) bound to `.melonds_test_bridge_{i}.sock`. 2s startup stagger between launches.
- `scripts/start_test_emulator.py` gained `--socket / --data-dir / --rom` args so it can be driven by the plural launcher.
- `tests/conftest.py` hooks `pytest_xdist_auto_num_workers` (the *correct* xdist entry point — `pytest_configure` and `pytest_load_initial_conftests` both fire too late once xdist has made its distributed-session decision) and returns the running socket count. With `-n auto --dist loadfile` set in `pytest.ini`, plain `pytest tests/` scales automatically. CLI `-n N` still wins.
- Each xdist worker (`gw0`…) picks its socket by index via `PYTEST_XDIST_WORKER`. 1.5s-per-worker staggered delay before the session fixture's first `load_state` (defensive against the bug below).

**N=2 ships as the default: 491 passed in 7:07 — 1.9× speedup.** N=3+ reliably SIGBUSes a worker during `savestate_load` within seconds.

### MelonMCP#9 — diagnosed

Filed an investigation request on MelonMCP; coordinated with another LLM instance on that repo who walked through the JIT fastmem code path. My original "concurrent `.mst` mmap contention" theory was **wrong**: savestates use plain `fread`, no mmap. Actual cause:

- melonDS's JIT fastmem allocates a PID-namespaced POSIX shm region (~17 MB per worker) in `/dev/shm`, then `mmap(MAP_SHARED|MAP_FIXED)` aliases it into an 8 GB reserved virtual window so JIT-emitted code can issue native loads/stores against guest pointers.
- On every `load_state`, `NDS::DoSavestate` calls `MapSharedWRAM` + `JIT.Reset`, which unmaps and remaps the fastmem aliases — a burst of page faults against the tmpfs-backed shm fd.
- When `/dev/shm` runs out of space, those faults deliver `SIGBUS(BUS_ADRERR)`. melonDS's own SIGBUS handler only recovers `SEGV_MAPERR/SEGV_ACCERR`, so tmpfs exhaustion falls through to `SIG_DFL` → process exits -7.
- Container's `/dev/shm` is Docker's 64 MB default (`df -h /dev/shm` confirms). N=2 fits (34 MB fastmem + 30 MB headroom); N=3+ oversubscribes → loses the fault lottery.

**Unblock for N=8 next time:** `sudo mount -o remount,size=8G /dev/shm` (+ `sudo sysctl -w vm.max_map_count=1048576` defensively), then `start_test_emulators.py --count 8`. Documented inline in CLAUDE.md's test-suite section and `start_test_emulators.py --help`; full playbook (including strace/coredump fallback diagnostics) lives in `memory/project_parallel_test_fleet.md`.

### Test count ground-truth

- Sequential baseline: **491 passed in 13:27** (CLAUDE.md claimed 369 across 31 files — stale; now corrected to 491 across 42 files).
- Parallel N=2: **491 passed in 7:07**.
- Sequential re-run after the MCP trim caught one stale assert in `test_detect_shift.py:55` (`result["map_id"]` → `result["location"]["map_id"]`), fixed; re-ran clean.

## Playtest Session 23 — BUG-033 filed (2026-04-20)

### BUG-033: `interact_with` stops one tile short when player is on the bicycle

**Repro save state.** `bug_interact_with_on_bike` (checkpoint `e7f7bee9`). Map 284 Wayward Cave (D21R0101) main branch, player at (41, 53) on the bicycle, Mira standing at (38, 42) — rescue-quest NPC, reachable from this entry (came in via Route 206 east secret entrance at (310, 607)).

**Exact tool call.** `interact_with(object_index=5)` where object 5 is Mira.

**Symptom.** Tool plans the correct path to the adjacent tile (destination `(39, 42)`, `face_direction="left"`, `path="up x11 -> left x2"`, 12 steps) but returns `stopped_early: true`, `blocked_at: {"x": 40, "y": 41, "step": 12}`, `blocked_on_final_step: true`. The player ends up one tile short of the destination (40, 41 instead of 39, 42) and no A-press / dialogue is ever triggered. Dismounting the bicycle and retrying worked (see next session note).

**Suspected root cause.** Bicycle movement is 8f/tile instead of 16f/tile; the final-step validator in the `interact_with` walker probably assumes walking speed and flags the last tile as still-moving when the faster bike frame arrives. Alternatively the face-direction enforcement fires before the final step completes on the bike.

**Fix direction.** Either (a) detect `on_bicycle` in `interact_with` and auto-dismount before driving the walk (same pattern `use_medicine` uses for menu safety), or (b) adjust the step-completion check in the walker to handle the 8f bike cadence. (a) is simpler and matches the "tools emulate player UI access" philosophy — you'd dismount to talk to someone in the game too.

## Dev Session: BUG-032 closed + housekeeping (2026-04-20 session 22)

### BUG-032 closed as no-repro-after-BUG-029

Re-ran the `bug_wayward_cave_pokeball_mislabeled` repro from (30, 23).  `read_objects` confirms all three targets (indices 1/2/3) are genuine Pokeballs: `gfx_id=87`, `trainer_type=0`, `movement_type=none`, distinct item-script IDs (7040/7041/7042).  `view_map` names them correctly; no mislabel.

The session-20 misdiagnosis came from the `navigate_to` failure diagram: `N` in that grid is drawn for *any* entry in `npc_set` (`pathfinding.py:188-213`) — NPCs, Strength boulders, **and Pokeballs**.  The `diagram_key` label says `N=NPC`, which primed the filer to read the Pokeball-N as a Kadabra NPC.

BUG-029's elevation-aware BFS now correctly marks all three Pokeballs as `unreachable` (different plateau level, reachable only via an alternate cave entrance).  The *observable* symptom — "I can't interact with a Pokeball shown on my map" — is expected behavior for unreachable items.

**Small follow-up noted** (not filed as a bug, captured here): the `diagram_key=\"N=NPC\"` wording is the trap that caused the misdiagnosis.  Next time we touch `pathfinding.py`, change it to `N=obstacle` or split renders per obstacle type.  Deferred — not worth its own session.

## Dev Session: BUG-029 + BUG-030 + BUG-031 cleared (2026-04-20 session 21)

Cleared three of the four navigation bugs filed in session 20.  BUG-032 deferred pending a framing conversation with Woj.  Full suite: **115/115 passing** across nav + map tools; no regressions.

### BUG-029: `view_map` marks under-bridge pickup as reachable

**Root cause.**  `view_map`'s BFS flood-fill (`_bfs_flood_fill` in `map_state.py`) never consumed BDHC elevation data on multi-chunk overworld maps — elevation was only loaded for single-chunk indoor maps (where `render_map` consumed it for `\/` glyph rendering).  On Cycling Road the player on the bridge ended up with a 2D-contiguous view of the under-bridge Pokeball because the bridge tile and the ground under it share the same `(x, y)` in the 2D grid.

**Fix (`renegade_mcp/pathfinding.py` + `map_state.py`).**

- `_flood_fill_level`: level-constrained flood-fill that mirrors `_bfs_pathfind_level`'s acceptance rules (ramp endpoints, steppable heights, multi-level tiles).  Returns `{(x, y): steps}` plus a `transitions` dict whose keys are either `ramp_index` (int) or `("ml", x, y, other_level)` — multi-level flat tiles act as implicit level-switch points.
- `_bfs_reachable_3d`: hierarchical flood-fill across levels via ramp + multi-level transitions.  Rewritten as an iterative work-queue with a shared `visited_level_starts` set.  The first cut was recursive and blew up to 77 s on Cycling Road's 5×5 chunk grid (≈1800 multi-level tiles × 15 levels = exponential branching).  The iterative form runs in ~5 ms with a 1.5 s wall-clock cap.
- `view_map`: on multi-chunk maps, build `_build_multi_chunk_terrain` + `_build_multi_chunk_elevation`, compute `player_level`, and run `_bfs_reachable_3d` instead of the 2D `_bfs_flood_fill`.  Translate reach set from mc-grid back to viewport-local for object reachability annotation.  Single-chunk maps still use the legacy 2D flood-fill (unchanged).

**Trade-off.**  The 3D flood-fill is more conservative than the 2D one on Cycling Road — Cyclist C at (306, 675), physically reachable by sliding south from the bridge, now appears in `unreachable_objects`.  The 3D elevation layout has a L3↔L4 gap (heights 48 and 59, diff 11 vs `STEPPABLE_HEIGHT=4`) that the BFS can't bridge without explicit ramp data, and the Cycling Road's ramps don't fill the gap cleanly.  Net: bridge/ground errors fixed, some legitimately-reachable-via-slide targets false-unreachable.  Callers still see these in `unreachable_objects` and can `navigate_to` them (the slide handler handles the actual traversal).

**Tests.**  `TestBug029ElevationReachability` (2 tests) — verifies the under-bridge Pokeball is unreachable and an on-bridge Cyclist is still reachable.  Uses a helper `_load_frozen` that skips the test helper's 60-frame settle, because the Cycling Road auto-slide drifts the player ~13 tiles south during that window.

### BUG-030: `navigate_to` routes through bridge instead of under it

**Root cause.**  Two stacked problems:
1. When 3D BFS returned `None` on a multi-chunk map, `navigate_to` silently fell back to 2D BFS, which ignores elevation and returns paths that step from under-bridge ground up onto the bridge (or vice versa).
2. `is_on_cycling_road`'s column-scan heuristic ("bridge body tile in player's Y-column → slide mode") fires for under-bridge players too, because the bridge body is literally above them in 2D space.  The subsequent dispatch into `_navigate_cycling_road` tried to slide, went south instead of west, and failed.

**Fix 1: 2D-fallback path validator (`_validate_path_elevation`).**  When 3D BFS fails on a 3D map, we still run 2D BFS (needed for HM-obstacle crossings — Surf, Rock Climb, Waterfall — that the current 3D BFS can't handle).  But before executing the path, simulate it step-by-step and reject if any step transitions between incompatible elevation layers.  Permissive where `_bfs_pathfind_level` is permissive: no-data tiles are accepted, multi-level tiles act as implicit level-switches, `STEPPABLE_HEIGHT`-close transitions are allowed.  HM-obstacle paths are exempt — Surf/Rock Climb/Waterfall are the legitimate ways to cross elevation layers.

Tracks `current_levels` as a set (not a single level) because while traversing ramps or multi-level tiles the player's "committed" level is ambiguous until a single-level tile forces the issue.

**Fix 2: elevation gate on `is_on_cycling_road` column scan (`map_state.py`).**  The column-scan now requires `read_player_height(emu) >= 40`.  Cycling Road bridge body is at height 48 (L3); under-bridge ground is at 16 (L1).  The threshold of 40 keeps bridge-adjacent scenarios firing while keeping under-bridge players out of cycling mode.  Skipped gracefully when height read fails.

**Also updated.**  `TestQaBug024SideWarpCluster` now fires from the 3D elevation path rather than the old 2D sanity-cap — same outcome (no player movement, warp hint, "No reasonable path" phrasing), different trigger point.  Dropped the `path_length > 50` assertion since we no longer build a 2D path to measure.

**Test coverage caveat.**  No live under-bridge save state exists.  Unit tests in `TestBug030PathElevationValidator` (3 tests) cover the validator directly with synthetic elevation dicts (bridge-crossing-from-ground rejected, level-jump rejected, ramp transition accepted).  Full end-to-end repro blocked on creating a save state at the filing's (302, 654) under-bridge position; flagged for future session.

### BUG-031: `navigate_to` bike-slope traversal fails going UP in Wayward Cave

**Investigation.**  Wayward Cave slope pair at (7, 26)/(7, 27) and (7, 37)/(7, 38) has the same tile behaviors (0xD9 top / 0xDA bottom) and same BDHC ramp (R2→0, dir=south, 32-unit height delta) as Route 207's slope at (306, 718)/(306, 719) (R9→4, dir=south, 32-unit height delta).  Calling `_traverse_bike_slope` from the identical pre-slope position pattern:

- **Route 207**: player moves from (306, 720) to (306, 714), tiles_moved=6.  Works.
- **Wayward Cave**: player stuck at (7, 28), tiles_moved=0.  Fails.

Same function, same inputs, different outcome.  Engine-side physics difference I couldn't pin down in this session — possibly related to the `R2-0 dir=north` ramp the Wayward Cave player starts on, or cave vs outdoor friction/acceleration tuning.  Worth revisiting with a ROM breakpoint on bike slope transitions if it starts blocking gameplay.

**Fix (`renegade_mcp/navigation.py::_execute_path`).**  When `_traverse_bike_slope` returns blocked (`tiles_moved == 0`), record `nav_info["blocked_reason"] = "bike_slope_traversal_failed"` and `nav_info["bike_slope_position"]`.  These merge into the `navigate_to` result via the existing `result.update(nav_info)` pattern, so callers see a structured error instead of the prior generic "Possible obstacle" note.  This is the filing's option (c) — detect and report — rather than (a) refuse ascent unconditionally (which would break Route 207).

**Tests.**  `TestBug031BikeSlopeTraversalFailure` (2 tests) — verifies the structured error is returned and the player doesn't end up wedged on a slope tile.  Route 207's slope tests (`TestBikeSlopeTraversal`, 6 tests) still pass — the new branch only fires on the blocked path.

### Session take-aways

- **BDHC elevation is multi-valued at (x, y).**  Bridge-over-ground tiles have plates at two heights for the same 2D footprint.  2D BFS flood-fill treats them as one tile; correct reachability needs a hierarchical level-indexed search.  The existing `_bfs_pathfind_level` had most of the pieces — extending it with multi-level transition tracking + a flood-fill wrapper was a couple hours of honest work.
- **"Recursive 3D search" is a trap on dense overworld maps.**  First cut of `_bfs_reachable_3d` was depth-capped but unbounded-per-branch; it ran 77 s on Cycling Road.  The iterative work-queue form with a shared `visited_level_starts` set ran in 5 ms.  Any future "hierarchical with branching" code should default to iterative unless the search tree is provably small.
- **Shared code paths hide physics-specific bugs.**  `_traverse_bike_slope` worked on every slope we'd hit until Wayward Cave.  Same behavior codes, same BDHC structure, different engine outcome.  Strategy here was "report the failure clearly, don't try to be clever" — the clear error unblocks the player to work around it manually rather than silently stalling.
- **Test scaffolding leaks.**  `do_load_state`'s 60-frame settle advances the Cycling Road auto-slide by ~13 tiles, invalidating any save state that relies on a bridge-bound starting position.  Added a local `_load_frozen` helper; worth promoting to a shared helper if more bridge tests land.

## Playtest Session 20 — BUG-029 + BUG-030 + BUG-031 + BUG-032 + FR-009 filed (2026-04-20)

Session cut short after a cascade of overlapping navigation bugs on Route 206 Cycling Road + Wayward Cave. The underlying theme: BFS reachability doesn't consistently respect elevation/bridge layering, and bike-slope traversal assumes descent-only. Bugs filed for the dev queue; playtest continuation blocked until fixes land.

### BUG-032: `view_map` classifies Mira's Kadabra (NPC) as a "Pokeball"

**Repro save state.** `bug_wayward_cave_pokeball_mislabeled` (checkpoint `bb0b5a81`). Map 285 Wayward Cave upper room. Player at (30, 23); target listed as `{"index": 2, "x": 31, "y": 16, "name": "Pokeball", "reachable": true, "steps": 19}` in `view_map.objects`.

**Exact tool call.** `interact_with(object_index=2)`.

**Symptom.** Returns `"No reachable tile adjacent to Pokeball at (31, 16). Fully surrounded by obstacles."` while `navigate_to(30, 16)` shows an `N` (NPC) adjacent to the target in its failure diagram. So the object is actually an NPC (almost certainly Mira's Kadabra, since her quest is active and this is her room), but `view_map` is naming it "Pokeball".

**Suspected root cause.** Name resolution is probably pulling from the wrong sprite/object-type table — the sprite ID may match a Pokeball graphic in one lookup but an NPC in another. Check how `view_map` classifies `objects` vs NPCs: anything with a dialogue/trainer script should be named by its NPC entry, not its sprite table.

**Fix direction.** Cross-check the sprite-label lookup with the object's behavior type. If it has a dialogue script or NPC-movement type, label it by NPC class (e.g., "Kadabra" / "Mira's Pokemon" / "NPC") rather than "Pokeball". Same lookup likely affects other story NPCs that happen to share sprite IDs with item-graphic objects.

### BUG-031: `navigate_to` bike-slope traversal fails going UP in Wayward Cave

### BUG-031: `navigate_to` bike-slope traversal fails going UP in Wayward Cave

**Repro save state.** `bug_wayward_cave_bike_slope_up` (checkpoint `9f48a95a`). Map 285 Wayward Cave second room. Player at (7, 32) on the bicycle; bike slope pair at (7, 37) top / (7, 38) bottom is north of player (south of them is the bottom room, north is upper room continuation).

**Exact tool call.** `navigate_to(x=7, y=18)`.

**Symptom.** Path announced as `"up x14"`, but only 6 steps executed, stopped at (7, 28). The bike-slope traversal logic in `navigate_to` is tuned for *downhill* (fast gear toggle + continuous UP hold going south); here the player needs to ascend the slope going NORTH, which requires a different input pattern the auto-handler doesn't emit. No `obstacles_cleared` entry despite the obvious slope obstacle.

**Contrast with BUG-025 (closed).** That one was about entering the bike-slope sequence without a bicycle. This one is about ascending a slope with the bicycle — previously all Renegade bike slopes we encountered were descent-only (Route 207+ overworld), so the ascent code path was never exercised.

**Fix direction.** `navigate_to` should detect when the slope-traversal direction is north of the player (ascent) and either: (a) refuse cleanly with a "bike slopes are one-way — descend only" note, or (b) implement an ascent strategy if the engine supports it. Given slopes are typically one-way in Platinum, (a) is likely correct — and the natural fallback is to find an alternate path around the slope. Verify the BFS isn't picking the slope path when a detour exists.

**Workaround (this session).** `navigate d3` + 90-frame `advance_frames([up])` to see whether manual hold-UP climbs the slope (testing in progress).

### BUG-030: `navigate_to` routes through bridge instead of under it

### FR-009: `use_item("Repel")` should report "already active"

**Symptom.** Calling `use_item("Repel")` when a Repel is already active returns:

```
success: false
kind: bag_message
formatted: "Item use may have failed. Repel quantity: 6 → 6. The menu flow may have gone wrong."
```

The "menu flow may have gone wrong" wording strongly implies a UI bug in the tool — but the actual cause is in-game: the game rejects the second Repel with an "Another Repel is already in use" prompt, so the item count correctly stays flat. No bug, just a confusing error message.

**Fix direction.** When `use_item` detects the "Repel already active" rejection prompt (or any "can't use now" dialogue), return a clear `reason: "repel_already_active"` plus a message like `"Repel already active — no new Repel consumed."` Same treatment for Escape Rope in non-escapable areas and Bicycle in walk-only zones, if those have analogous rejections.



### BUG-030: `navigate_to` routes through bridge instead of under it

**Repro.** Route 206 middle lower path. Player at (302, 654) (dirt path between the two bridge halves, underneath the bridge-merge section). Hiker NPC visible at (292, 643) on the west lower path, `reachable: true, steps: 20` per `view_map`. `navigate_to(292, 643)` triggers `cycling_road: true` mode (the bridge-slope auto-slide), slides south, doesn't reach the west side.

**Suspected root cause.** Same family as BUG-029 — BFS is not constraining to elevation level, so it treats bridge `n` tiles as walkable for the player standing underneath. When the chosen path crosses bridge tiles, the Cycling Road auto-slide kicks in because the code thinks the player is on the bridge.

**Fix direction.** Hierarchical BFS should gate on elevation level for lower-path start positions: the player under the bridge cannot traverse bridge tiles. Probably the same constraint that fixes BUG-029 (restrict reachability to player's current elevation) will fix this too.

**Workaround.** Use bare `navigate` with manual `up`/`left` strings to crawl out of the gap; don't call `navigate_to` from under-bridge positions until elevation gating lands.

### BUG-029: `view_map` marks under-bridge pickup as reachable

**Repro save state.** `bug_view_map_under_bridge_pokeball` (checkpoint `72c8ecc7`). Map 350 Route 206 Cycling Road. Player at (301, 662) on the bridge; Pokeball at (302, 652) is visible in the ASCII map through the bridge gap but sits on ground level below.

**Symptom.** `view_map` reports the pickup in `objects` with `reachable: true, steps: 18`.  `navigate_to(302, 652)` rides 4 tiles north then stops at (301, 662) with `reached_target: false, note: "Possible obstacle (trainer NPC, wall, or end of bridge)"`.  The pickup is physically under the bridge and can only be collected from the lower elevation path (enter Cycling Road from a different side).

**Suspected root cause.** `view_map`'s BFS reachability check ignores elevation — the bridge and the ground underneath share the same (x, y) in the 2D grid, so anything directly below a `n` tile looks connected.  BDHC elevation data is already loaded (render uses it for the `n` / `\` / `/` glyphs), just not consumed by the reachability pass.

**Fix direction.** When evaluating reachability on a 3D map, constrain the BFS to the player's current elevation level (same rule `navigate_to` uses for hierarchical path planning).  Unreachable-due-to-elevation items should move to `unreachable_objects` with a clear reason.

**Scope.** Only affects maps where pickups/NPCs sit on a different elevation from the player (Cycling Road, Mt. Coronet bridges, gyms with platforms).  Doesn't block gameplay — the misroute just wastes a few bike tiles.

## Dev Session: BUG-027 + BUG-028 fixed (2026-04-20 session 19c)

Cleared both bugs filed at the end of session 19b.  Straightforward — each had a precise repro save state and a file:line pointer, so the work was about picking the right fix wedge rather than hunting for the root cause.

### BUG-028: Rock Climb follow-up nav rejected by length guard

**Root cause.** BUG-024's sanity cap `max(manhattan * 5, manhattan + 30)` assumed long detours only happen around side-warp clusters.  It didn't account for the player being stranded on a top-of-wall Rock Climb ledge whose only exit is back down the same wall.  Live repro: `hm_test_rock_climb_veilstone` → climb to (691, 614) → navigate to (688, 612) (5 Manhattan) → BFS finds a legitimate 71-step path back down the climb and around, but the guard refused it.

Empirical check with the raw BFS primitives: `clean_path = None`, `obs_path = 71 tiles` crossing two `rock_climb` entries at (691, 615–616).  The obstacle path is the *only* way off the ledge.

**Fix (`renegade_mcp/navigation.py`).** Skip the length guard when the chosen path is `obs_path` and any entry in `obs_crossed` is in `AUTO_NAVIGATE_TYPES` (rock_climb / water / waterfall).  Single condition, no threshold knobs to tune.  BUG-024's cycling-road-end scenario has no HM tiles on its path, so that regression test still trips the guard correctly.

### BUG-027: `seek_encounter` blocked on bike en route to grass

**Root cause — two stacked problems.**

1. **Walk-to-pacing-tile phase ignored bike physics.**  The naive `press + check` loop at `fishing.py:428-443` pressed `down` one tile at a time.  At (306, 718) the bike hit a slope and auto-slid two tiles per press — the loop's step counter desynced, overshot the intended turn point, and eventually stalled against a wall.
2. **Pacing on bike is fundamentally unreliable.**  With a 4-frame per-tile hold, alternating directions leaves residual momentum that carries the player one tile in the *old* direction even while pressing the *new* one.  Verified live: at (303, 721) pressing `up` moved the player to (303, 722) — physically impossible for a correct input pipeline.  Same test with the bicycle dismounted (16-frame hold): clean alternation between (303, 720) and (303, 721) forever.

**Fix (`renegade_mcp/fishing.py::seek_encounter`).**
- Replace the walk-to-pacing loop with a `_navigate_to_impl(global_x, global_y)` call.  Handles bike slopes, facing turns, HM obstacles, repaths, and mid-walk encounters (including the `Repel's effect wore off...` dialogue path — which `_post_nav_check` already classifies as `encounter=dialogue`).
- Dismount the bicycle before the pacing loop if `CYCLING_GEAR_ADDR != 0`.  Re-read `_get_move_hold(emu)` after dismount so the hold frames switch from 4 → 16.
- Add one facing-turn retry to the pacing loop itself: if a press doesn't change position, retry once before declaring blocked.  Cheap insurance and also helps the already-in-grass repro mentioned in the bug filing (`(295, 720)` — where the first press was a facing turn that logged as blocked immediately).

**Regression test.** `TestQaBug027SeekEncounterBlocked::test_reaches_grass_through_bike_slope` in `test_fishing.py` — loads `bug_seek_encounter_blocked_route207_bike`, calls `seek_encounter`, asserts `result["result"] != "blocked"`.  Allows either `encounter` (Repel wore off mid-walk, wild Ponyta, wild Larvitar) or `max_steps` (200 steps without a hit) as valid outcomes.  Run live three times: two wild encounters + one Repel dialogue.

### Verification
- `test_hm_obstacles.py` + `test_cycling_road.py` (59 tests) — green, including `test_navigate_continues_after_rock_climb` and the full BUG-024 regression set.
- `test_fishing.py` + `test_auto_grind_v2.py` (12 tests) — green, including the new BUG-027 test.
- Full suite: **465 passed in 13:34** against the standalone test emulator.  Zero regressions.

### Session take-aways
- **When a sanity cap misfires, the distinguishing signal is usually already computed nearby.**  BUG-028's fix is a one-line exception using `obs_crossed`, which was already available in scope.  No need for a new traversal or a tunable threshold.
- **Bike pacing is a genre-local landmine.**  Pokemon's input model distinguishes short (turn) and long (move) presses, and 4-frame bike holds sit right at the boundary.  Any future "alternating direction on bike" code should either dismount first or use a longer hold.  Straight-line nav on bike is fine because `_execute_path` doesn't change direction every step.
- **`_navigate_to_impl` is the escape hatch for movement correctness.**  The walk-to-pacing-tile phase didn't need to understand slopes or HMs — it just needed to delegate.  Worth keeping this pattern in mind for any future tool that walks the player somewhere specific.

## Dev Session: FR-007 + FR-008 + two new bugs filed (2026-04-20 session 19b)

Closed two feature requests from the QA triage backlog and filed two new bugs discovered along the way.

### FR-007: view_map splits objects by BFS reachability

**Motivation.** During the Galactic HQ Eterna playthrough, `view_map` showed Jupiter in the ASCII grid as a visible object, but she was behind interior walls from the player's current section. `interact_with` failed with "No reachable tile adjacent." The grid itself is hard to disambiguate visually, so the reader had no cheap way to tell Jupiter was actually walled off.

We debated three render-time options — fog of war, dim glyphs, suffix marker — and settled on **"don't touch the grid, fix the object listing."** The listing is what a caller actually reads before picking a target.

**Implementation (`renegade_mcp/map_state.py::view_map`).** The existing `obj_info` list (with its per-entry `reachable: bool`) is split into two top-level keys: `objects` (BFS-reachable only, sorted by step count) and `unreachable_objects` (walled off, sorted by Manhattan distance). When any unreachable objects exist, the `map` string gets a trailing `Unreachable: N object(s) walled off — see \`unreachable_objects\`` pointer so the reader notices without scanning both lists.

Downstream test fixtures (`test_qa_bug020`, `test_qa_bug021`) were using `result["objects"]` to look up trainers by id or position — not caring whether the trainer was reachable. They're updated to search `objects + unreachable_objects` so the lookup remains reachability-agnostic.

**Tests.** 4 new in `TestFr007ReachableSplit` (`test_map_tools.py`): every entry in `objects` has reachable=True; `unreachable_objects` is always present; Galactic HQ fixture has disjoint reachable/unreachable index sets when both are non-empty; when unreachable are present, the map string contains the `Unreachable:` pointer.

### FR-008: switch_to uses battle UI slot, rejects fainted

**Motivation.** During the Jupiter fight, `battle_turn(switch_to=4)` stalled on the party summary screen. `switch_to=0` was rejected with "your active battler (Machop)" even though Machop was party slot 3. The original filing assumed the docstring was right — `switch_to` uses "party-slot numbering matching read_party order" — and the fix would be "reject fainted Pokemon." Woj pushed back: **in battle, only battle slots should be used.**

**Empirical test settled it.** Loaded `test_trainer_battle_action` (Luxio active, Machop at party slot 1). Opened POKEMON menu, screenshotted: Luxio top-left, Machop top-right — party order. Switched Machop in, advanced to the next action prompt, opened POKEMON menu again. **Grid reshuffled:** Machop top-left (the vacated active slot), Luxio top-right. `read_party` in-battle already exposes `battle_ui_slot` and `battle_role` per Pokemon — Luxio became `slot=0, battle_ui_slot=1, role=bench`, Machop became `slot=1, battle_ui_slot=0, role=active`. Party memory ordering is stable; the UI grid tracks battle-slot ordering with the active battler always at UI 0.

So the existing `PARTY_TOUCH_XY[switch_to]` tap was battle-slot-correct the whole time — the docstring was just lying. The original Jupiter failure: `switch_to=4` tapped UI tile 4, which post-switch wasn't Monferno, which is why the summary screen stalled.

**Fix.**
1. Docstring in `server.py` and CLAUDE.md rewritten to say **battle UI slot (1-5)**, with UI 0 rejected (always active), and pointers to `read_party.battle_ui_slot` for the mapping.
2. New helper `_fainted_switch_error` in `renegade_mcp/turn.py`: reverse-maps `switch_to` → party member via `battle_ui_slot`, returns a species-named error string if HP==0.
3. The helper is called after range-validation in all three switch-accepting branches (ACTION, FAINT_SWITCH/SWITCH_PROMPT, FAINT_FORCED).

The existing `_switch_to_zero_error` message was rewritten in the same spirit — no more "party-slot numbering" language.

**Tests.** 4 new in `TestFr008SwitchBattleUiSlot` (`test_battle_turn.py`): zero-error phrasing now mentions "battle UI slot" and "read_party"; healthy bench passes the helper; fainted bench (monkey-patched party) returns species-named error; end-to-end `battle_turn(switch_to=1)` surfaces the error when the target is fainted. Existing `TestFr005SwitchToZeroErrorMessage` tests still pass — the new message satisfies the "party" substring and "1-5" hint by virtue of mentioning `read_party` and the 1-5 range.

**Regression run.** Full suite: 463 passed, 1 failed. The single failure (`test_navigate_continues_after_rock_climb`) is pre-existing and unrelated — BUG-024's path-length guard (from commit `b962d02`) misfires on tight post-Rock-Climb nav where a 5-tile Manhattan target takes 71 steps to reach. `git diff` confirms my edits don't touch navigation. Filed as **BUG-028**.

### Also filed this session

**BUG-027:** `seek_encounter` returns "blocked" on bike when grass requires a multi-step navigation path. Repro save: `bug_seek_encounter_blocked_route207_bike`. Discovered while setting up the FR-008 experiment — `seek_encounter` from Route 207 (306, 714) on bike returned `{"result":"blocked","steps_taken":1}` without attempting to walk to the grass patch 15+ steps away. Also reproduced from a position already standing in tall grass (295, 720). Suspect: `_find_pacing_pair`'s BFS returns paths the non-navigate_to stepper can't execute. Switched to `test_trainer_battle_action` to unblock the FR-008 work.

**BUG-028:** BUG-024 path-length guard too aggressive for Rock Climb follow-up nav. Suggested fix is to loosen the ratio when `obstacles_cleared` contains an HM-traversal entry, or raise the absolute step floor from 30 to 60.

### Session take-aways

- **Empirical experiments beat reasoning about docstrings.** The FR-008 work stalled on "is the docstring right?" for one back-and-forth; once we scripted the actual test (open menu, screenshot, switch, screenshot) the answer was immediate.
- **The object-listing split was the ergonomic win for FR-007, not a grid change.** "Should we dim unreachable floor?" was a red herring — callers read the listing, not the grid.
- **Test-emulator decoupling paid off.** Ran 463 tests in 13 minutes against the standalone test emulator while the live one stayed on the battle-state for experimentation.

## Dev Session: QA BUG-026 — use_battle_item throws Poké Ball instead of healing (2026-04-20 session 19)

Fixed the session-18-filed BUG-026. The tool reliably threw the last-used Poké Ball at the opposing trainer on any `battle_turn(use_item="Super Potion", party_slot=N)` call — silently consuming the turn, lying in the `formatted` field, and exposing the active Pokemon to a free enemy attack.

**Root cause — three stacked timing/coordinate bugs.** Reproduced on `bug_battle_turn_use_item_throws_pokeball` and traced step-by-step by tapping the sequence manually and screenshotting between each tap:

1. **First BAG tap at (45, 170) was dropped.** The "What will Luxray do?" prompt text is still printing when `use_battle_item` runs, and the game ignores touch input during the print. The tool's 60-frame wait after the tap wasn't long enough to notice the tap failed.
2. **Pocket tap at (64, 44) landed on FIGHT.** With the bag still not open, (64, 44) is inside the action-screen's FIGHT button. Move select opened.
3. **The PREV_PAGE × 5 spam at (20, 172) cascaded into a Poké Ball throw.** Tap 1 hit CANCEL on move select (back to action); tap 2 hit the BAG button (x=20, y=172 is inside BAG's rect); tap 3 was spent on the bag-open transition; **tap 4 landed on the bag menu's "Last Used Item" button** `{152, 191, 0, 207}` — which from session 17's Larvitar catch had `lastUsedItem = Poké Ball`; tap 5 confirmed USE and the ball flew.

The decomp reference in `ref/pokeplatinum/src/battle_sub_menus/battle_bag.c` confirmed the coordinates — our `POCKET_TAP_XY` and `_BIT_TO_POCKET` tables both match the ROM's `sMenuTouchRects` and `sBattlePocketIndexes`. The bug wasn't in the static mapping, it was entirely in the timing assumption that the bag would be on-screen by frame 60.

**Fix (`renegade_mcp/use_battle_item.py`).**

- `PROMPT_SETTLE_WAIT = 60` before the first BAG tap — lets "What will X do?" finish printing so the tap registers.
- `SCREEN_WAIT = 150` for the BAG→menu and menu→pocket transitions (the fades take ~90-110 frames). Stops the "pocket" tap from landing on FIGHT and the page-reset taps from hitting LAST_USED_ITEM.
- Bench-heal post-party-tap B-press: the "X's HP was restored by N points" confirmation on a bench target waits for user input and — per a live memory scan — never writes its text into the region `_scan_for_new_text` reads. Without a B press, `_wait_for_action_prompt` trips on the stale pre-turn "What will X do?" WAIT_FOR_ACTION marker still in memory and returns immediately. Active heals don't need this because their narration overwrites the stale marker at the same address before the tracker runs (verified on `battle_item_debug_damaged` — at `_wait_for_action_prompt` entry the buffer holds `"Used the Potion!"` at `0x2301bc0`, not the stale action prompt).

**Tests.** 7 new in `test_qa_bug026_use_item_throws_pokeball.py`:
- Log doesn't contain "blocked the Ball" / "thief" rejection lines (core invariant).
- Formatted field doesn't contradict the log.
- Final state is WAIT_FOR_ACTION.
- Enemy Fake Out appears (proves the turn actually progressed past the heal).
- Last log entry is the fresh action prompt.
- Bench role metadata reports `role="bench"`, `target="Monferno"`, `party_slot=3`.
- `battle_turn(use_item=...)` wrapper is also safe.

Broader sweep: 169 tests passed across BUG-022, use_battle_item, and all battle-related suites — no regressions. The active-heal path (BUG-022's `battle_item_debug_damaged` state) still captures `"Used the Potion!"` narration correctly, which was briefly broken by an over-eager unconditional B-press before the fix was gated on `not is_active_target`.

### Also noted in this fix

- **Address `0x2301bc0` is the game's primary battle text slot.** It's where action prompts, move narration, item-use narration, and faint messages all land in turn. If you see a stale-text-in-buffer problem, check this address first.
- **Bench heals need a different dismissal path than active heals.** Not just a timing difference — a *what-text-the-tracker-can-see* difference. Keep this in mind if we extend `use_battle_item` to other bench-target items (Full Restore, Revive, etc.).

## Dev Session: BUG-025 + BUG-026 filed during playtest (2026-04-20 session 18)

Two playtest-surfaced bugs documented with repro save states and file pointers. No code changes this session — both are open and awaiting fix.

### BUG-025: navigate_to silently stalls on bike-slope ascent when not on bicycle

**Symptom.** From Route 207 (299, 730) on foot, called `navigate_to(305, 715)` to cross the bike-slope pair at (306, 718–719). Tool ran 15 repaths and terminated at (306, 720) — one tile south of the slope bottom — with no error, no warning, and no mention of the bicycle requirement. Path returned: `up x10 -> right x5 -> up -> right -> up x4 -> right -> up x5 -> left`, 58 steps.

**Verified root cause.** The slope traversal handler requires the bicycle. After `use_item("Bicycle")` + retrying the same `navigate_to(305, 715)` call from (306, 725), it succeeded in one pass: `up x10 -> left`, 13 steps, `obstacles_cleared: [{"type":"bike_slope","tiles":2,"x":306,"y":719}]`, 1 repath. The 5-tile runway south wasn't the issue — bicycle mount state was.

**Repro save.** `bug_bike_slope_north_climb_fail` — Route 207 (299, 730) facing right, on foot, full 6-Pokemon healed team. Reload and call `navigate_to(305, 715)` → stalls. `use_item("Bicycle")` then retry → succeeds.

**Fix options (preferred order).**
1. **Auto-mount bicycle** when BFS path crosses a bike-slope tile and the Bicycle is in key items — mirrors the existing auto-Surf / auto-Waterfall / auto-Rock-Climb flows. Consistent UX, no caller cognitive load.
2. **Refuse early** with a clear error if a slope tile is on the path and `on_bicycle == False`. Strictly a bugfix; worse ergonomics than (1) but safer on surprises.
3. At minimum surface `obstacle_blocked: "bike_slope_requires_bicycle"` in the result so callers can detect the failure mode instead of parsing a stopped-early coordinate.

**File pointer.** `renegade_mcp/navigation/` — same module family as the existing slope-descent handler. The south→north branch is the broken/missing one. Also check BFS passability: if the slope tile is marked passable on foot, the tool plans a path it cannot execute.

### BUG-026: battle_turn(use_item="Super Potion") throws a Poké Ball at the enemy trainer

**Symptom.** Mid-battle vs Youngster Austin's Lombre, Luxray active at 19/109 burned. Called `battle_turn(use_item="Super Potion", party_slot=3)` intending to heal Monferno (slot 3). Tool log:
```
"The Trainer blocked the Ball!"
"Don't be a thief!"
"The foe's Lombre used Fake Out!"
"Luxray is hurt by its burn!"
```
The game actually attempted a **Poké Ball throw** at the opposing trainer — rejected with the canonical "thief" message — then the turn proceeded with Lombre attacking. No Super Potion was used. Pre-call Monferno 24/78; post-call still 24/78 (verified via `read_party`).

**Worse: the tool lied in the formatted field.** It returned `"Used Super Potion on Monferno (bench — HP unverifiable)"` — confidently asserting a heal that never happened, while the `log` field showed the Poké Ball throw. Callers relying on the formatted summary would never know.

**Repro save.** `bug_battle_turn_use_item_throws_pokeball` — mid-battle vs Youngster Austin's Lombre Lv25, Luxray Lv33 active at 38/109 burned (pre-Fake Out), full 6-mon party with Monferno 24/78 in party slot 3. Reload and call `battle_turn(use_item="Super Potion", party_slot=3)` → Poké Ball thrown.

**Hypotheses.**
- Pocket tab index off-by-one after an earlier in-battle bag action (e.g., a previous turn touched Items/Medicine/Poké Balls in a specific order that offset the cursor).
- Item-position calculation using stale quantities. Noted during this same session: `use_item("Repel")` out-of-battle reported `old_qty:14 → 13` right after buying 5 Repels when we should have had 9. A possible parallel qty-cache bug in the same code family.
- Unconditional "first usable ball-like item" fallback when the item-name lookup misses.

**File pointers.** `renegade_mcp/use_battle_item.py` (in-battle item dispatch) + `renegade_mcp/turn.py` where `battle_turn` delegates to it. Also audit the bag pocket-tab routing — Items, Medicine, and Poké Balls are on different tabs and the navigation must pick the right one based on `fieldUseFunc` / ItemData lookups, not on bag-scroll order.

**Priority: high.** Silently consumes the turn, hits the player with opponent moves, and lies about what happened. Any autonomous play that uses in-battle Super Potion is currently unsafe.

### Also noted (not its own bug entry)

- **Text glyph leak `[01B9]`** in Bullet Seed multi-hit narration: `"Hit 3 time[01B9]s/!"`. Same family as the resolved BUG-005/008/009 (hex codes slipping past `text_encoding.CHAR_MAP`). Bundle into the next glyph-leak cleanup pass — check all multi-hit-counter strings in ROM.

## Dev Session: QA BUG-022 — battle_turn(use_item=...) missing `log` field (2026-04-19 session 17)

QA surfaced BUG-022: `battle_turn(use_item=...)` returned a response with
no `log` field, making the turn opaque — the enemy's reciprocal action
executed invisibly and only the pre/post HP delta (often confusingly
"backwards" when the enemy's damage exceeded the heal) hinted that the
enemy had acted at all. Classic observability gap: every return path
was missing `log`, not just one edge case.

Copied `session16_map75_pre_jupiter_battle.mst` from the QA project into
`/workspace/RenegadePlatinumPlaytest/savestates/qa_session16_map75_pre_jupiter_battle.mst`
(ROM MD5 matches, so save states transfer cleanly). Walked the extra
6 tiles to Jupiter, engaged her, saved a focused repro state
`bug022_jupiter_battle_pre_super_potion` at her action prompt with
Monferno 75/99 HP and Super Potion x9 in the Medicine pocket. Pre-fix
call returned `old_hp=75 new_hp=51 final_state=WAIT_FOR_ACTION` with no
log. Post-fix call exposes the full turn: *Used the Super Potion!* →
*Monferno's HP was restored by 24 points.* → *The foe's Golbat used
Wing Attack!* → *It's super effective!* → *What will Monferno do?*

**Root cause.** `use_battle_item` called `_wait_for_action_prompt`
(which itself logs every distinct text transition while polling through
item animation + enemy turn + action-prompt return), but only read
`prompt["prompt_type"]`. `prompt["log"]` — the complete turn narration
— was thrown away. Every one of the six return paths in the function
(blackout, active-heal HP-changed, active-heal HP-unchanged, bench
HP-unverifiable, X-item success, X-item uncertain) omitted the `log`
field.

**Fix.** `renegade_mcp/use_battle_item.py`:
- Initialize `turn_log: list[dict] = []` just before the Step 7 branch
  so even the escape-item (Poke Doll, battleUseFunc=3) path — which
  doesn't call `_wait_for_action_prompt` — still returns a well-typed
  empty list.
- Capture `turn_log = prompt.get("log", []) or []` immediately after the
  `_wait_for_action_prompt` call on the healing / X-item branch.
- Thread `"log": turn_log` through every return dict. `turn.py::battle_turn`'s
  item path (lines 1056-1064) already returns the inner dict unchanged
  and then appends `battle_state`, so the new `log` field propagates
  automatically — no wrapper changes needed.

8 regression tests in `tests/test_qa_bug022_battle_turn_use_item_log.py`:
- 4 on `battle_item_debug_damaged` (Luxio vs Natu, Potion) — log key is
  present and a list, entries have correct shape (`text` + `stop`,
  valid stop values), last entry's stop is WAIT_FOR_ACTION when the
  prompt closes the turn, log contains "Potion" narration.
- 2 on the same state via the `battle_turn(use_item=...)` wrapper
  exposing the log and coexisting with `battle_state`.
- 2 on `bug022_jupiter_battle_pre_super_potion` — the exact QA repro,
  asserting "Golbat" appears in the log text blob and that both the
  heal narration ("restored") and enemy-action narration ("used") are
  captured so downstream callers can reconstruct the HP arc.

Existing `test_use_battle_item.py` (25 tests) still passes — no
regressions. Full BUG-022 file runs in ~12 s; the combined
use_battle_item surface is ~32 s.

## Dev Session: QA BUG-019 / BUG-020 / BUG-021 — double-battle log dedupe + trainer-class/flavor-NPC metadata (2026-04-19 session 15)

Triaged the three new QA reports from session 15. All three are log /
view-metadata cosmetic issues — no gameplay impact — but all three bite
downstream parsers or completionist planners. Importing the QA save
states as `qa_session15_galactic_bldg_pre_stairs` and
`qa_session15_route211_west_entry` (battery save backed up read-only as
`saves/qa_session15.sav`).

### BUG-019: Double-battle log duplicates multi-line narration
**Root cause.** Two independent sources of duplication:
1. `BattleTracker.poll` unconditionally advanced `prev_text` even for
   AUTO_ADVANCE entries it was filtering out (BUG-011 orphan names,
   BUG-016 level-summary artifacts). A filtered entry between two real
   repeats of the same text defeated the consecutive-same dedupe.
2. **Bigger source** — when `_tracker.poll` returns (WAIT_FOR_ACTION /
   TIMEOUT / NO_TEXT) with narration markers still live in the battle
   text region, `turn.py`'s doubles / recovery path calls
   `_wait_for_action_prompt` and extends `result["log"]` with whatever
   the second scanner picks up. Those stale markers get re-logged
   verbatim.

Confirmed by instrumenting `BattleTracker.poll` to log every
`logged_multiline.add` — live repro produced exactly one "Aurora Beam!"
in the tracker's log, but a second entry appeared after the extend.
Removing the instrumentation after the diagnosis.

**Fix.**
- `renegade_mcp/battle_tracker.py::BattleTracker.poll` — gate the
  `prev_text = text` assignment on `not is_filtered`, and track
  multi-line AUTO_ADVANCE entries in a per-poll `logged_multiline` set.
  Single-line emphasis ("A critical hit!", "It's super effective!") is
  deliberately not deduped — those legitimately repeat in doubles.
- `renegade_mcp/turn.py::_merge_log_dedupe_multiline` — new helper
  that appends an extra log list to an existing one while skipping
  exact multi-line AUTO_ADVANCE duplicates of entries already present.
  Non-AUTO_ADVANCE stops (WAIT_FOR_ACTION / WAIT_FOR_INPUT) always pass
  through so partner re-prompts aren't suppressed. Applied at every
  cross-scanner extend site: `_poll_after_action` NO_TEXT recovery,
  doubles partner-prompt recovery, `_execute_action`'s prompt+poll
  merge, and the level-up recovery's trailing prepend.

7 regression tests in `tests/test_qa_bug019_double_battle_log_dedupe.py`
(6 unit tests for `_merge_log_dedupe_multiline` semantics — dup drop,
legit single-line repeats, different-mon / different-exp values pass
through, empty extras, prompt-stop preservation — plus 1 meta-test
asserting the BUG-011/BUG-016 filter invariants stay stable, because
the tracker's prev_text guard depends on them).

### BUG-020: `view_map` reported sprite class, not trainer class
**Root cause.** `map_state.py` built `object.name` from
`GFX_NAMES[graphics_id]` (the overworld sprite class). The
authoritative in-battle trainer class lives in `trdata.narc`: each
trainer record's byte 1 is a class index into ROM message file 619.
Route 211 W's Alexandra has `graphics_id: OBJ_EVENT_GFX_ACE_TRAINER_F`
(sprite "Ace Trainer F") but `script: TRAINER_BIRD_KEEPER_ALEXANDRA`
→ trainer 76 → class 30 = "Bird Keeper". Vanilla Platinum inherits the
same re-skin, so this isn't Renegade-specific.

**Fix.**
- `data/trainer_classes.json` — pre-built from the 1066 trdata.narc
  records × 105 class names in ROM file 619. Ships as a plain
  `{trainer_id: {class_id, class_name}}` map.
- `renegade_mcp/trainer.py::lookup_trainer_class` — cached singleton
  loader returning the real class for a trainer id (or None for
  unknown ids, so the caller can fall back gracefully).
- `renegade_mcp/map_state.py` — when the trainer id resolves and the
  sprite name differs from the trainer class, override `name` with
  the class, preserve the original via `sprite_name`, and surface
  `trainer_class` explicitly. Matching sprite+class pairs skip the
  extra fields to avoid noise.

7 regression tests in `tests/test_qa_bug020_view_map_trainer_class.py`
(5 lookup-table units + 2 live view_map integration — Alexandra
sprite/class override and Ninja Boy matching-pair negative case).

### BUG-021: `view_map` flagged a flavor-only NPC as defeated trainer
**Root cause.** `TRAINER_HIKER_LOUIS` at (377, 529) has a real 3-mon
party in trdata.narc (Graveler / Onix / Golem @ Lv19) and a
`TRAINER_TYPE_NORMAL` zone_event header with `script:
TRAINER_HIKER_LOUIS` → trainer id 326. In Renegade Platinum the field
script was rewritten to skip the battle and emit a flavor line; a
story-side script pre-sets trainer 326's defeat flag (bit 1686 in
VarsFlags) so the NPC's LOS trigger silently no-ops. Verified cold:
bit 1686 = 0 in `twinleaf_outside_house_post_mom`,
bit 1686 = 1 in `qa_session15_route211_west_entry`, with no Hiker
battle between those save states. So `is_trainer_defeated` was
technically correct — the game really does treat him as defeated — but
`trainer=true defeated=true` on an unexplored map misled the QA
operator and would confuse any completionist tool.

**Fix.**
- `data/rp_flavor_trainers.json` — curated
  `{map_id: [trainer_ids]}` allowlist. Starts narrow with just
  `{"365": [326]}`; header comment documents how to extend.
- `renegade_mcp/trainer.py::is_flavor_trainer` — cached
  `(map_id, trainer_id)` membership check.
- `renegade_mcp/map_state.py` — when a resolved trainer id hits the
  allowlist, suppress `trainer` / `trainer_id` / `defeated` and set
  `flavor_npc: true` instead. Non-flavor trainers get the full
  metadata (including BUG-020's new `trainer_class` / `sprite_name`
  fields) unchanged.

6 regression tests in `tests/test_qa_bug021_flavor_trainer_suppression.py`
(4 allowlist semantic units + 2 live view_map integration — Louis
flavor suppression + Alexandra metadata unchanged). Additional flavor
NPCs discovered in future QA runs go straight into the JSON file, no
code change needed.

### Verification
- `tests/test_qa_bug019_*` — 7 passed.
- `tests/test_qa_bug020_*` — 7 passed.
- `tests/test_qa_bug021_*` — 6 passed.
- `tests/test_battle_turn.py`, `test_battle_tracker.py`,
  `test_battle_move_learn.py`, `test_battle_event_text.py` — 51 passed
  (no regressions).
- `tests/test_navigation.py`, `test_qa_bug017_*`, `test_qa_bug018_*`
  — 35 passed (no regressions).

## Dev Session: QA BUG-017 / BUG-018 — Eterna Gym 3D pathfinding + MOVE_LEARN mis-attribution (2026-04-19 session 14)

### BUG-017: `navigate_to` / `interact_with` fail to route around a blocked clock arm
**Root cause.** Eterna Gym's BDHC defines an L0 strip (height = -2) at
row 20 that separates the upper clock area (L1) from the south-warp
perimeter (L1). In-game the 2-unit dip is just a grass step — the engine
crosses it without a ramp animation — but `_bfs_pathfind_level`'s
`_tile_on_level` only accepted tiles whose `level_map[tile]` listed the
current level exactly, or ramp tiles whose endpoints matched. L0 has no
ramp connector, so L1 BFS treated it as impassable and the only route
between clock and warp was the south-arm L2 ramp at col 11. When that
arm's fountain was active, the dynamic-block repath loop ran against
the same bad tile 15× and gave up at `warp_failed, repaths: 15`. The
"teleport to (15, 13)" the QA report described was an artifact of the
path-string summary, not a real teleport — the player just never left
the east arm.

**Fix.**
- `renegade_mcp/nav_constants.py` — new constant
  `STEPPABLE_HEIGHT = 4`. Accepts the L0↔L1 small-step dip (diff 2)
  while keeping L1↔L2 (diff 16) ramp-only. Scoped at 4 so a future map
  with stacked half-tile heights doesn't accidentally collapse into a
  single level group.
- `renegade_mcp/pathfinding.py` — `_bfs_pathfind_level._tile_on_level`
  now treats a neighbour as same-level if its defined elevation is
  within `STEPPABLE_HEIGHT` of the BFS's current level height. Same
  check is applied to ramp tiles so a small-step ramp doesn't get
  rejected because neither endpoint equals the current level.
- `renegade_mcp/interaction.py` — `interact_with` was 2D-only; loaded
  BDHC (single-chunk or multi-chunk), cached `player_level`, and wired
  `_bfs_pathfind_3d` into the `_path_to(adj_x, adj_y)` helper. Falls
  back to 2D when elevation data isn't available. `repath_ctx` also
  gets `elevation` + `emu` so `_try_repath` has the same info.

**Tests (5 new in `tests/test_qa_bug017_clock_navigation.py`).**
- Save-state sanity (map 67, player at (15, 13)).
- `STEPPABLE_HEIGHT` bounds: covers L0/L1 diff, rejects L1/L2 diff.
- L1 BFS from (4, 13) to (11, 27) crosses row 20 (explicit y-trace).
- `navigate_to(11, 27)` from bug state exits to Eterna City (map 65).
- `interact_with(object_index=4)` on the east Breeder succeeds
  (adjacent reached, no stopped_early-without-dialogue).

`tests/test_3d_nav_fallback.py::test_clock_hand_dynamic_blocks` updated
to reflect the cleaner behaviour (3D BFS now plans the correct outer
path directly instead of relying on the dynamic-block safety net).

### BUG-018: Mid-battle `MOVE_LEARN` mis-attributes the learning mon
**Root cause.** `_get_move_learn_info` matched "lowest set bit >=
`tmpData[GET_EXP_PARTY_SLOT]`" in the `levelUpMons` bitmask. Two decomp
facts make that wrong in multi-level-up battles:
- `levelUpMons` is cumulative (`battle_script.c:10090`:
  `levelUpMons |= FlagIndex(slot)`) with no paired clear. Every mon
  that leveled up in the current battle has its bit set for the rest
  of the battle, even after it finishes processing or faints.
- `tmpData[GET_EXP_PARTY_SLOT]` is the **scan start index** for the
  for-loop in `BattleScript_GetExpTask`, only advanced at
  `SEQ_GET_EXP_CHECK_DONE` (line 10415, `slot + 1`) *after* a slot's
  move-learns are handled. During a mid-processing prompt the index
  still points at or below the current slot.

So in the QA Gardenia repro, Monferno leveled 30 → 31 early and
fainted; Mothim leveled 28 → 29 later and hit the Poison Powder
prompt; `levelUpMons = 0b00000101`, `tmpData[6] = 0`; the old heuristic
returned slot 0 (Monferno) instead of slot 2 (Mothim).

**Fix** (`renegade_mcp/turn.py::_get_move_learn_info`). For each slot
with a bit set, check the species' level-up learnset
(`renegade_mcp/data.py::level_up_moves`) for `(current_level, move_id)`.
Exactly one match → that's the learning mon. Monferno Lv31's learnset
contains Slack Off, not Poison Powder, so it's filtered out; Mothim
Lv29 matches Poison Powder and wins. If multiple matches exist
(unlikely — would need two party members of the same species and level
learning the same move), prefer the first at-or-above the scan index.
No matches → fall back to the old scan heuristic (handles species with
gaps in ROM learnset data).

**Tests (8 new in
`tests/test_qa_bug018_move_learn_identification.py`).** Memory and
`read_party` are monkeypatched — replaying the live Gardenia scenario
would be fragile and isn't necessary to exercise the disambiguation
logic.
- Canonical Monferno/Mothim repro — both bits set, correct slot 2.
- Single level-up still resolves correctly (no false positives on the
  learnset check when only one bit is set but species doesn't actually
  learn the move).
- No-learnset-match fallback uses the scan index.
- Null taskData pointer returns None without touching party.
- Zero `levelUpMons` mask returns None.
- Out-of-range move id returns None.
- Stale `slot_lower = 0` no longer shadows the real learning mon.
- Decomp audit: `levelUpMons` still has exactly one `|=` write and no
  clears in `battle_script.c` — a grep-style regression guard against
  a future decomp upgrade silently changing the semantics.

### Imported save states
- `savestates/bug_navigate_eterna_gym_clock_tile_stuck.mst` (copied
  from QA project — primary BUG-017 repro).
- `savestates/session14_pre_gardenia_healed_stocked.mst` (copied from
  QA; pre-Gardenia state — canonical BUG-018 scenario needs a full
  Gardenia replay to trigger, so not directly used by the mocked
  BUG-018 tests but kept alongside for a future live-repro test).
- `savestates/session13_end_gym_healed_post_lass.mst` (copied from QA;
  cleaner alternate BUG-017 repro after Lass + east Breeder defeats).

---

## Dev Session: QA BUG-014 / BUG-015 / BUG-016 — battle-UI slot indirection + level-up summary artifacts (2026-04-19 session 12)

### Summary
Three related issues surfaced by QA session 12 on Route 216 vs Ace
Trainer Blake. All three revolve around the Gen 4 battle engine's
`partyOrder[4][6]` indirection table — the engine does *not* physically
reorder party-block entries when you switch, it updates this UI→persistent
slot map at `0x022C5B60`.

### BUG-014: `use_battle_item(party_slot=N)` misroutes after a switch
**Root cause.** `use_battle_item` tapped `PARTY_TOUCH_XY[party_slot]`
directly, treating the caller's `party_slot` as a UI position. After
switching Vaporeon (persistent slot 1) in, partyOrder became `[1, 0, …]`;
tapping UI pos 1 hit the now-benched Monferno instead. Pre-switch the
identity map hid the bug.

**Fix** (`renegade_mcp/use_battle_item.py`).
- `_read_party_order(emu)` + `_persistent_to_ui_pos(slot, ui_order)` —
  translate persistent slot → current UI position before tapping.
- `is_active_target` flips on UI pos 0 (singles active); drives HP
  verification path + the `role` label in the response.
- Active-battler HP verified via BattleMon (live). Bench HP is marked
  "unverifiable" — the party block isn't updated in real time during
  battle (see BUG-015), so a before/after diff is unreliable.
- Response carries `role: "active"|"bench"` so callers don't have to
  infer target state from the formatted string.

### BUG-015: `read_party` opaque to in-battle UI order
**Root cause.** Same partyOrder indirection — `read_party` reads the
persistent party block and has no signal that UI position ≠ persistent
slot during battle. Active battler HP is also stale because mid-battle
HP lives in the BattleMon struct, not the party block.

**Fix** (`renegade_mcp/party.py`).
- `_read_battle_context(emu)` snapshots partyOrder + live BattleMon when
  battleEndFlag=0.
- Each party entry gains `battle_ui_slot` (UI grid position) and
  `battle_role` (`"active"` / `"bench"`).
- Active battler's `hp` / `max_hp` / `status_conditions` are overridden
  from the BattleMon. Persistent `slot` is unchanged — stable callers
  keep working.
- `format_party` surfaces `[UI N · role]` tags + in-battle header.

### BUG-016: Level-up summary UI labels leak into battle log
**Root cause.** During a mid-battle level-up the party panel writes its
summary labels to the text scan region alongside the narration:
- ROM file 368 index 944: `{NAME}{COLOR_ON}@{COLOR_OFF}\nLv. {LEVEL}`
  — the "@" is a literal sprite glyph; the decoder strips the color
  VAR blocks and leaves `"Mothim@\nLv. 23"`.
- ROM file 368 index 947: a bare stat-name VAR that drives the
  "stat rose by N!" graphic — only the stat-name token leaks through
  (`"Sp. Def"`, `"Attack"`, etc.).
The real "grew to Lv. N!" and "<stat> rose!" lines are separate scan
entries (templates 3 and 750–755 respectively) and render cleanly.

**Fix** (`renegade_mcp/battle_tracker.py`).
- New `_is_level_summary_artifact()` filter — regex for `<name>[@*]?\nLv. <num>`
  capped at 10 chars (Gen 4 nickname max) to avoid swallowing narration
  like `"Monferno grew to\nLv. 30!"` + a whitelist of standalone stat
  labels. Wired into both `BattleTracker.poll` and
  `turn._wait_for_action_prompt` alongside BUG-011's orphan-name filter.

### Tests (17 new)
- `TestQaBug014UseItemPartySlotAfterSwitch` in
  `tests/test_use_battle_item.py` — 3 unit (identity map, post-switch
  swap, missing-slot guard) + 2 integration (post-switch Super Potion
  heals active Vaporeon; identity-map slot 0 still targets active as
  before) + persistent→UI translation edge case.
- `TestQaBug015ReadPartyBattleEnrichment` in `tests/test_party_tools.py`
  — 4 tests: overworld has no battle fields, UI slot/role tagging after
  a switch, active HP matches BattleMon (not party block), formatted
  output shows `[UI N · role]` tags.
- `test_bug016_*` under `TestQaBug011OrphanNameFilter` in
  `tests/test_battle_tracker.py` — 6 tests: `@`/`*`/no-marker label
  patterns filtered, every standalone stat-name filtered, real
  level-up narration not filtered, empty text edge case.

### Imported save states
- `saves/qa_session12.sav` (copied from `/workspace/RenegadePlatinumQA/
  RenegadePlatinum.sav`, `chmod 444`).
- `savestates/qa_session12_route216_entry.mst` — Route 216 (375,403),
  Blake reachable at object_index=1, Monferno asleep slot 0, Vaporeon
  slot 1, Mothim slot 2 (Toxic, 30/67), Shinx slot 3.
- `savestates/qa_session12_route216_post_blake.mst` — post-fight state
  for future BUG-016 re-triggering if a live level-up integration test
  is ever added.

---

## Dev Session: QA BUG-013 — short-player-name decoy (2026-04-19)

### Summary
BUG-012's fix made `name_length × 10` dominate delta scoring, which worked
when the decoy was a *longer* name (8-char species nicknames outscoring a
7-char player name). QA's playthrough uses the 3-char player name "WOJ" —
and a ROM text buffer in main RAM contains "Destiny Knot", whose 4-char
substring `"Knot"` sat at delta=-0x100 and scored 42 vs the real "WOJ"
at delta=-0x20 (score 33). The secondary canaries at the decoy were
wildly wrong (party_count=36,299,880, money=$36,302,676 — the reported
"always $36,302,676" fingerprint) but the old scoring treated garbage
canaries as *missed bonuses*, not disqualifications.

### Fix
`renegade_mcp/addresses.py` — new `_save_block_structural_ok(emu, cand)`
gate: `party_count ∈ [0, 6]` AND `money ≤ 999,999` (Platinum hard
invariants). Applied in two places:
- `_detect_save_block_delta` — skip any delta failing the gate during
  the scan, so the "Knot" decoy never enters the candidate set.
- `revalidate` — require the cached delta to still pass the gate, not
  just the name check. A decoy whose "name" read still matches gets
  re-detected instead of staying stuck (addresses the mid-session
  desync where the cache wouldn't self-heal).

### Tests (4 new in `TestQaBug013ShortPlayerNameDecoy`)
- `test_detect_shift_rejects_knot_decoy_mid_session` — live repro state
  `bug_013_mid_session_desync_post_gym_guide` resolves to -0x20 not -0x100
- `test_detect_shift_rejects_knot_decoy_cold_start` — the cold-start
  regression capture also resolves correctly
- `test_save_block_structural_ok_gates_decoy` — unit-level gate: -0x100
  rejected (garbage pc/money), -0x20 accepted
- `test_revalidate_rejects_decoy_with_matching_name` — install -0x100
  manually, confirm revalidate re-detects to -0x20

Full detect_shift suite (18 tests) green. Pre-starter, BUG-012 name-length
cap, cross-save-switch, and group-delta tests unaffected.

---

## Dev Session: Test-suite reorganization (2026-04-17 session 11)

### Summary
Split the two catch-all test files (`test_battle.py`, `test_qa_bugfixes.py`)
into per-subsystem files so the filename tells you what the test exercises.
"QA tests" isn't a useful category — every test was a QA test at some
point. Test count unchanged at 369; 71 tests sampled across every moved
and renamed file pass.

### Motivation
`test_qa_bugfixes.py` (1235 lines, 16 classes) accumulated regression
tests for 2026-04-15 and -16 triage sessions. `test_battle.py` (527 lines)
mixed core turn mechanics with throw_ball, read_dialogue, trainer flows,
and move-learn. Neither name helped answer "where do I put this new
test?" or "which file covers feature X?"

### Battle split (5 files, all `test_battle_*` prefix)
- `test_battle_turn.py` — core `battle_turn`: move/switch/run, doubles,
  self-targeting, accuracy warnings, plus BUG-004 (Taunt false MOVE_BLOCKED),
  QA BUG-002 (wild FAINT_SWITCH classification), QA BUG-003 (evolution
  "What?" detection), QA BUG-004 (doubles species-count), FR-005
  (switch_to=0 error message).
- `test_battle_trainer.py` — multi-Pokemon trainer flows (SWITCH_PROMPT,
  post-battle dialogue).
- `test_battle_move_learn.py` — move-learn prompt (skip, learn, Prompt 2
  Fire Fang regression).
- `test_battle_catch.py` — `throw_ball` + QA BUG-001 (`_format_log`
  [FFFE] handling + `_recover_from_catch` formatted rebuild).
- `test_battle_tracker.py` — `battle_tracker` internals: QA BUG-011
  orphan-name filter.

### New standalone files
- `test_dialogue.py` — `read_dialogue`/`advance_dialogue` (moved from
  `test_battle.py`) + BUG-002 (cutscene `CTX_WAITING`).
- `test_text_encoding.py` — QA BUG-005 (VAR-block + glyph 0x25BD/0x01A8),
  QA BUG-008 (alt-font '&'/'%' + pocket icon sprites 0x0113–0x011A),
  QA BUG-009 ([01E0][01E1] "Pokémon" ligature).

### Appended to existing per-subsystem files
- `test_map_tools.py` ← BUG-008 (`map_id_to_name.json` rebuild, 3 tests).
- `test_shop_tools.py` ← BUG-003 (Premier Ball bonus poisons next buy, 2
  tests) + QA BUG-006 (buy_item exit-to-overworld, 1 test).
- `test_use_battle_item.py` ← BUG-009 (target reporting hardcoded to
  slot 0, 4 tests).
- `test_party_tools.py` ← QA BUG-010 (`_resolve_party_extension`
  field-level composition, 3 tests).

### Renamed
- `test_event_text.py` → `test_battle_event_text.py` for consistency
  with the `test_battle_*` category prefix (it's post-battle event
  animation text dismissal).

### Deleted
- `test_battle.py` and `test_qa_bugfixes.py` — all contents redistributed.

### Verification
- `pytest --collect-only`: 369 tests across 31 files (previously 369
  across 26 files). No tests lost.
- Ran 71 tests across every moved/renamed file against the standalone
  test emulator (`scripts/start_test_emulator.py` on `.melonds_test_bridge.sock`):
  26/26 pure-unit + integration in `test_battle_catch`/`test_battle_tracker`/
  `test_text_encoding`; 28/28 QA/BUG classes across the five other
  moved files; 17/17 sampled tests from battle splits + shop regressions +
  renamed event-text file. All green.

### File count bump
- `CLAUDE.md` Test Suite header: "369 tests across 26 files" → "369 tests
  across 31 files".

## Dev Session: QA run-3 closeout — BUG-009/010/011 (2026-04-17 session 10)

### Summary
Closed the remaining three open bugs from the qa-run-3 backlog (BUG-009,
BUG-010, BUG-011), re-verified BUG-007 stays deferred (cosmetic, root
cause already documented), and wrote 13 new regression tests across 3
test classes. Full suite stays green.

### BUG-009: `[01E0][01E1]` "Pokémon" ligature leak
- **Observation** (session 9): trainer-class strings in the Cheryl battle
  rendered as `[01E0][01E1] Trainer Cheryl` — two raw hex codes leaking
  into `battle_turn` log + `post_battle_dialogue`.
- **Root cause:** ROM file 619 (trainer classes) stores "Pokémon Trainer",
  "Pokémon Breeder", and "Pokémon Ranger" as `[0x01E0][0x01E1]` + space +
  suffix. The 2-byte pair renders the stylized "Pokémon" sprite glyph
  in-game. Our decoder had no mapping.
- **Fix:** added two `CHAR_MAP` entries in `renegade_mcp/text_encoding.py`
  — `0x01E0 → "Pokémon"` and `0x01E1 → ""`. The pair decodes as one word
  and the ROM's trailing space reads naturally as "Pokémon Trainer".
- **Tests:** `TestQaBug009PokemonLigatureLeak` (4) — 3 unit cases
  (ligature + Breeder + full Cheryl send-in line) + 1 integration
  driving two turns of the Cheryl battle from
  `eterna_forest_entered_south` and asserting no bracketed leaks plus a
  "Pokémon Trainer" spot-check.

### BUG-010: `read_party` garbled `max_hp=37988` for PC-round-tripped slot
- **Observation** (session 9): on fresh load of
  `eterna_forest_entered_south`, Shinx slot 3 returned `max_hp=37988`.
  Other slots and other fields were sane; the in-game party menu showed
  Shinx at 21/21.
- **Root cause:** the party extension (bytes 136-236 of the slot struct)
  captures **a mixed encryption state** in this specific save: bytes 0-7
  (status/level/cur_hp) and bytes 8-9 (max_hp) end up in opposite
  states. Applying PRNG decryption yields valid level/cur_hp but garbage
  max_hp; leaving raw yields garbage level/cur_hp but valid max_hp.
  Neither source passes the old `_ext_sane` full-record check, so the
  fallback returned primary's garbage max_hp. This happens after PC
  deposit/withdraw because the PC code path resets the extension's
  per-byte encryption state, and a save captured before the first battle
  transition catches it mid-recompute.
- **Fix:** `party._resolve_party_extension` now composes field-by-field
  when neither source is fully sane. Per-field predicates (`_level_sane`,
  `_hp_sane`, `_max_hp_sane`) select the correct half; `status` follows
  the level byte under the assumption that bytes 0-7 are a single
  encrypted unit. The happy path (both sources consistent) is unchanged.
- **Tests:** `TestQaBug010MaxHpMixedStateRecovery` (3) — 1 unit case
  that synthesizes the live state (plaintext tail + encrypted header),
  1 integration verifying Shinx reads `HP 21/21` on fresh load,
  1 sanity case asserting Monferno/Vaporeon/Burmy are unaffected.

### BUG-011: orphan species / move / trainer-class log entries
- **Observation** (session 9): battle logs included bare single-word
  entries like `"Slowpoke"`, `"Makuhita"`, `"Water Pulse"`, `"Bug
  Catcher"` sandwiched between normal macro lines. Occurred in
  `battle_turn` log output and in the `battle_log` returned by
  `seek_encounter` / `interact_with`.
- **Root cause:** the battle text poll loop picks the memory slot with
  the highest decoded-char count each ~15-frame tick. Between a macro
  clearing and the next macro populating, a short name-cache buffer
  briefly becomes the top match and gets emitted as its own
  `AUTO_ADVANCE` log entry. Real narration always carries either a
  newline (multi-line box) or terminal punctuation (`.` `!` `?`); bare
  name caches carry neither.
- **Fix:** `battle_tracker._is_orphan_name_text()` filter — drop
  `AUTO_ADVANCE` entries with no newline, no terminal punctuation
  (`.!?,;:…`), and ≤24 chars. Applied in both `BattleTracker.poll`
  (in-battle log) and `turn._wait_for_action_prompt` (battle-intro log
  used by encounter detection). The helper is shared between the two
  paths; `WAIT_FOR_ACTION` / `WAIT_FOR_INPUT` entries are never filtered
  so real action prompts and ability-announcement boxes keep their
  behavior.
- **Tests:** `TestQaBug011OrphanNameFilter` (6) — 5 unit cases
  (species/class/move orphans + empty edge + guard that real lines
  aren't false-positive-filtered) + 1 integration replaying the
  Slowpoke wild encounter from `forest_exit_route205_north_post_cheryl`.

### QA BUG-007: still deferred
Investigated one more time. Fix options remain (a) per-var-id
substitution layer that reads game state to fill unresolved tokens, and
(b) read text buffer at a later pipeline stage after the game's
substitution pass. (a) is risky — many code paths rely on stripping
`[VAR]…` working correctly; (b) needs a text-buffer survey not yet done.
Cosmetic-only (user sees `"Obtained the !"` instead of
`"Obtained the TM76!"`), so leaving deferred for a future session.

### Touch points
- `renegade_mcp/text_encoding.py` — 2 CHAR_MAP entries.
- `renegade_mcp/battle_tracker.py` — `_is_orphan_name_text` helper +
  filter call in `BattleTracker.poll`.
- `renegade_mcp/turn.py` — import `_is_orphan_name_text`, filter call
  in `_wait_for_action_prompt`.
- `renegade_mcp/party.py` — per-field sanity predicates + mixed-state
  composition path in `_resolve_party_extension`.
- `tests/test_qa_bugfixes.py` — 3 new test classes (13 tests).

### Save states introduced / imported
- `bug009_cheryl_post_drifloon_ko` — checkpoint right after Drifloon KO
  in Cheryl battle, for ad-hoc live verification of the ligature fix.
- `bug011_cheryl_post_wailmer_ko` — switch-prompt state after Wailmer KO
  with Vaporeon's level-up consumed.
- Imported from QA: `bug008_cheryl_trainer_01e0_01e1_codes`,
  `bug_shinx_max_hp_garbled_read_party`, `eterna_forest_entered_south`,
  `forest_exit_route205_north_post_cheryl`,
  `eterna_forest_cheryl_doubles_mid_battle_buneary_paras`.

### Test stats
- New tests: 13 (4 + 3 + 6).
- `test_qa_bugfixes.py` file total: 70 tests, all green.
- Full suite at session end: **369 tests, all green** (13m38s).

---

## Dev Session: FR-004 — Unified use_item dispatcher (2026-04-17c)

### Summary
Closed FR-004 by generalizing `use_item` into the single entry point for every
field-usable bag item. Deleted the `use_field_item`, `use_key_item`, and
`teach_tm` MCP tool wrappers. New signature is
`use_item(item_name, party_slot=-1, forget_move=-1)` and dispatches on the
item's `fieldUseFunc`.

### Scope decisions (agreed with Woj up front)
- **Supported shapes:** no-target (Repel / flutes / Escape Rope / Honey /
  Bicycle / the BAG_MESSAGE key items), party-target (Medicine, healing
  Berries, evolution stones, Gracidea), party + optional forget-move
  (TMs & HMs — delegates to `teach_tm`, which stays as an internal module).
- **Rejected shapes** with specific guidance: fishing rods → point to
  `seek_encounter(rod=...)`; mail → point to `give_item`; modal-UI key
  items (Town Map, Journal, Pal Pad, Poffin Case, Poké Radar, Explorer
  Kit, Vs. Seeker, Vs. Recorder, Sprayduck, Mulch, Azure Flute) →
  unsupported, drive manually. Context-gated preconditions (facing Honey
  Tree, cave-only for Escape Rope, outdoors-only for Bicycle) logged to
  backlog as deferred.
- **Evolution-stone compat pre-check** skipped for this pass. The game's
  own "had no effect" path is detected after USE (no wasted stone either
  way). ROM-extracted evo table for preemptive rejection can be added
  later if wasted stones become a real concern.

### Implementation details
- `renegade_mcp/use_item.py` rewritten (696 lines): primitives → bag
  lookup → `use_item` dispatcher → per-flow handlers
  (`_flow_no_target_message`, `_flow_escape_rope`, `_flow_bicycle`,
  `_flow_party_medicine`, `_flow_evo_stone`) → internal `activate_key_item`
  helper kept for `fishing.py`.
- Bag lookup scans every pocket (pocket name comes from the bag, not the
  func) so items like Coin Case / Fashion Case / Seal Case in Key Items
  route correctly despite sharing `FUNC_BAG_MESSAGE` with Items-pocket
  flutes/repels.
- TM/HM fallback: if the bag search misses, check whether the name matches
  a move taught by a TM/HM in the bag; delegate to `teach_tm` so callers
  can pass `"Rock Smash"` instead of `"HM06"`.
- Evo-stone post-USE: poll up to ~720 frames for "is evolving" / "What?"
  markers using the existing `_is_evolution_text_on_screen` helper. If
  detected, dismiss with B and wait passively for "evolved into …" (up to
  ~40s); otherwise treat as incompatible and close the menus.
- `navigation.py` bike auto-mount switched from the deleted `use_key_item`
  to `use_item(emu, "Bicycle")`.

### Tests
- `tests/test_item_tools.py` restructured: `TestUseFieldItem` →
  `TestUseItemNoTarget`; new `TestUseItemRejections` (fishing-rod pointer,
  modal-UI rejection, missing party_slot); `TestTeachTm` →
  `TestUseItemTmHm` routed through the unified dispatcher + new
  missing-party-slot rejection case.
- `tests/test_bicycle.py` and `tests/test_cycling_road.py` updated to call
  `use_item(emu, "Bicycle")`.
- Full regression: 67 passed across
  `test_item_tools / test_bicycle / test_fishing / test_cycling_road` (~2 min).

## Dev Session: FR-003 + FR-005 (2026-04-17b)

### Summary
Two QoL feature requests from the 2026-04-17 QA triage closed: FR-005 (low) improves the `battle_turn(switch_to=0)` rejection message, and FR-003 (medium) folds `use_battle_item` into `battle_turn` as a fifth action type. FR-004 (generalize `use_item`) deferred pending a decomp investigation of non-medicine item types.

### FR-005 — Active battler species in switch_to=0 error
- **Before:** `"switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."`
- **After:** `"switch_to=0 is your active battler (Monferno). switch_to uses party-slot numbering (0-5, matching read_party order), not battle-slot numbering. Use 1-5 to swap in a different party Pokemon."`
- Implementation: new `_switch_to_zero_error(emu)` helper in `turn.py` reads battle slot 0's species from `BATTLE_BASE` and formats the message. Replaces the string literal in all three validation branches (ACTION / SWITCH_PROMPT / FAINT_FORCED).
- `server.py` docstring for `switch_to` param also updated to flag the party-slot vs battle-slot distinction.

### FR-003 — `battle_turn(use_item=...)` delegation
- Added `use_item: str = ""` and `party_slot: int = -1` parameters to both `turn.battle_turn` and the MCP wrapper. When `use_item` is set at the ACTION prompt, the turn delegates to `use_battle_item(emu, use_item, party_slot, target)` and early-returns with `battle_state` appended — skipping the enrichment passes (MOVE_LEARN / SWITCH_PROMPT / blackout) which don't apply to item use. Preserves `use_battle_item`'s own formatted output (e.g. `"Used Potion on Monferno. HP: 10→25."`).
- Validation: `use_item` is mutex with `move_index` / `switch_to` / `run`; rejected outside the ACTION prompt with a state-named error.
- Standalone `use_battle_item` tool kept for back-compat — docstring updated to note it's the same code path as `battle_turn(use_item=...)`.

### Tests Added (10 tests)
- `tests/test_qa_bugfixes.py::TestFr005SwitchToZeroErrorMessage` (3): species-name presence, party-slot clarifying language, direct helper unit test.
- `tests/test_use_battle_item.py::TestFr003BattleTurnUseItemDelegation` (7): heal-via-battle_turn, battle_state appended, healing-requires-party_slot propagated, three mutex rejections (move_index / switch_to / run), Poke Ball → throw_ball rejection still fires through the delegation.

Existing tests pass unchanged:
- `TestBug009BattleItemTarget` (4) — direct `use_battle_item` path still green.
- `TestUseBattleItemHealing` / `TestUseBattleItemValidation` / `TestBattleBagPockets` (9) — back-compat direct calls.
- Full `test_battle.py` (50+) and `test_auto_grind_v2.py` (5) — no regressions in upstream callers.

### Files Changed
- `renegade_mcp/turn.py` — `_switch_to_zero_error` helper; `battle_turn` signature + docstring + ACTION/SWITCH_PROMPT/FAINT_FORCED validation + use_item delegation path.
- `renegade_mcp/server.py` — MCP `battle_turn` wrapper signature, docstring, and pass-through to impl; `use_battle_item` docstring noting the merger.
- `tests/test_qa_bugfixes.py` — `TestFr005SwitchToZeroErrorMessage` (3).
- `tests/test_use_battle_item.py` — `TestFr003BattleTurnUseItemDelegation` (7).

### Next Session Plan
FR-004 (generalize `use_item` to Items pocket / dedicated `evolve_with_stone`) awaits a decomp pass on item type handling — e.g. how evolution stones (`field_use=0` stone class), Escape Rope (`field_use=0` escape class), and Fluffy Tail (overworld-only) branch in the `ItemData.fieldUseFunc` dispatch. Once we know the dispatch shape, the generalize-vs-dedicated decision gets easier.

## Dev Session: QA BUG-008 hex-code leaks + BUG-007 root-cause (2026-04-17)

### Summary
Two new bugs landed in the 2026-04-17 QA run — BUG-008 (hex format codes still leaking after the BUG-005 fix) and BUG-007 (post-battle reward dialogue tokens elide to empty strings). BUG-008 **fixed** (10 CHAR_MAP entries, 5 tests, live-verified). BUG-007 **root-caused but deferred** — the fix is risky and the bug is cosmetic. Three new feature requests (FR-003/004/005) triaged to the backlog untouched — scoping conversation with Woj next session.

### QA triage
- **BUG-001..006** — all already marked FIXED (round-1 resolved 2026-04-15, round-2 resolved 2026-04-16/17). No action needed.
- **BUG-008** — new, actionable. Same decoder family as BUG-005 but a different set of unmapped glyph codes was still reaching callers.
- **BUG-007** — new, root cause is deeper than BUG-008. Deferred.
- **FR-003/004/005** — new QoL suggestions, to be scoped next session.

### QA BUG-008 — Hex-code leak sibling of BUG-005
- **Symptom:** Every item-pickup cutscene and some dialogue cutscenes leaked raw bracket tokens like `"in the [0114]KEY ITEMS Pocket."`, `"90[01D2] of all Pokémon..."`, `"TMs [01C2] HMs"`.
- **Root cause:** Five distinct unmapped u16 codes hitting the `decode_char` bracket fallback. Traced via `search_rom_messages` against Renegade Platinum's message archives:
  - `0x01C2` and `0x01D2` are alt-font `&` and `%` glyphs used inline in normal dialogue (ROM file 395 "TMs & HMs", file 23 Dawn's "90% of all Pokémon").
  - `0x0113`..`0x011A` are the 8 pocket sprite icons embedded in pocket-name strings (ROM file 396 pocket label table: ITEMS / KEY ITEMS / TMs & HMs / MAIL / MEDICINE / BERRIES / POKé BALLS / BATTLE ITEMS).
- **Fix:** 10 entries added to `CHAR_MAP` in `renegade_mcp/text_encoding.py`. Alt-font glyphs map to ASCII variants; pocket-icon sprites map to empty string (no ASCII equivalent, and in-game they render as small sprites). The decoder pipeline itself is unchanged — the new entries just cover previously unmapped values so they bypass the `[XXXX]` fallback.
- **Live verification:** Replayed the Galactic-grunts double battle from `bug008_pre_galactic_battle_win`; `post_battle_dialogue` now returns `"90% of all Pokémon are somehow tied to evolution!"` and `"WOJ put the Fashion Case in the KEY ITEMS Pocket."` with zero bracketed leaks.

### QA BUG-007 — Root-cause identified, fix deferred
- **Symptom:** Roark's post-battle reward ceremony surfaces text with tokens silently elided to empty strings — `"Obtained the !"` / `" put the \nin the  Pocket."` / `"That  contains\nthe move Stealth Rock."`. Distinct from BUG-005/008 (raw brackets) and easier to miss.
- **Root cause (from ROM analysis):** Roark's reward templates use `{0x0108,0x0000,0x0000}` (VAR var_id=0x0108, arg-0=0x0000). The Galactic-grunts Fashion Case templates — which **do** resolve correctly in the same session, same code path — use `{0x0108,0x0001,0x0000}` (arg-0=0x0001). Same var_id. Working theory: Gen 4 VAR arg-0 selects which internal memory slot the game's `TextPrinter` substitutes from. The Roark reward script doesn't populate slot 0 before the text renders, so the raw VAR block reaches our text buffer, and the BUG-005 `_consume_var_block` fix correctly strips it → empty string.
- **Why deferred:**
  - Severity is cosmetic (minor).
  - Fix option (a) — per-var-id substitution reading player name from save block, bag items, pocket names from ROM file 396 — is a big surface area and risks regressing the many code paths where VAR stripping currently works fine.
  - Fix option (b) — read the text buffer at a later point after the game's own substitution pass completes — needs investigation. Likely involves picking a different slot among the multiple `D2EC/B6F8` header markers in the scan region (pre- vs post-substitution buffers).
- **Notes captured for next investigation:** `reference_gen4_var_substitution.md` memory with observed VAR id/arg pairs; QA `BUG_LOG.md` entry updated with the analysis.

### Tests Added (5 tests in `tests/test_qa_bugfixes.py`)
New class `TestQaBug008HexFormatCodeLeak`:
- **Unit (4):** `0x01C2` renders as `&` in "TMs & HMs"; `0x01D2` renders as `%` in "90%"; all 8 pocket sprite icons (`0x0113`..`0x011A`) elide to empty string; end-to-end pocket-label template (`FFFE FF00 0001 0002 | 0x0114 | FFFE FF00 0001 0000 | "KEY ITEMS"`) decodes to `"KEY ITEMS"` with no brackets.
- **Integration (1):** Replays the 4-turn Galactic-grunts battle from `bug008_pre_galactic_battle_win`, asserts `post_battle_dialogue` has no `[XXXX]` tokens anywhere (regex-guarded), plus positive spot-checks that `"90% of all"` and `"KEY ITEMS Pocket"` are present with their glyphs resolved.

All 6 prior BUG-005 tests still pass (regression check) — the new CHAR_MAP entries don't affect the control-code handling.

### Files Changed
- `renegade_mcp/text_encoding.py` — 10 new `CHAR_MAP` entries: `0x01C2='&'`, `0x01D2='%'`, `0x0113`..`0x011A=''`. Section comments reference the ROM files they were enumerated from.
- `tests/test_qa_bugfixes.py` — `TestQaBug008HexFormatCodeLeak` with 5 tests.

### Save States
Four QA-project save states copied permanently into `/workspace/RenegadePlatinumPlaytest/savestates/` for future repros:
- `jubilife_galactic_grunts_double_battle_start.mst` — pre-battle, exercises the Fashion Case cutscene on win (working control for VAR-substitution comparisons).
- `meadow_cleared_works_key_obtained.mst` — post-cutscene, Works Key + Honey dialogue dismissed (for manual inspection).
- `oreburgh_gym_pre_roark_lv20_monferno.mst` — BUG-007 repro target; must win the Roark battle to trigger the reward ceremony.
- `post_galactic_grunts_jubilife_fashion_case.mst` — post-cutscene reference state.

Plus two session-local states saved during investigation:
- `bug008_pre_galactic_battle_win.mst` — integration-test entry point (turn 1 of the Galactic double battle).
- `bug007_pre_roark_battle_start.mst` — mid-Roark-fight snapshot for any future BUG-007 work (Monferno paralyzed, Geodude/Onix survivors).

### Verification
- New BUG-008 tests (5) green — 4 unit tests complete in 0.34s, integration test in 25.5s.
- BUG-005 regression class (6 tests) still green — no regressions.
- Committed as `5ccc902` and pushed to `origin/main`.
- QA `BUG_LOG.md` annotated with BUG-008 FIXED status + BUG-007 root-cause notes; committed on the `qa-run-3` branch locally. **Not pushed** — that branch has diverged 11 local vs 10 remote commits, needs Woj's review before resolving the history.

### Next Session Plan
Three feature requests queued up and waiting for scoping:
- **FR-003** (medium) — Merge `use_battle_item` into `battle_turn` as a fourth action type (mirrors `move_index`/`switch_to`/`run`/`forget_move`). Pure delegation, moderate surface area.
- **FR-004** (medium) — `use_item` is hard-scoped to Medicine pocket; doesn't work for evolution stones. Either generalize to fall through to Items pocket, or add dedicated `evolve_with_stone(party_slot, stone_name)` with ROM-validated compatibility (similar to `teach_tm`).
- **FR-005** (low) — Include active battler species name in `battle_turn(switch_to=0)` rejection error message + clarify battle-slot vs party-slot numbering. Pure signaling fix.

## Dev Session: QA BUG-005/006 — text decoder + shop exit (2026-04-16c)

### Summary
Two items originally filed as QA feature requests (FR-001 and FR-002 from the 2026-04-15 QA run) were reclassified as bugs after live-verified reproduction — leaky text decoders and a buy_item that stopped one state short of overworld. Both fixed, 7 regression tests added.

### Reclassification
- **FR-002 → BUG-006**: `buy_item` returns `success: true` but leaves the game on the "Potion? Certainly. How many would you like?" quantity prompt. Live-verified from QA save `jubilife_mart_after_buy_5potions` (copied permanently into Playtest savestates).
- **FR-001 → BUG-005**: `read_dialogue` / `battle_turn` surface raw `[VAR][XXXX]...` / `[FFFE]...` / `[25BD]` / `[01A8]` tokens in their output. Saved `fr001_repro_growlithe_battle_prompt` — one-call repro: `read_dialogue(advance=False, region="battle")` returns `"What will Chimchar do?[VAR][0200][0001][0000]"`.

Both QA-project entries moved from `FEATURE_REQUESTS.md` to `BUG_LOG.md` with precise repro steps.

### Fixes

**QA BUG-006 — `buy_item` exits shop cleanly:**
- Root cause: the post-purchase poll loop in `shop.py::buy_item` gated on `ScriptManager.is_msg_box_open`, but the Gen 4 shop UI doesn't drive the script manager for its dialog pages — so the loop ran zero iterations. The hardcoded exit (1 B + 2 down + 2 A) was then 2 presses short, landing on "You put away..." instead of the main menu. The final A re-selected Potion from the item list → stuck at "Potion? Certainly. How many?".
- Manual frame-by-frame trace from a `debug_post_yes` save state: 3 B-presses with 300f waits each cleanly unwind the shop UI — B1 advances "Here you are!" → "You put away..." (rendered + money deducted), B2 dismisses dialog → item list, B3 item list → BUY/SELL/SEE YA main menu.
- Fix: replaced broken poll loop with 3 fixed B-presses. Premier Ball bonus case (10+ Poké Balls bought) conditionally adds 2 extra B-presses for the bonus text pages.

**QA BUG-005 — text-code decoder unified:**
- Root cause: three separate decoders (`text_encoding.decode_values`, `dialogue._decode_values`, `battle_tracker._decode_text`) each had a partial take on control-code handling. None understood the Gen 4 VAR block format (`FFFE <var_id> <arg_count> <args×n>` — a total of 3 + arg_count tokens), so VAR blocks fell through as raw `[FFFE][XXXX][XXXX][XXXX]` placeholder sequences. Similarly, 0x25BD line-break and 0x01A8 currency glyph weren't mapped anywhere.
- Fix: added `_consume_var_block(values, i)` shared helper in `text_encoding.py` with a defensive arg-count clamp (>8 treated as 0 to prevent runaway on corrupt data); plumbed into all three decoders. Registered `0x25BD` as `CTRL_LINE_BREAK` → `"\n"` in `TEXT_CONTROL`, added `0x01A8` → `"$"` in `CHAR_MAP`.

### Tests Added (7 tests in `tests/test_qa_bugfixes.py`)

- **BUG-005 (6 tests):**
  - Integration: `read_dialogue(region="battle")` from the FR-001 save state returns clean "What will Chimchar do?" (no brackets anywhere); battle log after `battle_turn` has no `[FFFE]` / `[VAR]` / `[XXXX]` tokens.
  - Unit: `_consume_var_block` advances past FFFE + id + count + args for 1-arg and 2-arg variants; clamps corrupt `arg_count=0xFFFF` to 0 (stops it from swallowing the buffer). `decode_values` strips VAR blocks between regular characters. 0x25BD → newline (split into separate lines). 0x01A8 → `$` (renders as "$100" for currency).
- **BUG-006 (1 test):** load `jubilife_mart_after_buy_5potions` → `buy_item("Potion", 1)` → `read_dialogue` returns `"(no active text)"`. Wrapped in `retry_on_rng` since the save-state load is deterministic but the shop flow relies on timing.

### Files Changed
- `renegade_mcp/text_encoding.py` — added `CTRL_LINE_BREAK` (0x25BD) → `"\n"`, `CHAR_MAP[0x01A8]` → `"$"`, shared `_consume_var_block` helper, VAR-stripping in `decode_values`.
- `renegade_mcp/dialogue.py` — `_decode_values` uses `_consume_var_block`, treats 0x25BD as line-break.
- `renegade_mcp/battle_tracker.py` — `_decode_text` uses `_consume_var_block`, maps 0x25BD alongside existing page-break / newline.
- `renegade_mcp/shop.py` — `buy_item` post-purchase sequence: 3 B-presses (300f each) + existing down×2 + A×2. Premier Ball bonus adds 2 extra Bs.
- `tests/test_qa_bugfixes.py` — 2 new test classes (`TestQaBug005TextPlaceholderLeak`, `TestQaBug006BuyItemExit`), 7 tests total. Docstring updated with the two new save states.

### Save States
Two QA-project save states copied permanently into `/workspace/RenegadePlatinumPlaytest/savestates/` for the test suite:
- `jubilife_mart_after_buy_5potions.mst` — player inside Jubilife Mart, money ¥1,948.
- `fr001_repro_growlithe_battle_prompt.mst` — mid-battle vs wild Growlithe on Route 202.

### Verification
- Shop tool subsuite (12 tests) green post-fix.
- BUG-005/006 regression classes (7 tests) green.
- Full suite: `337 passed in 692.72s (11:32)` against the standalone test emulator. No regressions.

## Dev Session: Decouple test suite from live emulator (2026-04-16b)

### Summary
Stood up a second melonDS process dedicated to the test suite, listening on its own bridge socket. `pytest` now runs against the standalone emulator by default, leaving the emulator Claude Code drives for interactive play entirely untouched. Full suite (**330 tests, 11:27**) ran concurrently with an agent-driven navigation task on the live emulator — both finished cleanly with zero interference.

### Problem
The test suite and interactive play shared a single melonDS process. Running pytest in a session with an active emulator would corrupt test state (or the playthrough), and a known bug caused `load_state` to hang indefinitely when invoked concurrently. The operational rule was "don't touch the emulator while pytest is running" — fine for small runs, painful for a 12-minute full suite.

### Architecture
MelonMCP's bridge is just a Unix domain socket the client connects to — nothing about it is coupled to Claude Code's MCP stdio layer. The server-side bridge path is controlled by `MELONDS_BRIDGE_SOCK` (`server.py:169-172`), and the client-side search respects both the env var and a list of well-known socket paths (`client.py:237-262`). This made it trivial to spin up a second emulator on a different socket.

### Implementation
- **`scripts/start_test_emulator.py`** — standalone bootstrap. Imports `EmulatorState` + `BridgeServer` directly (bypassing the FastMCP stdio layer), initializes the engine, loads the ROM, starts the bridge on `.melonds_test_bridge.sock`, and blocks on a `threading.Event` until SIGTERM/SIGINT. Dedicated `melonds_test_mcp.log` file so it doesn't trample the live emulator's log.
- **`tests/conftest.py`** — added `.melonds_test_bridge.sock` as the first entry in the melonds backend's socket search list. Pytest picks up the standalone when it's running, falls back to the live `.melonds_bridge.sock` otherwise. No env-var wrangling.
- **`.gitignore`** — added `melonds_test_mcp.log*` and `.melonds_test_bridge.sock` to the existing log/socket entries.
- **`CLAUDE.md`** — documented the two-terminal workflow in the Test Suite section.

Both emulators share the same `data_dir` (`/workspace/RenegadePlatinumPlaytest`), so savestates, macros, ROM, and romdata are all visible to both. Only the live socket is written. Checkpoints go to a shared `checkpoints/` directory — in practice this hasn't caused issues since each process keeps its own in-memory ring buffer and hash collisions on state-derived filenames are vanishingly unlikely, but if future test churn evicts a checkpoint the live process still has a handle to, we'd need to split the checkpoint directories.

### Stress test
With both emulators running in parallel:
- **Live emulator** (CC session) — loaded `eterna_city_post_gardenia_team_updated`. Agent task (general-purpose subagent) navigated from Eterna Pokemon Center to the Team Galactic Eterna Building doorstep, saved a new save state. 26s wall time, 7 tool calls. Reported no hangs or unexpected responses.
- **Test emulator** (standalone) — ran full suite: `330 passed in 687.68s (0:11:27)`, exit 0.

**Post-run verification**: live emulator's trainer status and map position matched exactly where the agent left it — money $9,218, badges 2, position (304, 520) Eterna City. Frame count 1363 (all from agent activity). Zero test-induced state leaked across.

### New save state
- `eterna_city_galactic_building_doorstep` — one tile SW of T.G. Eterna Bldg warp (305, 519). Ready for the next play session's Forest Badge follow-up objective.

### Stale guidance corrected
- **`feedback_no_parallel_emu`** memory — rewritten to describe the new model: prefer the standalone, fall back to shared-process rules only when it's not running.
- **`feedback_disable_stream_for_tests`** memory — recovery instruction tweaked to distinguish the standalone process from the live MCP server.
- **CLAUDE.md** — Test Suite section gained a "Dedicated test emulator" subsection with the two-terminal recipe.

### Files changed
- `scripts/start_test_emulator.py` (new)
- `tests/conftest.py` (socket search list)
- `CLAUDE.md` (Test Suite section)
- `.gitignore` (log + socket)
- `DEV_HISTORY.md` (this entry)

Commit `a39a84f` landed the core decoupling; this session added verification + docs.

## Dev Session: Fix + test all 7 QA bugs (2026-04-15b)

### Summary
Implemented fixes for all 7 confirmed QA bugs from the triage session, live-tested 5 against the emulator with QA save states, and added 14 automated integration tests. Two bugs (BUG-005 evolution race, BUG-010 use_battle_item blackout) are probably fixed but lack easy reproduction — BUG-005 was visually confirmed (evolution screen observed), BUG-010 uses identical code path to battle_turn's verified blackout handler.

### Fixes implemented (commit 28f8a2c)
- **BUG-009** (`use_battle_item.py`): Target reporting matched `party_slot` not hardcoded slot 0; bench Pokemon report "HP unverifiable".
- **BUG-010** (`use_battle_item.py`): Added blackout recovery via `_is_battle_over` + `_handle_blackout` after item use.
- **BUG-004** (`turn.py`): MOVE_BLOCKED detection skips opponent's "foe's"/"wild" Taunt-blocked text.
- **BUG-003** (`shop.py`): Post-purchase dialogue polls `is_msg_box_open` via ScriptManager instead of hardcoded 3 A-presses. Added money-spent sanity check.
- **BUG-002** (`dialogue.py`): `advance_dialogue` enters main loop for `CTX_WAITING` scripts, not just `CTX_RUNNING`.
- **BUG-005** (`turn.py`): `_recover_from_level_up` checks evolution text before pressing B; disabled `auto_press` in poll.
- **BUG-008** (`build_map_table.py` + `map_id_to_name.json`): Rebuilt from ROM zone header `mapLabelTextID` field instead of hardcoded area-code mappings. All 593 maps authoritative.

### Bonus fix (commit e24b76f)
- `use_battle_item.py`: Map internal `"ACTION"` prompt_type to public `"WAIT_FOR_ACTION"` — caught during live testing.

### Test file: `tests/test_qa_bugfixes.py` (14 tests)
- BUG-008: 3 tests (static lookup, live map_id, no unknowns)
- BUG-004: 3 tests (Taunt → WAIT_FOR_ACTION, PP consumed, "fell for the taunt" in log)
- BUG-009: 4 tests (bench target, HP unverifiable, active name, final_state mapping)
- BUG-002: 2 tests (cutscene not no_dialogue, Barry dialogue collected)
- BUG-003: 2 tests (10 Poke Balls + 3 Potions, money sanity check)

### Save states created for tests
- `test_bug004_dawn_battle_taunt` — Chimchar vs Turtwig at action prompt
- `test_bug009_roark_battle_monferno_lead` — Monferno active with bench Pokemon, at action prompt
- `test_bug003_oreburgh_city_post_event` — Oreburgh overworld, scripted NPC cleared

### Verification status
| Bug | Status | Evidence |
|-----|--------|----------|
| BUG-008 | Verified | "Oreburgh Gate" returned, 3 automated tests |
| BUG-004 | Verified | WAIT_FOR_ACTION returned, PP consumed, 3 automated tests |
| BUG-009 | Verified | "Slot 1" not "Monferno", 4 automated tests |
| BUG-002 | Verified | Barry dialogue collected, 2 automated tests |
| BUG-003 | Verified | Correct item + cost after Premier Ball bonus, 2 automated tests |
| BUG-005 | Probably fixed | Evolution screen observed visually; read_party stale (heap delta shift) |
| BUG-010 | Probably fixed | Code path identical to verified battle_turn blackout; no easy repro |

## Dev Session: QA bug triage — live verification of 8 bugs (2026-04-15)

### Summary
Verified the 8 bugs the QA Sonnet session filed on 2026-04-14 against the live emulator. Previously all had been static-analyzed only. **Result: 7 reproduced (5 live, 2 via code inspection), 1 not reproducible.** Each confirmed bug now has a documented fix approach, file:line pointer, and preserved repro save state. Backlog memory (`project_tool_improvements.md`) updated so next session can pick a bug and go directly to implementation.

### Setup
Copied the needed QA save states from `/workspace/RenegadePlatinumQA/savestates/` into Playtest's `savestates/` with a `qa_` prefix (so `list_states` picks them up and the existing melonDS bridge can load them without a directory switch). The QA states come from a different battery save with a different heap delta, so `reload_tools` was called after each load to re-detect. `mcp__renegade__reload_tools` was sufficient — no need to flush the MelonMCP bridge.

### Per-bug verification
| ID | Tool | Status | Key finding |
|---|---|---|---|
| BUG-002 | `read_dialogue` | REPRODUCED | Tool returns `no_dialogue` while script is CTX_WAITING for input. Single manual B press unsticks Barry's dialogue, proving script was active. Fix: expand `dialogue.py:304-318` bailout to include CTX_WAITING with a bounded timed-wait. |
| BUG-003 | `buy_item` | REPRODUCED | Poké Ball×15 → Potion×5 yielded Antidote×3. Response `total_cost:1500` vs `money_spent:300` mismatch. Premier Ball bonus dialogue adds 2 extra pages that `shop.py:457-460`'s hardcoded 3 A-presses don't consume. Fix: dialogue-aware post-purchase loop. |
| BUG-004 | `battle_turn` | REPRODUCED | Chimchar Taunt vs Turtwig Withdraw → `MOVE_BLOCKED` returned, but Taunt PP 20→19 (turn consumed) proves the classifier is wrong. Fix: filter "can't use" matches where "foe's" or "fell for the taunt" appears in adjacent log entries. |
| BUG-005 | `auto_grind` | CONFIRMED (code) | `turn.py:1300` presses B BEFORE `turn.py:1306` checks evolution text — classic race. Also `_tracker.poll(auto_press=True)` can press during evo animation. Live repro deferred (~15-battle grind). Fix: swap check-before-press; disable auto_press when evo text may appear. |
| BUG-007 | doubles partner | **NOT REPRODUCIBLE** | Tested move_index=0/1/3 on Monferno partner — all correct (Mach Punch, Flame Wheel, Taunt with matching PP decrements and targets). QA's "always uses Taunt" doesn't fire from clean load. Likely a stale-cursor effect from QA session history. Closing as not-reproducible. |
| BUG-008 | `map_name` | REPRODUCED | map_id=258 returns "Floaroma Meadow" but engine popup shows "Oreburgh Gate"; view_map confirms with a *warp to* Floaroma Meadow (can't BE the place you warp TO). `data/map_id_to_name.json` is stale for Renegade's reshuffled IDs. Fix: rebuild table from per-map zone-header location_name index × msg file 433. Audit the whole table, not just 258. |
| BUG-009 | `use_battle_item` | REPRODUCED | `party_slot=1` passed, response says `target:"Monferno"` (slot 0, active). `use_battle_item.py:221-225` iterates battlers matching only `b.slot == 0`. Fix: walk battlers for `party_slot`; if non-active, skip HP verification. |
| BUG-010 | `use_battle_item` | CONFIRMED (code) | `turn.py:929-941` has the full blackout recovery block; `use_battle_item.py:192-207` has no equivalent. Live 3-KO repro deferred. Fix: copy the 13-line block. |

### Preserved checkpoints / save states
- `qa_oreburgh_gate_entrance.mst` — BUG-008 repro (inside map 258)
- `qa_lake_verity_cyrus_cutscene_done.mst` — BUG-002 repro
- `qa_route202_ready_chimchar_lv10.mst` + `bug004_dawn_battle_pretaunt_backup.mst` — BUG-004 (Dawn rival battle pre-Taunt)
- `qa_oreburgh_city_arrival.mst` + `bug003_pre_buy_repro.mst` — BUG-003 pre-buy state
- `qa_oreburgh_gym_monferno_lead.mst` — BUG-009 / BUG-010 repro (Roark pre-battle)
- `qa_route203_trainers_defeated_monferno.mst` + `bug007_partner_action_checkpoint.mst` — BUG-007 doubles partner action moment
- `qa_jubilife_city_town_map_obtained.mst` — BUG-005 repro path (Chimchar Lv13, 1317/2197 exp)

### Fix difficulty ranking (cheapest first)
1. **BUG-010** — copy 13 lines from turn.py:929-941 into use_battle_item.py after final_state classification. Literal copy-paste.
2. **BUG-009** — change `if b.get("slot") == 0` loop to match `party_slot`; add unverifiable-HP note for non-active targets.
3. **BUG-004** — subject filter for "can't use" log matches (one-line addition or helper function).
4. **BUG-005** — swap two lines in `_recover_from_level_up` + add evo check inside poll loop.
5. **BUG-002** — extend `dialogue.py:304-318` bailout with a bounded wait for CTX_WAITING state.
6. **BUG-003** — rewrite post-purchase section of `shop.py:457-460` to poll `is_msg_box_open` until clear.
7. **BUG-008** — regenerate `data/map_id_to_name.json` from per-map zone headers. Largest change; touches ROM-parsing utility rather than gameplay code.

Next session: just pick from the list. Each bug's memory entry has the exact repro steps, so no re-verification is needed.

## Dev Session: trim Rock Smash + Cut auto-clear (2026-04-15)

### Summary
Reclassified Rock Smash rocks (GFX 85) and Cut trees (GFX 86) as impassable objects instead of auto-clearable HM obstacles. External documentation and on-camera verification at Oreburgh Mine B2F confirmed Drayano removed every path-gating Rock Smash and Cut obstacle from Renegade Platinum — remaining instances are decorative and walkable-around. Auto-clearing was actually counter-productive (the HM animation takes ~5–8s vs. ~1s to walk around). Also decided to drop the planned Strength tool: the only mandatory Strength obstacle is the Distortion World B5F/B6F Lake Guardian boulder puzzle, which is a one-shot and cheaper to handle manually with `press_buttons` when we reach it.

### On-camera verification
Loaded `hm_test_rock_smash_oreburgh_mine_b2f`, ran `navigate_to(21, 28)` then `navigate_to(18, 28)` with streaming on. Footage confirmed the tool smashed both rocks correctly — but the rocks sit in open corridor tiles with clean walkable routes immediately adjacent. Nothing was gated behind them.

### Code changes
- `nav_constants.py`: Emptied `CLEARABLE_OBSTACLES` (`{85, 86}` → `set()`) and `CLEARABLE_TYPES` (`{"rock_smash", "cut_tree"}` → `set()`). Kept `HM_OBSTACLES` dict intact (used for view_map labels via decomp-sourced `GFX_NAMES`). Added a comment block explaining the trim and documenting the one-line restore path. `AUTO_NAVIGATE_TYPES` now contains only Surf/Rock Climb/Waterfall types.
- `pathfinding.py`: No changes. The `if gfx_id in CLEARABLE_OBSTACLES` branches at lines 198 and 844 still exist; with the set empty, Rock Smash/Cut objects fall through to the `else: npc_set.add(...)` branch (impassable). Dual-path BFS and `_bfs_pathfind_obstacles` stay in place for Surf/Rock Climb/Waterfall (which are terrain-based, not GFX-based).
- `hm_traverse.py`: No changes. `_clear_hm_obstacle` is generic and still used by Surf/Rock Climb/Waterfall.
- `navigation.py`, `server.py`: Updated docstrings to reflect the narrower auto-clear scope.
- `CLAUDE.md`, `SAVE_STATES.md`: Updated navigation docs; removed "Cut standalone" and "Strength" from the "Still needed" save-state backlog.

### Test changes
- Replaced `TestRockSmashAutoClear` (6 tests, exercised auto-clear path) with `TestRockSmashImpassable` (4 tests, verify rocks go to `npc_set`, `navigate_to` routes around them, and field-move availability is still detected). Same save state reused.
- Fixed `TestHMObstacleGfxIds::test_gfx_id_mapping` — now asserts `CLEARABLE_OBSTACLES == set()`.
- Fixed `test_surf_auto_navigate_types` — now asserts `rock_smash` and `cut_tree` are NOT in `AUTO_NAVIGATE_TYPES`.
- Full suite: 301/301 pass in 705.69s (was 302; -6 deleted + 4 added = net -2, but one other test was previously counted separately).

### Why keep the scaffolding intact
Emptying the clearable sets rather than deleting the infrastructure means adding a mandatory HM obstacle back takes a single-line change (add GFX id to `CLEARABLE_OBSTACLES`). The only dead code this leaves is the `if gfx_id in CLEARABLE_OBSTACLES` branch itself — net ~10 lines across two files — which is cheap insurance.

