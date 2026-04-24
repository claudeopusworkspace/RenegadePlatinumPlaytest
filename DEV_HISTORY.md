# Dev History

Chronological log of tool development, bug fixes, and MCP improvements — separate from gameplay in GAME_HISTORY.md.

Older entries (2026-04-20 and earlier) live in [DEV_HISTORY_ARCHIVE.md](DEV_HISTORY_ARCHIVE.md).

## Dev Session: Bike-gear encoding inversion + BUG-047 logged (2026-04-24 session 41/42)

Root-caused and fixed the bike-gear address-and-encoding problem that session 39 had misidentified. Session closed with the `session42_wayward_b1f_first_ramp_approach` save, player at (25, 6) on Wayward Cave B1F top of the first east-bound bike ramp in the row-6 chain, mid-puzzle.

### Root cause — `BIKE_GEAR_STATE_ADDR` was pointing at the wrong mirror AND had the encoding backwards

History of the wrong address:
1. **ARM9 BSS `0x021BF6AC`** — early guess. Alternated 0/1 on B-press but drifted out of sync with the true engine gear.
2. **`PLAYER_POS_BASE + 0x6c` (`0x0227F4BC`)** — session 39's "fix" after the ARM9 address failed. Also an alternating mirror, toggled cleanly on B-press, but sometimes showed a gear state opposite to what the engine was actually using. Session-39's decomp-matching encoding (`0=fast, 1=slow`) was written against this mirror's post-load state on one save and didn't generalize.
3. **`PLAYER_POS_BASE + 0x8c` (`0x0227F4DC`)** — the right byte. Found by memory-scanning for tiles that toggle cleanly with every B press across many iterations (`scripts/spike_scan_e4_gear.py`), then empirically verifying on the Route 207 slope that `byte==1` climbs and `byte==0` is rejected (`scripts/spike_gear_truth_v4.py`).

Important subtlety — **this byte is *inverted* from the decomp's `PlayerData.cyclingGear`**. It's an engine mirror, not the authoritative PlayerData field, and at this mirror:
- `byte == 1` = **FAST** (climbs slopes, fires JUMP_FARTHER)
- `byte == 0` = **SLOW** (bounces off slopes, fires JUMP_NEAR_SHORT at 0 momentum)

To keep call sites readable, `_set_bike_gear(emu, target_gear)` now takes decomp-style semantics (`0=fast, 1=slow`) at the boundary and XORs internally to translate to the byte. This hides the inversion so `this_gear = 0  # fast` in the ramp-segment planner and `_set_bike_gear(emu, 0)` in the slope traversal keep their intuitive meaning.

### Rabbit-hole that delayed discovery

First empirical "proof" (`spike_gear_truth_v3.py`) used `bug_bike_slope_north_climb_fail` — which I *assumed* was a slope runway save. It wasn't. Player was at (299, 730) on Route 207, 14 tiles west of the actual slope. Holding UP from there walked through tall grass for 15 tiles — no slope involvement — and I mis-read the displacement as "gear=0 climbed." Woj caught it: *"what level is the player on? Perhaps the position you asked for it to move to was incorrect to begin with?"* The follow-up spike (`spike_gear_truth_v4.py`) on `route207_at_bike_slope_bottom` (the actual slope-bottom save) gave the real answer.

**Feedback takeaway saved to memory:** pick spike saves with care and verify the player is *in the regime you're testing* before drawing conclusions (`feedback_spike_save_verification.md`).

### Code changes

- `renegade_mcp/addresses.py:84`: `BIKE_GEAR_STATE_ADDR = 0x0227F4DC` (was `0x0227F4BC`). Tagged `"field_ow"` heap group. Doc comment rewritten to explain the inversion vs decomp.
- `renegade_mcp/use_item.py::_set_bike_gear`: XOR on the target internally (`target_byte = 1 - target_gear`). Caller API unchanged — decomp semantics preserved.
- `renegade_mcp/cycling_road.py`, `renegade_mcp/navigation.py`: comment cleanups — call sites that used `# byte=0 fast` now say `# decomp semantic; _set_bike_gear inverts`.
- `tests/test_cycling_road.py::TestBikeSlopeConstants::test_gear_address_valid`: range updated to the FieldOverworldState heap. `test_gear_toggle` asserts raw before/after toggle rather than a specific value.
- Three slope tests (`test_slope_in_path`, `test_traverse_reaches_target`, `test_close_target_near_slope_top`) migrated from `_navigate_to_impl` to the public `navigate_to`. Cause: the BFS bounces back-and-forth around the slope runway when NPC motion drives proactive repaths. `_navigate_to_impl` alone can hit `MAX_REPATHS=15` before the slope-trigger fires; `navigate_to` wraps it in `_nav_impl_with_overshoot_retry` which gets one more full attempt. Production uses the wrapper, so the tests should too. Full suite: **554 passed @ ~5:10 (N=8).**

### Playthrough progress & BUG-047

With gear fixed, the slope on Wayward B1F climbs cleanly (`navigate_to(7, 6)` from (13, 9): 17 steps, one bike_slope obstacle, one-shot success). Woj then asked about BUG-046's east-chamber reachability — confirmed still open:

- Dumped BDHC elevation (`scripts/spike_dump_elevation_levels.py`). Both `(13, 9)` and `(23, 9)` are level 0; `(33, 8)` (obj:3 Pokéball) is also level 0. The 3D BFS rejects nav between them not because of elevation classification but because there's no connected level-0 corridor between the east chamber and any ramp that reaches level 2. BUG-046 remains the gating issue for obj:3 and warp:0.
- During an attempt to navigate `(16, 6) → (25, 6)`, a Repel expired mid-bridge. Instead of surfacing the repel-expiration or flee-ing the resulting encounter, `navigate_to` raised `KeyError: 'move'` (`navigation.py:1751/1755` accesses `ob["move"]` unconditionally when formatting the obstacle-choice prompt). Logged as **BUG-047**, repro save `bug_nav_repel_expired_move_keyerror` (frame 1334845). Not fixed this session.

### Mid-range ramp jump distance — new open question (future session)

Reached (25, 6) and spotted the next Pokéball: the puzzle wants a jump of *exactly 3 tiles past the first ramp*, then NOT taking a chained second ramp. Our BFS only models two ramp landing distances:
- **FAR**: approach + 5 = ramp + 4 (requires RUNWAY_TILES=4 of momentum)
- **NEAR**: approach + 2 = ramp + 1 (from momentum=0)

Mid-range (ramp + 2 or ramp + 3, from 1 or 2 tiles of runway) is intentionally excluded from BFS edges — `nav_constants.py:127-131` notes the earlier spike was inconclusive because a wall clamped the landing. This Wayward puzzle is a clean mid-range case on the row-6 chain. Saved `session42_wayward_b1f_first_ramp_approach` (player at (25, 6), facing east, first-ramp-approach tile) for the follow-up spike; goal is to confirm whether 1-tile runway → ramp+2 and 2-tile runway → ramp+3 are indeed deterministic, then add those edges to `_bike_ramp_segment`. Noted in `project_tool_improvements.md`.

### Files added

- `scripts/spike_gear_truth_v4.py` — definitive gear encoding proof via Route 207 slope climb.
- `scripts/spike_gear_truth_v5.py` — `_set_bike_gear` API round-trip confirmation.
- `scripts/spike_dump_elevation_levels.py` — BDHC level / ramp dump around a given player position.
- Several dead-end spike scripts (`v2`, `v3`, `spike_gear_encoding_truth`, `spike_fow_*`, `spike_find_authoritative_gear`, etc.) left checked in per the "spike-before-redesign" policy as a record of the rabbit hole. Safe to prune later.

### Memory updates

- `reference_bike_gear_encoding.md` — rewritten with the correct address, inverted encoding, and the `_set_bike_gear` abstraction.
- `project_tool_improvements.md` — **BUG-047** added above BUG-046. Description-line updated.

## Dev Session: Bike-bridge traversal + overshoot-retry wrapper (2026-04-23 session 40)

Next obstacle after the 4-ramp chain puzzle: the Wayward Cave east-wing **bike bridges** — wooden suspension-bridge tiles that reject on-foot entry. User's pre-session hypothesis was correct: "something like the swimming implementation, but instead of interacting with the water when at the edge, you get on the bike, and once you're off the other edge, you get off the bike. Clean and simple, I'm hoping." Empirical observation confirmed three engine invariants that made this genuinely simple — plus one engine quirk (bike coasting) that forced a small but general repath-after-overshoot wrapper.

### Empirical observations at `bug_bike_bridge_unknown`

Map 285, player (22, 13) on foot on a `bridge_start` (0x70) tile directly east of the south bridge body:

- **On-foot step onto 0x7A/0x7B body → BLOCKED.** Zero displacement, even with sustained hold. Engine refuses.
- **On-bike step → succeeds.** Slow gear, fast gear — both ride through cleanly. **No momentum requirement**, no forced slide. Just "must be on the bike".
- **Mid-bridge `use_item("Bicycle")` → fails.** Engine rejects the menu while the player is on a body tile. Nice safety net: the pathfinder cannot create a "stuck mid-bridge" state.
- **`bridge_start` (0x70) is walkable on foot AND bike.** It's the hinge tile at each end. Mount can happen ON `bridge_start`, not just before it.
- **Exit does NOT auto-dismount.** Riding off onto cave_floor keeps the bike mounted — the navigator has to emit the dismount itself.

### Problem 1 — bridge behaviors not modeled in the executor

`_scan_path_for_bike_obstacles` populated obstacle_tiles with ramps + slopes but not bridges. `_step_needs_bike` only looked at ramp runways + immediate-next slope tiles. BFS happily planned paths through bike-bridge bodies (they're `passable=True` in the terrain grid — same as ramps), but the executor walked into them on foot and bonked forever.

**Fix.** `nav_constants.BIKE_BRIDGE_BEHAVIORS = {0x76–0x7D}` + `BIKE_BRIDGE_TYPES = {"bike_bridge"}`. Scanner now tags body tiles crossed by the path. `_step_needs_bike` returns True when **current OR immediate-next** tile is a bike-bridge body — the *current*-tile check is what keeps the bike active for the last exit step (body → bridge_start) so the executor doesn't emit a doomed dismount while still on a body tile. Error path extended to report `bike_bridge_requires_bicycle` when `_auto_mount_for_slope` fails on a bridge step.

### Problem 2 — bike coasting overshoots the target

First live test (`navigate_to(14, 13)` from (22, 13), a straight-west crossing): 8 lefts planned, player ended at (11, 14) — 3 tiles past target + 1 south. Instrumentation pinned the cause precisely:

- After step_hold returns at (15, 13) on bike, the bike **coasts 3 tiles west** with no button held (stable coast-drift of ~20 frames on cave_floor after fast-gear release).
- During the subsequent dismount menu, `open_pause_menu`'s verification `down` keypress fires while the bike is still in overworld → registers as a bike input → +1 south drift on top of the coast.

Tested the cycling_road.py "drain momentum" recipe (slow gear + 120f idle before dismount) — the ~38f gear-toggle window let the bike coast another 3 tiles during the toggle itself, so even with drain the player overshoots. Tested mounting in slow gear *before* crossing: the gear byte flipped back to 0 (fast) during the first step_hold, but coasting was fully eliminated — empirical evidence that setting slow gear drains some internal momentum counter independent of the surface-level byte. **Kept the slow-gear mount** (cheap, helps) but couldn't fully eliminate coast on the east-bound trip.

### Problem 2 (fix) — repath after overshoot instead of fighting coasting

Per Woj: "If it overshoots, just add a step after getting off the bike afterwards to correct (if necessary, might just want to recalculate the full path at that point anyways since the overstep might even be beneficial)."

Added `_nav_impl_with_overshoot_retry` — a thin wrapper around `_navigate_to_impl`. If the inner call returns `stopped_early` + `blocked_reason == "path_exhausted_before_target"`, it re-BFS-es from the player's current position and retries (up to 3 times). `path_choice` is honored only on the first attempt; retries are treated as repaths. `start` is preserved across retries, `steps` is summed.

This is intentionally general: any future "engine carried the player past the planned final tile" case gets the same treatment without a bike-bridge-specific branch. East-bound trip: first pass overshoots to (25, 13), retry plans `left x3` on foot, lands on (22, 13). `overshoot_repaths: 1` surfaces in the result for observability.

### Problem 3 — `is_on_cycling_road` false-triggered on Wayward bridges

Retry then hit a second bug: `is_on_cycling_road(emu, 22, 13)` returned True because target (22, 13) is `bridge_start` (0x70), which was in the `BIKE_BRIDGE_BEHAVIORS` set used by the target-tile check. That set also included 0x76–0x7D — but those are Wayward-style bike bridges, NOT cycling-road auto-slide tiles. Pre-existing bug that my change surfaced.

**Fix.** `map_state.py`:
- Narrowed the cycling-road constant to the actual forced-slide behaviors (`CYCLING_ROAD_BRIDGE_BEHAVIORS = {0x70, 0x71}`); kept `BIKE_BRIDGE_BEHAVIORS` as an alias for the existing `test_cycling_road` import.
- Removed the naive target-tile-behavior fast path in `is_on_cycling_road` (the column-scan height-gated heuristic still catches "player at bridge elevation stepping onto bridge from above", which is the real motivating case). Comment block calls out the Wayward false-positive.

### Files touched

- `renegade_mcp/nav_constants.py` — `BIKE_BRIDGE_BEHAVIORS`, `BIKE_BRIDGE_TYPES` (new).
- `renegade_mcp/map_state.py` — `CYCLING_ROAD_BRIDGE_BEHAVIORS` (new, narrow), `BIKE_BRIDGE_BEHAVIORS` alias retained, `is_on_cycling_road` target-tile check removed.
- `renegade_mcp/navigation.py` — scanner + `_step_needs_bike` + executor mount branch (slow-gear flip) + error path + `_nav_impl_with_overshoot_retry` wrapper; public `navigate_to` now dispatches through the wrapper.
- `tests/test_navigation.py` — `TestBikeBridgeTraversal` (3 tests).

### Session take-aways

1. **Empirical > decomp, again.** Engine forbids mid-bridge dismount was a nice invariant I wouldn't have guessed from source; confirmed in under a minute with one `use_item` call.
2. **"Match the engine behavior" beat "fight the engine behavior".** Fighting the bike coast (opposite-direction brake, mid-ride gear toggle, brute-force drain) produced fragile partial fixes. Accepting the coast + re-BFS after dismount is simpler, more general, and cost-free on paths where the coast happens to land on target.
3. **Shared constants drift.** The map_state `BIKE_BRIDGE_BEHAVIORS` was defensively over-included from when 0x76–0x7D semantics were unknown; narrowing it was one line but required understanding all callers. Worth an audit pass on similar "I'll just include everything that might be relevant" sets elsewhere.

### Commits

- `bdd47c1` — `feat(nav): bike-bridge traversal + overshoot-retry wrapper`

## Dev Session: Near-jump ramp BFS + gear encoding empirical verification + slope-remount reset (2026-04-23 session 39)

Goal that kicked off the session: the Wayward Cave 4-ramp chain puzzle. The solution isn't "hit every ramp at full momentum" — the LAST ramp in the chain has to fire a **near-jump** (land 1 tile past the ramp, not 4) so the player threads the correct corridor instead of overshooting into a consolation dead-end Pokéball. Extended BFS to admit near-jumps, unified gear control via `_set_bike_gear`, and — after a painful encoding misstep — documented the true empirical semantics of `BIKE_GEAR_STATE_ADDR`. Closes the puzzle. Full regression suite green (551 passed, 3:43).

### Problem 1 — BFS only planned far-jumps

`_bike_ramp_edges` in pathfinding.py now emits **two** edge classes per ramp:
- `momentum + 1 >= RUNWAY` → far jump (5-tile displacement, post-momentum = RUNWAY)
- `momentum == 0` → near jump (2-tile displacement, post-momentum = 1)
- mid-range momentum (1–2 prior same-direction tiles) → NO edge. The in-between regime is untested; BFS intentionally refuses to plan into it.

Wired into all four BFS variants (`_bfs_reachable`, `_bfs_pathfind`, `_bfs_pathfind_level`, `_flood_fill_level`). `navigation._bike_ramp_segment` locks `segment_gear` from the first ramp's momentum class and bails if a subsequent ramp in the same hold-chain wants the opposite gear — a mixed far+near chain can't satisfy one sustained hold, so the per-tile fallback takes over.

### Problem 2 — gear control as input, not memory-write

Old code used `emu.write_memory(BIKE_GEAR_STATE_ADDR, value=1)` to flip gear mid-traversal. This was unreliable: the engine re-syncs the byte from an authoritative mirror within ~60f, so writes silently revert. New helper `_set_bike_gear(emu, target_gear)` in `use_item.py`:

- Reads current gear byte.
- If mismatched, emits `press_buttons(["b"], frames=8) + advance_frames(30)` (matches cycling_road.py's known-working slope-prep pattern).
- Retries up to 5× with a 15f window.
- Requires `CYCLING_GEAR_ADDR` truthy (pressing B while walking/surfing/in-dialogue does something else entirely).

`_ensure_fast_gear` is a thin wrapper around `_set_bike_gear(emu, <fast>)`. The segment executor threads the segment's required gear through and calls `_set_bike_gear` once before the hold-chain.

### Problem 3 — the decomp encoding trap (and the rollback)

The decomp at `ref/pokeplatinum/src/player_avatar.c:438` says `PlayerData_Init` sets `cyclingGear = 0`, and `sub_0205F95C` in `unk_0205F180.c:618` branches `gear == 1` to the bigger-jump action. Read naively, this says byte=0 is slow and byte=1 is fast. Based on that, I flipped the encoding assumption in `_ensure_fast_gear`, `_set_bike_gear`, and the segment simulator. Ramp tests passed. Two cycling-road slope tests regressed.

**Empirical re-verification on `route207_at_bike_slope_bottom`:**
- Initial byte=1 at save state — slope bounces player back, can't climb.
- After one B-press: byte=0 — slope climbs cleanly on running-start hold.

`BIKE_GEAR_STATE_ADDR` is NOT `PlayerData.cyclingGear`. It's a different mirror whose semantics are **inverted** from the decomp's `CyclingGear`. Byte **0 = FAST** (climbs slopes, fires far-jump with momentum), byte **1 = SLOW** (default after mount, bounces off slopes). Rolled back all call sites. Added a comment block to `addresses.py` warning against copying decomp `== 1` checks. Saved `reference_bike_gear_encoding.md` memory so future sessions don't walk into the same trap.

### Problem 4 — slope traversal fails after nav-repath churn

Even with the correct encoding, `test_close_target_near_slope_top` and two peers still failed inside `_navigate_to_impl(306, 710)` from `route207_at_bike_slope_bottom`. Directly calling `_traverse_bike_slope` after a single failed step_hold worked fine; under the full nav flow it didn't.

Traced it: BFS plans "down x3 -> up x13" (a south backup then climb), and because the slope is a chokepoint, the path oscillates UP/DOWN for ~30 step_hold calls before committing to the climb. By the time the blocked-check triggers the slope branch, the bike's internal state (movement queue, momentum counter, dir-lock) is in a configuration where `_set_bike_gear(0)` — which reads the post-bounce transient byte=0 and no-ops — isn't enough to get the slope to fire. Backup presses then re-sync gear to 1 and the climb refuses.

**Fix:** `_traverse_bike_slope` now does a full dismount+remount at the top (`use_item("Bicycle")` twice, 30f between). Cost ~400f (~7s) per slope traversal, acceptable for an infrequent primitive. Nine slope tests now pass.

### Files touched

- `renegade_mcp/pathfinding.py` — `_bike_ramp_edges()` (new), wired into 4 BFS variants.
- `renegade_mcp/navigation.py` — `_bike_ramp_segment` returns `segment_gear`; executor threads it into `_set_bike_gear` before the hold-chain.
- `renegade_mcp/nav_constants.py` — `BIKE_RAMP_NEAR_JUMP_TILES = 2` + updated comment block on the two-case model.
- `renegade_mcp/use_item.py` — `_set_bike_gear` (new), `_ensure_fast_gear` rewritten to use it.
- `renegade_mcp/cycling_road.py` — `_traverse_bike_slope` prelude is now dismount + remount + `_set_bike_gear(0)`.
- `renegade_mcp/addresses.py` — corrected encoding doc comment with decomp-vs-empirical warning.
- `tests/test_navigation.py` — +4 tests on ramp-edge emission.

### Followups

- **Bike bridges** — next obstacle on the Wayward Cave east wing. Save state `bug_bike_bridge_unknown.mst` already exists (map 285 @ (22, 13) on foot) for a dedicated future session.
- Task #6 in the session task list is marked pending as the reminder; the repro is captured in `SAVE_STATES.md` and this log.

## Dev Session: Bike-ramp segment execution + POI-path ramp scanner (2026-04-23 session 38)

Goal that kicked off the session: auto-navigate to the east-chamber Pokéball in Wayward Cave (`bug_bike_ramps_repel`, target (31, 17) via a 4-ramp chain). Session 37 had closed the BFS side; session 38 closed the executor side. **Goal achieved: `navigate_to(poi="obj:2")` picks up the Max Ether in 8 steps with 1 repath.**

### Repro with Repel

Woj noted the previous spike was being swamped by wild encounters. Built a dedicated save state `bug_bike_ramps_repel` (player at (7, 22) on bike, Repel active) so diagnostic spikes see clean executor behavior without 11 encounter-flee interruptions per run. Checked-in `scripts/spike_debug_ramp_nav.py` monkey-patches `_step_needs_bike`, `_bike_ramp_segment`, `_auto_mount/dismount`, and `step_hold` to log per-step decisions.

### Problem 1: cross-axis momentum slip at direction changes

First spike revealed: `up x5` on bike → first `left` step landed at (6, **16**) instead of (6, 17). The bike finishes its in-flight up-step during the `left` press, shifting the player diagonally off the planned path. `step_hold`'s axis-change exit condition misses the cross-axis drift because it only watches the target axis.

**Fix direction (from Woj):** "make sure that any movement outside of actual slope/ramp runs is off the bike entirely." Dismount aggressively — the bike is only on during runway + ramp/slope chains, walking on foot everywhere else.

### Implementation — `_step_needs_bike` + dismount-between-segments

`renegade_mcp/navigation.py`:

- `_auto_dismount_if_bike(emu)` — no-op when already off-bike; otherwise uses the Bicycle item.
- `_step_needs_bike(directions, i, obstacle_tiles, cur_x, cur_y)` — True when the step is a slope ascent on the IMMEDIATE next tile OR a ramp appears within `BIKE_RAMP_RUNWAY_TILES` ahead (same direction only — momentum resets on turn). Slope check limited to the immediate tile (not full runway) so the BUG-045 slope-runway backup plan doesn't cause mount/dismount thrashing against the BFS repath loop.
- `_bike_ramp_segment(...)` — forward-simulates the path through chained ramps and returns `(segment_end_idx, landing_x, landing_y, last_ramp_tile_x, last_ramp_tile_y)` when a runway + ramp chain exists starting at step `i`.
- `_execute_path` gets a new mount/dismount decision at the top of the loop:
  - `step_wants_bike and not on_bike` → settle `WAIT_FRAMES` + mount + `active_hold = BIKE_HOLD_FRAMES`.
  - `not step_wants_bike and on_bike` → dismount + `active_hold = hold_frames` (gated on non-surfing, see Problem 3).

### Implementation — sustained-hold ramp chain

Per-tile `step_hold` during a ramp chain releases the direction button between tiles, draining the engine's bike-momentum timer. On the second ramp of the chain the ramp fires at slow-gear displacement (1-tile hop instead of 5). Matches the "direction button isn't being held continuously enough" symptom Woj flagged in session 36.

New branch in `_execute_path`: when `step_wants_bike` and `_bike_ramp_segment` returns a segment, execute the whole runway + chain as ONE continuous hold:

```
write BIKE_GEAR_STATE_ADDR = 0 (fast)
advance_frames(90)                  # post-mount settle
write BIKE_GEAR_STATE_ADDR = 0      # re-assert fast gear
advance_frames_until(
    buttons=[direction],
    until: PLAYER_POS_axis reaches last-ramp-tile coord
)
advance_frames(36)                  # let the final jump animate
```

Polling for the LAST RAMP TILE (not the landing) and then idling 36f matches the `spike_ramp_poll_release.py` pattern from session 36 — releasing mid-jump drifts +1 past the landing. On `reached=True`, clears the crossed ramp tiles from `obstacle_tiles` so repaths don't re-plan them. On `reached=False`, falls through to per-tile logic (which detects the blocked step and triggers repath — cold-mount flakiness self-recovers on the second attempt).

### Problem 2: the POI path didn't mount at all

First end-to-end test via `navigate_to(poi="obj:2")` on the interactive emulator: player walked to (9, 17) on foot and looped repeatedly charging at the ramp. 99 steps, `blocked_at (9, 17)`. Coordinate mode (`navigate_to(31, 17)`) worked fine.

Root cause: POI items dispatch through `interaction.py::interact_with`, which calls `_execute_path` directly without pre-populating `obstacle_tiles`. The ramp-scanner lived only in `_navigate_to_impl`, so `_step_needs_bike` saw an empty obstacle map, never returned True, and the mount branch never fired.

**Fix:** extracted `_scan_path_for_bike_obstacles(directions, terrain_info, start_gx, start_gy, grid_ox, grid_oy, obstacle_tiles)` and moved the scan into `_execute_path` itself — runs whenever `repath_ctx` carries `terrain_info` (both navigate_to and interact_with populate it). Idempotent: navigate_to's pre-population is kept.

### Problem 3: surf regression from the new dismount branch

Full suite after the dismount fix failed 2 tests: `test_navigate_across_water` (1 tile too far south), `test_navigate_through_waterfall` (5 tiles too far south). Both pass at HEAD.

Instrumented the surf path: `CYCLING_GEAR_ADDR` is named "0=walking, 1=cycling" but empirically reads as **1 during surf** too. My dismount branch fired, `use_item("Bicycle")` failed (can't dismount what isn't the bike), but the bag menu open/close frames let in-flight surf motion drift the player 1 tile off-axis per spurious attempt.

**Fix:** gate the dismount on `not is_surfing` where `is_surfing = repath_ctx.get("surfing") or active_hold == SURF_HOLD_FRAMES`. Both signals are set by the existing Surf/Waterfall activation branches.

### Tests

`TestBikeRampSegmentExecution` (3 tests in `test_navigation.py`):
- `test_navigate_reaches_east_chamber_pokeball` — coordinate-mode navigate_to(31, 17) from (7, 22) reaches target. Repaths tolerated (cold-mount flakiness self-recovers).
- `test_on_foot_during_non_ramp_walking` — navigate_to(6, 17) ends with `CYCLING_GEAR_ADDR == 0`. Validates the aggressive-dismount behavior.
- `test_poi_pickup_reaches_east_chamber_pokeball` — `interact_with(object_index=2)` reaches (31, 17) without `stopped_early`. Covers the interact_with path specifically.

Full suite: **546 passed @ 3:26 (N=8)**.

### Commits
- `0091034` — dismount-between-segments + sustained bike-ramp segment + surf gate
- `13f6bf7` — _execute_path auto-scans ramps/slopes for callers that skip navigate_to

### Memory saved
- `reference_cycling_gear_mount_states.md` — CYCLING_GEAR_ADDR is overloaded across bike + surf; disambiguate via `repath_ctx['surfing']` or `active_hold == SURF_HOLD_FRAMES`.

### Engineering lessons
1. **Don't rely on memory byte naming.** `CYCLING_GEAR_ADDR` was documented as bike-only but was actually a general mount-state flag. Empirical observation trumps the documented semantic, just like the session 36 ramp-landing constant that contradicted the decomp.
2. **Check every caller of a primitive when you change its contract.** Adding "obstacle_tiles must contain ramp entries" as a precondition for correct `_step_needs_bike` behavior silently broke `interact_with` — it's a direct caller that wasn't in the head when the primitive was tweaked. Scanning for call sites before merging would have surfaced this pre-commit.
3. **Woj's "dismount for all non-ramp walking" framing** was the key simplification. I was chasing "why does bike momentum slip cross-axis?" at the primitive level when the answer was "avoid the regime entirely."

## Dev Session: Bike-slope momentum gate + flee-loop start preservation (2026-04-23 session 37)

BUG-045 (bike-slope BFS admits turn-into-approach) closed, plus BUG-044's primary symptom (mis-reported `start` field) fixed. Session-35 momentum-aware BFS extended from ramps to slopes.

### Repro & spike

Loaded `bug_bike_slope_turn_into_approach` (player at (8, 28), Wayward Cave B1F, on bike). Raw 2D BFS found a 22-step path starting `left → up x11` — exactly the turn-into-approach Woj described. Empirical spike `scripts/spike_bike_slope_runway.py` (and helper-direct test `scripts/spike_bike_slope_helper.py`) confirmed the engine's running-start detection is finicky on this save — no approach-length from my synthetic setup reliably crossed the slope. End-to-end navigate_to(7, 25) from (7, 31) *did* cross, so the engine works with natural south-approach; the helper backed-up + continuous-hold pattern doesn't reproduce the natural approach state.

### Implementation — BFS momentum gate (BUG-045)

`renegade_mcp/nav_constants.py`:
- New constant `BIKE_SLOPE_RUNWAY_TILES = 4` (matches existing `BIKE_SLOPE_BACKUP_TILES=3` + approach tile, same shape as `BIKE_RAMP_RUNWAY_TILES=4`).
- Comment block explains slopes are N-S only, `up` entries only are gated, descents auto-slide.

`renegade_mcp/pathfinding.py`:
- New `_bike_slope_entry_blocked(terrain_info, x, y, direction, dx, dy, momentum)` helper. Rules: (1) only `up` entries gated; (2) `momentum + 1 >= RUNWAY` admits; (3) slope-to-slope steps (source tile also 0xD9/0xDA) are ungated — the engine's running-start check fires once on initial entry, and BFS tile-by-tile model of the engine's single continuous climb would otherwise false-block step 2 on 3D-BFS recursions re-entering a slope tile at the destination level with fresh momentum=0.
- Threaded into all four BFS variants (`_bfs_reachable`, `_bfs_pathfind`, `_bfs_pathfind_level`, `_flood_fill_level`). `_bfs_pathfind_obstacles` intentionally not gated — it's only chosen when HM obstacles are crossed, which doesn't intersect slope geometry.

After fix, 3D BFS from (8, 28) to (7, 25) returns `down x3 → left → up x6` (10 steps) — south-approach built from runway, slope crossed reliably, tile (7, 25) reached on level 2.

### Implementation — flee-loop start preservation (BUG-044 partial)

`renegade_mcp/navigation.py::navigate_to`:
- Outer flee-retry loop now saves `original_start = result.get("start")` from iteration 1 and restores it on the final result. Before: each `_navigate_to_impl` iteration captured its own `start_pos` from the current position, so retries after slope overshoot + wild encounter flee leaked an intermediate position into the final result.
- Path-string mis-report (original BFS plan vs actual trajectory when mid-execution repath shortens the remainder) is still open — low priority, cosmetic; requires tracking the cumulative direction sequence through `_execute_path`.

### Tests

New `TestBikeSlopeBfsEdges` (9 tests in `test_navigation.py`):
- 5 unit tests on `_bike_slope_entry_blocked` (blocked without momentum, admitted with full runway, ungated for descent / lateral / non-slope).
- 3 synthetic-grid BFS tests: turn-refused, long-runway admitted, descent-no-runway.
- 1 save-state integration test on `bug_bike_slope_turn_into_approach` asserting 3D BFS finds a south-approach path with ≥3 prior up-steps before the slope.

New `TestBug044StartPreservedAcrossFleeLoop::test_start_preserved_after_flee_retry` — asserts `navigate_to(7, 25, flee_encounters=True)` from the slope repro save returns `start == initial_player_position` across slope overshoot + flee iterations.

### End-to-end verification

Live `navigate_to(poi="obj:2")` from (8, 28) now routes `down x3 -> left -> up x14 -> left -> right x9` — slope traversed cleanly in the first call (11 wild encounters fled, player ends at (8, 17) post-slope, well past the barrier). Chamber-beyond-chamber routing involves further ramp/slope chains out of scope for BUG-045.

Full suite: **544 passed @ 2:40 (N=8)**. 10 new tests (9 slope + 1 BUG-044 start-preservation).

### Engineering lesson

The slope-to-slope skip came from debugging the 3D-BFS recursion: after transitioning levels via the slope ramp, `_bfs_pathfind_level` re-ran on the new level with fresh momentum state, and the gate incorrectly false-blocked the continuation step. The pokeplatinum engine only requires momentum on INITIAL slope entry — once on a slope tile a continuous hold carries through. The BFS gate must mirror that: don't over-gate BFS continuations on the same terrain feature when the engine doesn't re-check mid-traversal.

## Dev Session: Poll-based bike ramp execution + BFS landing off-by-one (2026-04-23 session 36)

Follow-up to session 35. Woj flagged that although momentum-aware BFS predicted the east-chamber chain was reachable, attempting to actually execute the chain still failed on the second ramp — "presumably the direction button isn't being held continuously enough to go from one ramp to the next." Two bugs fell out of the investigation: a BFS landing off-by-one that had been latent since BUG-042, and an executor that released the direction button for 36 frames between every ramp step (draining bike fast-gear state).

### Spike first

`scripts/spike_ramp_pos_sampling.py` — frame-by-frame sampling of `PLAYER_POS_BASE+8` during a ramp jump. Question was whether the tile-x field is tile-quantized or fx32 sub-tile (per `step_hold`'s `"changed"` primitive, tile-quantized was the strong prior). Result: **field is tile-quantized, every single integer tile is written, no skips.** `advance_frames_until(value == landing_x)` at `poll_interval=1` cannot miss the landing; `>=` is strictly safer and costs nothing.

`scripts/spike_ramp_poll_release.py` — measure where the player comes to rest when we poll-and-release at various tiles. Surprise result: **releasing at BFS-predicted landing (x=13 = approach+4) with ≥8 frames of idle drifts the player to x=14**. Releasing AT the ramp tile (x=10) with 32+ frames of idle stably lands at x=14. The true fast-gear landing is `approach + 5 = ramp + 4`, one tile further than the `BIKE_RAMP_JUMP_TILES=4` constant predicted — **BFS was off by one, and the decomp citation of "3 past ramp" from `src/unk_020655F4.c:994` didn't match the engine's actual behavior** (`JumpFartherEast` = FX32_CONST(4), 12 frames).

### Implementation

`renegade_mcp/nav_constants.py`:
- `BIKE_RAMP_JUMP_TILES = 4 → 5` (displacement from approach tile = ramp + 4, fast gear). Comment block updated to cite the empirical spike result as ground truth, overriding the prior decomp-based "3 past ramp" interpretation.

`renegade_mcp/navigation.py::_execute_path` — ramp branch:
- Replaced `advance_frames(BIKE_HOLD_FRAMES, buttons=[dir]) + advance_frames(36)` with `advance_frames_until` polling the direction until the player steps ONTO the ramp tile (`approach + 1`), then releases and idles 36f for the discrete `JumpFartherEast` animation to play out. Poll-driven entry preserves bike fast-gear state across adjacent loop iterations (brief inter-iteration release instead of 36f gap), unblocking the chained-ramp case while still letting the jump complete at its natural `+4` landing.
- Tried polling *through* the landing first — catches the landing tile cleanly, but because the button is still held during the engine's discrete jump, bike fast-gear continues past the natural end and releasing mid-animation drifts the player +1 to +4 tiles depending on subsequent idle time. Releasing at the ramp tile (before the jump fires) and letting the engine play out atomically is the only pattern that stably lands at `approach+5`.
- New `last_step_was_ramp` flag. When the final step of a path was a ramp, skip the end-of-path `advance_frames(WAIT_FRAMES)` settle — the 36f in-ramp idle already settled the jump, and an extra 8f of no-input would drift the player +1 past the landing (drift saturates at +1 per spike data).

`renegade_mcp/pathfinding.py::_bike_ramp_landing`:
- Docstring updated to reflect the new `approach + 5 = ramp + 4` landing.

`renegade_mcp/navigation.py` path scanner (line ~1468):
- Comment block updated.

### Tests

All 10 `TestBikeRampBfsEdges` tests updated to the new constant:
- 4 `_bike_ramp_landing` unit tests widened their grids from 8 to 9 cols and bumped expected landings by 1 (e.g. approach `(3, 0)` with ramp at `(4, 0)` now lands at `(8, 0)` instead of `(7, 0)`).
- `test_2d_bfs_crosses_ramp_in_wayward_cave` — ramp landing assertion `(13, 17) → (14, 17)`.
- `test_2d_bfs_chains_ramps_via_momentum_carry` — synthetic 2-ramp layout: mid-jump walls expanded to cols 7-9 + 12-14 (3 tiles each instead of 2), landing assertions moved to (10, 0) and (15, 0). Chained path shrank from **9 edges to 7** because ramp1's landing now coincides with ramp2's approach tile, dropping the intermediate walk step.
- `test_2d_bfs_turn_resets_momentum_before_ramp` — grid widened to 11 cols with 3 walls between ramp and landing instead of 2.
- `test_2d_bfs_reaches_wayward_east_chamber_via_ramp_chain` — phase-1 landing assertion updated from `(13, 17)` to `(14, 17)`.

Empirical end-to-end verification on `session31_wayward_cave_bike_ramps`:
- **Single ramp**: `navigate_to((14, 17))` from start (7, 22) lands exactly at (14, 17) ✓
- **Chain**: debug trace confirms ramp1 at `(9, 17)` and ramp2 at `(14, 17)` both fire in the same `navigate_to((31, 16))` call. Reaching (31, 16) itself is blocked on a wild encounter further east — unrelated to ramp mechanics and out of scope for this fix.

Full suite: **534 passed** in 13:33 (single-emu sequential run). New empirical spikes checked in as `scripts/spike_ramp_pos_sampling.py`, `scripts/spike_ramp_poll_release.py`, and `scripts/spike_ramp_chain_exec.py` per the `spike_before_redesign` memory.

### Commits

1. `fix(nav): poll-based bike ramp execution + correct landing tile` (40c6f41)

### Take-aways

- **The decomp citation was wrong, and only empirical evidence caught it.** Session 32 called out "decomp cites can match the wrong function; empirically verify mechanics in-emulator before shipping them" — and that lesson repeated itself here at one level deeper. The `JumpFartherEast` action text really is in the decomp; the tile-displacement constant we inferred from it didn't match the engine's actual landing. Future ramp-like mechanics: always run the release-at-entry spike across the actual regime before trusting a constant.
- **Continuous-hold vs discrete-action tension.** Held button through a discrete engine action (ramp jump) → bike fast-gear keeps running past the action's natural end → release-drift is a function of idle time, not a fixed overshoot. Release BEFORE the action triggers → the action plays out atomically → lands at the engine's chosen tile regardless of subsequent idle. For any engine-level "trigger + play-out" mechanic, release on entry and let the engine drive.
- **Poll-driven entry ≠ continuous hold.** My first instinct was "hold the button through the whole thing so the engine never sees a release." That pattern works for regular tile steps (the `step_hold` idiom) because the engine fully consumes one tile's worth of input and then stops. It does NOT work for ramp jumps because the engine has its own in-flight displacement action that responds to held input by continuing past the landing. Poll-driven entry + release-at-trigger is the right idiom for any primitive where the engine drives the motion after a threshold crossing.
- **End-of-path `WAIT_FRAMES` assumes per-tile step_hold semantics.** The 8f trailing settle was added for `step_hold`'s position-change-exit race (position updates at tile entry, animation completes a few frames later). For ramp-step endings, the 36f in-ramp idle already settles the jump fully — an extra 8f is pure drift. When adding new end-of-step primitives in the future, check whether the trailing settle is redundant or harmful.

## Dev Session: Momentum-aware BFS for bike-ramp chaining (2026-04-23 session 35)

Phase 3 of BUG-043. Session 34 landed the single-ramp runway check + fast-gear jump distance, but the geometric runway fallback couldn't model the chained-ramp case — where the landing from one ramp carries full momentum into the next, even across a 1-tile gap that wouldn't satisfy a fresh 3-tile-straight-line check. Session 34's spike had already confirmed the empirical chain (ramp1@10 → land 13 → walk 14 → ramp2@15 fires). This session wired that empirical fact into the BFS.

### Implementation

`pathfinding.py::_bike_ramp_landing`:
- `momentum` parameter semantic change: `None` (new default) = caller doesn't track momentum, use geometric fallback (unchanged behavior). `int` = caller tracks momentum, trust it — no geometric fallback. This closes a subtle mis-admit: momentum-aware BFS that reaches an approach tile via a turning path now correctly passes `momentum=0` and rejects the ramp, where the old `momentum=0` default would fall back to geometric and incorrectly admit.

`pathfinding.py::_bfs_reachable`, `_bfs_pathfind`, `_bfs_pathfind_level`, `_flood_fill_level`:
- BFS state augmented from `(x, y)` to `(x, y, last_dir, momentum)` where `last_dir ∈ {up, down, left, right, None}` and `momentum ∈ [0, RUNWAY]`.
- Same-direction step: `m' = min(m+1, RUNWAY)`. Direction change: `m' = 1`.
- Ramp approach passes `approach_m = m if last_d == direction else 0` — the turn-reset is explicit and the geometric fallback is disabled in these callers.
- Post-jump landing state: `(lx, ly, direction, RUNWAY)` — full carry-through per session-34 spike data. This is the chain-enabling edge.
- Visited set keyed on the full 4-tuple so each tile is explored with up to 4×(RUNWAY+1) = 20 distinct momentum contexts. Bounded and cheap on 32×32 chunks.
- `_bfs_pathfind_level` records ramp transitions on *first* tile discovery (via `tile_seen`) so the expanded state space doesn't inflate the transition map.

Impact on `_bfs_reachable_3d` / `view_map`: delegated through `_flood_fill_level`, so the 3D flood inherits chain-awareness for free.

### Tests

`tests/test_navigation.py::TestBikeRampBfsEdges`:
- `test_2d_bfs_chains_ramps_via_momentum_carry` — synthetic 16-col grid with two east ramps where the second ramp's geometric runway has a wall at the third back-tile. Pre-session BFS would reject the chain; momentum-aware BFS reaches landing2 and returns a 9-edge path.
- `test_2d_bfs_turn_resets_momentum_before_ramp` — 10×3 grid forcing a turn onto the ramp approach tile. Asserts the landing is NOT reached, confirming the turn-reset rule hasn't regressed now that the geometric fallback is off.
- `test_2d_bfs_reaches_wayward_east_chamber_via_ramp_chain` — integration test on `session31_wayward_cave_bike_ramps`. Asserts the east-chamber Pokéball at `(31, 16)` is reachable. Before: only `(13, 17)` was; after: `(13, 17)` + `(31, 16)`. The Pokéballs at `(22, 9)`, `(33, 8)`, and warp:0 at `(43, 38)` remain out of reach — they gate on additional ramps/puzzle elements beyond chain-awareness.

Full suite: **534 passed** (+3 new tests, zero regressions) in ~2:35.

### Commits

1. `feat(nav): momentum-aware BFS for chained bike ramps` (a5183c9)

### Take-aways

- The geometric-fallback → trust-the-caller transition via `None` sentinel was the cleanest way to keep the legacy test surface and unit-testable contracts intact while letting BFS be strict. A boolean flag would have worked too; the sentinel self-documents "I don't know momentum, please guess geometrically."
- State expansion 20× per tile sounds like a lot but at 32×32 chunks the visited set stays well under 20k entries and the full suite didn't get noticeably slower. Never optimized — dominance pruning (`best_m[(x, y, last_dir)]`) stays in reserve.
- Landing momentum `RUNWAY` (not 0) is the whole point: it says "after a ramp, you're at full speed in this direction, not resetting." Without it the chain doesn't exist, regardless of runway math.
- BUG-043's full closure needs the rest of the east-chamber ramps (and whatever puzzle the `(43, 38)` warp gates on) — but that's a gameplay exploration task now, not a BFS-tool task.

## Dev Session: Bike ramp fast-gear fix + runway check + fast-gear mount (2026-04-23 session 34)

Follow-up to session 33's sustained-hold primitive. Session 32's decomp dive + session 33's hold primitive had teed up BUG-043 (Wayward Cave B1F east chamber unreachable); this session closed the tool-side gap. Woj's brief: make the BFS aware that ramps need a few tiles of approach runway in the ramp direction, and that our playthrough always runs fast gear.

### Spike first (again)

`scripts/spike_ramp_runway.py` on `session31_wayward_cave_bike_ramps`. Methodology per `spike_before_redesign` memory: measure before redesigning.

Ran a sweep of start positions at y=17 with varying runway length, held right continuously, sampled position every 2 frames. Two false starts first:

1. **Teleport via `write_memory` on PLAYER_POS_BASE reverted on the next frame.** Writes to `+8` (tile_x) and `+12` (tile_y) land fine for one frame, then a third authority snaps them back. Writing the fx32 pixel pos at `OBJ_ARRAY_FPX_BASE` also didn't hold the engine's logical position. The truth source for tile coords is elsewhere — possibly the MapObject's script data, possibly a separate PlayerData field — and I didn't chase it because it wasn't on the critical path.
2. **`navigate_to` overshoots target tiles on fast bike.** `nav_to(5, 17)` from west-chamber (7, 22) lands at (4, 17) instead of (5, 17) because the sustained-hold primitive carries the bike past the target when the BFS plan is short. That's BUG-044, which we left open last session — relevant here because it made the spike's "set player to precise start position" phase fragile.

Final working setup: `nav_to(4, 17)` + 90f settle (known stable), then press right with `advance_frames_until(changed)` and 90f drain between tile-steps to reach the test start position on foot-like kinematics. Not perfect (each step leaks a bit of momentum into the next), but deterministic enough to sweep runway lengths 1-6 tiles.

**Findings** (ramp at game-x 10 on row 17):

| Approach tiles before ramp | Ramp fires? | Final |
|---|---|---|
| 0, 1, 2 | NO | approach tile |
| 3 | YES | (13, 17) after jump, chain stalls |
| 4, 5 | YES | (18, 17), chains into ramp 2 at (15, 17) |

- Fast-gear cold-start acceleration curve: **12 → 12 → 8 → 6 → 4 frames/tile**.
- Fast-gear ramp jump displacement: **approach + 4 tiles** (3 past the ramp). Matches decomp `MOVEMENT_ACTION_JUMP_FARTHER_EAST` (`src/unk_020655F4.c:994`, FX32_CONST(4) × 12f).
- Empirical: minimum runway = 3 approach tiles. Went with **4** in the BFS constant for cold-start safety margin — the fifth tile is the first at full-speed 4f/tile, and we'd rather over-restrict than fail mid-chain.
- Ramp chains: landing → 1 gap tile → next ramp still fires from carry-through momentum. Observed: ramp1 at 10 → land 13 → walk 14 → onto ramp2 at 15 fires → land 18.

### Implementation (phase 1 — single-ramp runway)

`nav_constants.py`:
- `BIKE_RAMP_JUMP_TILES 2 → 4`.
- New `BIKE_RAMP_RUNWAY_TILES = 4`.
- Docstring expanded with the decomp cite + empirical numbers.

`pathfinding.py::_bike_ramp_landing`:
- Added optional `momentum` arg (int, default 0) for momentum-aware BFS callers.
- When `momentum+1 < RUNWAY`, falls back to a **geometric check**: the `RUNWAY-1` tiles behind the approach tile in the ramp direction must be passable AND not direction-gated (no ledges, no directional warps) — since any of those would force a turn that breaks the straight-line hold.
- Landing now `approach + JUMP_TILES × dir` (was `approach + 2 × dir`). Skips the ramp tile and the one-tile wall that sits mid-jump on most layouts.

`navigation.py::_execute_path`:
- Ramp-step hold extended from `BIKE_HOLD_FRAMES + 24f` to `BIKE_HOLD_FRAMES + 36f` — spike observed entry→landing spans ~20 frames, so 40f covers it with margin.
- Path-scanner advances `BIKE_RAMP_JUMP_TILES` per ramp step (was hard-coded `+ 2`).

`tests/test_navigation.py::TestBikeRampBfsEdges`:
- Widened synthetic grids to 8 cols so the new runway check has room to test.
- New `test_ramp_landing_insufficient_runway` (wall in the runway → edge rejected).
- New `test_ramp_landing_momentum_override` (short geometric runway but `momentum=RUNWAY-1` supplied → edge admitted, chain-ready for phase 2).
- `test_2d_bfs_crosses_ramp_in_wayward_cave` updated: landing is now (13, 17) instead of (11, 17).

Full suite: **531 passed**.

### Implementation (phase 2 — fast gear on every mount)

Woj flagged the related concern: mounts don't currently enforce gear state, so we inherit whatever the last B-toggle left. Fast gear is the only gear we use deliberately.

`use_item.py::_flow_bicycle`:
- On a successful mount (transition to on-bike), read `BIKE_GEAR_STATE_ADDR`. If 1 (slow), press B once to toggle. Input-only — no memory writes (memory-write audit open from session 33 leaves that lane as the only one permitted for production tool code).
- Factored out as `_ensure_fast_gear(emu)` helper for reuse.

`navigation.py::_auto_mount_for_slope`:
- Calls `_ensure_fast_gear` when the player is already cycling (use_item path already handles fresh mounts). Closes the "already on bike in slow gear → slope traversal fails" hole.

Full suite: **531 passed, zero regressions** across the bike-touching tests (`test_cycling_road.py`, `test_navigation.py`, `test_bicycle.py`).

### Deferred (next session)

**Phase 3 — chain-aware BFS (task 6 from this session's task list).** Phase 1's geometric runway check doesn't admit a ramp edge when the approach tile has only a 1-tile straight-line backing (which is exactly the scenario between chained ramps). The empirical chain IS real — landing momentum carries the player through a subsequent ramp jump if they hold the same direction — but our current BFS can't see it. Concretely, Wayward Cave B1F east-chamber POIs (`obj:1/2/3` + `warp:0` at (43, 38)) are still `unreachable_interactibles`. BFS reaches `(13, 17)` (ramp-1 landing) and stops; the rest of the east chamber needs phase 3.

Design sketch (not implemented): augment BFS state with `(last_direction, momentum)` where momentum is capped at `BIKE_RAMP_RUNWAY_TILES`. Rules:
- Same-direction step: `momentum = min(m + 1, RUNWAY)`.
- Direction change: `momentum = 1` (the step into the new direction is its own first tile).
- Post-ramp-jump: `momentum = RUNWAY` (full carry-through per spike data).
- Ramp edge admitted iff `last_direction == ramp direction AND momentum >= RUNWAY - 1`.

State expansion per tile = 4 directions × (RUNWAY + 1) momenta = 20× — bounded, tractable. Affects `_bfs_reachable`, `_bfs_pathfind`, `_bfs_pathfind_level`, `_flood_fill_level` in `pathfinding.py`. The `momentum` arg on `_bike_ramp_landing` is already wired for this.

**Memory-write audit** (session 33 carry-over) — `cycling_road.py::_traverse_bike_slope` still uses `emu.write_memory(BIKE_GEAR_STATE_ADDR, 1, …)` before its B-toggle and again after slope traversal to drain momentum. Input-only replacements would need to replicate the "settle" effect the original comment calls out ("the B press is essential even when gear is already 0"). Separate concern from this session.

### Commits

1. `chore(spike): ramp runway + fast-gear jump distance measurement` (26d1876)
2. `fix(nav): bike-ramp fast-gear jump distance + runway requirement` (98e7e0d)
3. `feat(nav): always end bike mounts in fast gear` (3bbcf30)

### Take-aways

- Two spike false starts (memory-write teleport, nav-overshoot positioning) ate most of the first hour but were cheap relative to the alternative of building the fix on wrong assumptions. The final spike data — that 3 approach tiles suffice and 2 don't — is the kind of threshold you don't get from decomp alone.
- The "geometric runway" check is a coarse approximation of a direction-aware BFS state. It suffices for open corridors (most of the overworld) but can't reason about chained ramps. When we discovered phase 1 didn't unblock the east chamber, the right call was to stop, commit what works, and scope phase 2/3 for a dedicated session — not to try to land all three phases in one.
- Memory-write audit concerns (from session 33) made the gear-enforcement design mechanical: the only production-code path is read gear + press B. Sometimes explicit constraints simplify the work.

## Dev Session: Sustained-hold movement primitive (2026-04-22 session 33)

Architectural overhaul of the per-tile movement primitive in `_execute_path`. The old tap-and-wait pattern (`advance_frames(HOLD, buttons=[dir]) + advance_frames(WAIT)`) released the d-pad between tiles, which broke anything the engine needs sustained input for — bike ramps and bike slopes top the list. The new primitive holds the direction continuously across tile boundaries and exits per-tile on a memory-change condition.

Motivation: session 32b's bike-ramp empirical finding ("Ramps require continuous momentum, NOT a press-from-standing") implied the whole per-tile pattern was a dead end. Woj: "we need to try making all navigation be a matter of holding down buttons in a direction until we reach where we need to go".

### Spike first

`scripts/spike_hold_vs_tap.py` — four experiments across walking, slow bike, fast bike, and running (B+dir):

1. **Commit threshold**: how many frames of held input before a step commits? Walking/slow-bike: 6f. Fast bike: 7f. RAM position-coord updates at ~frame 11 on foot, ~frame 12 on fast bike.
2. **Back-to-back 5-tile runs** with varying 0f/1f/2f/4f release gaps between calls. Wall-clock total stays constant regardless of gap size — the engine's per-tile animation runs on a fixed clock whether or not the button is held. On fast bike the per-tile frames dropped from 12 → 4 across the run as the `playerAvatar->speed` (max 3) ramped.
3. **Release-at-change settle**: after `advance_frames_until` fires on pos-change, release for 0/1/2/4/8/16/32/64 frames and re-read. Walking + slow-bike settle cleanly on the tile; fast-bike's per-tile release also clean (hasn't accumulated multi-tile momentum yet).
4. **Momentum slide**: hold for N frames, release, advance 120f uninputted. Walking never coasts. Slow-bike rarely coasts. Fast-bike coasts 1-3 tiles after a long hold — confirmed Woj's suspicion about bike momentum.

`scripts/` retains the spike for future tuning. Three new save states (`spike_eterna_open_ground`, `spike_eterna_open_bike_slow`, `spike_eterna_open_bike_fast`) at (304, 542) in Eterna City outdoor — 7+ tiles of clearance in most directions, no NPCs, no encounters.

### Decomp on bike momentum

Sub-agent dig (`pokeplatinum/src/player_avatar.c` + `src/unk_0205F180.c`): momentum IS `playerAvatar->speed` (0-3), incremented +1/frame on press, decremented -1/frame on release (via `sub_020603EC`). `PlayerAvatar_ClearSpeed` would zero it instantly. But — per Woj — any memory write for momentum would look like cheating for the LLM streaming context, so this stays an input-only problem.

### Architecture decisions

- **Running Shoes (B+dir) is the walking default.** 2× faster per-tile (8f vs 16f), clean release, no momentum. Harmlessly falls back to walking indoors.
- **Bike is NOT the default for normal paths.** Only needed for upward bike slopes and bike ramps. Auto-mount is scoped to those specific cases.
- **For downward slopes** the engine auto-slides on foot; no bike needed. This was the biggest surprise of the session — the pre-step auto-mount was firing on *all* slope tiles, including descents, introducing unneeded momentum.
- **Per-tile primitive**: `nav_constants.step_hold(emu, direction, active_hold, aux_buttons)` does `advance_frames_until(cond=pos_changed, buttons=[dir, *aux], max_frames=hold*2+8)`.

### Implementation

Dropped per-tile cost from 24 frames (16 hold + 8 wait) to ~16 frames (the condition fires at RAM-update time and the next call absorbs any remaining animation). No measured per-tile-count improvement at the frame level — the engine's 16-frame walking animation runs end-to-end regardless — but the *engine-visible* behavior is a continuous hold, which is what bike ramps and slopes need.

Call sites:
- `nav_constants.py::step_hold` — new primitive.
- `navigation.py::_execute_path` — replaces the inner `advance_frames(hold) + advance_frames(WAIT)` pair. Adds "b" to buttons when `active_hold == HOLD_FRAMES` (walking).
- `navigation.py::_execute_path` pre-step slope-or-ramp check — only auto-mounts for `direction == "up"` on slopes (ascent) or for ramps (always).
- `navigation.py::_execute_path` post-step settle — `advance_frames(WAIT_FRAMES)` after step_hold when `pre_obs` is a slope tile, so the engine's slope-slide-back animation resolves before the blocked-check reads position.
- `navigation.py::_execute_path` end-of-path — short settle + verify we actually hit the BFS goal. If not, surface `stopped_early=True` with `blocked_reason="path_exhausted_before_target"`.
- `navigation.py::_execute_path` slope-success branch — after `_traverse_bike_slope` succeeds, dismount the bike via `use_item("Bicycle")` + `_try_repath` from the actual landing tile. Bike momentum off slope-top is otherwise unpredictable (overshoots by 1-3 tiles); re-BFS'ing on foot from where we actually landed is more reliable than trying to predict the exit.
- `navigation.py::_navigate_to_impl` adjacent-walk-in-warp check — skip when current position already matches the BFS goal (otherwise a grass/sign target near a warp gets shoved off-target by the warp-trigger press).
- `fishing.py::seek_encounter` — dismount BEFORE the pre-pacing nav (pacing requires foot), and honor `stopped_early` from nav to emit a clean "blocked" diagnostic instead of silently pacing from the wrong tile.

### Test updates

- `TestBug031BikeSlopeTraversalFailure` deleted — BUG-031 (Wayward Cave north-bound slope refuses traversal) is fixed by the new primitive. Sustained hold is what the slope needed all along.
- `test_close_target_overshoots_gracefully` → `test_close_target_near_slope_top` — the "overshoot" concept is obsolete under auto-dismount + repath. New test allows ±3 tiles of target tolerance when the target is on the slope boundary.
- `test_auto_mounts_bike_when_walking` + `test_walk_from_distance_auto_mounts` — dropped assertions that the player remains cycling after slope (we now dismount intentionally).

### Verification

Full suite: **529 passed in 2:33**. Zero regressions across 42 test files. Every nav-touching area (ledges, 3D elevation, HM obstacles, clock puzzles, cycling-road auto-slide, fishing, adjacent targets) stayed green through each iterative change.

### Commits

1. `feat(nav): replace per-tile tap with sustained-hold primitive` (2a77959) — 526 pass / 5 bike-slope fail, the latter expected as pre-existing per Woj's prediction.
2. `fix(nav): auto-dismount + repath after bike-slope traversal` (826d67a) — 528 pass / 1 fail (seek_encounter through slope).
3. `fix(nav): skip bike auto-mount on downward slope descent` (12b7c03) — 529 pass.

### Take-aways

- Don't implement a fix before an empirical spike when the engine's behavior matters. The spike's momentum-slide data (EXP5) told us which cases to worry about and made the nav design decisions mechanical rather than speculative.
- When one test fails after a cascade of fixes, stop and re-examine the premise before adding the next layer. Woj called this out and his pushback ("did we actually get off the bike after traversing the slope?") was the exact right question — my auto-dismount never fired for downward slopes because `_traverse_bike_slope` isn't called for them (engine auto-slides instead).
- Delegate decomp digs for mechanic discovery, not for design decisions. The agent finding `PlayerAvatar_ClearSpeed` was load-bearing data; it didn't dictate any code change because the streaming audit rules out memory writes.
- Bike is a niche tool under this architecture — only needed for upward slopes and ramps. Every other path runs on foot with Running Shoes. That's a simpler mental model for the nav layer and matches Woj's read of the game.

### Relevant for next session(s)

BUG-043 (gear-dependent ramp jump distance) is teed up: this session's continuous-hold primitive is the prerequisite for ramp traversal that needs momentum build-up. The BFS still uses the slow-gear jump model. Next ramp session can now add gear-dependent `_bike_ramp_landing`, and the `_execute_path` already holds direction continuously so ramp chains should work end-to-end. Open item filed in `project_tool_improvements.md` at current priority.

Memory-write audit is a separate (streaming legitimacy) concern, filed for a dedicated session. Several writes exist in `cycling_road.py::_traverse_bike_slope` that may need input-only replacements.

## Dev Session: LEDGE_DIRECTIONS decomp fix + BUG-043 root-cause (2026-04-22 session 32)

Parallel-dev session running against `.melonds_test_bridge.sock` while the playthrough agent drives `.melonds_bridge.sock` on its own story track. All probes in `/tmp`.

Goal: close out BUG-043 — the session-31b follow-up where four Wayward Cave B1F east-chamber POIs ((22, 9), (31, 16), (33, 8) Pokeballs + warp:0 at (43, 38)) remained in `unreachable_interactibles` on `session31_wayward_cave_bike_ramps` despite BUG-042 wiring bike-ramp BFS edges.

### Instrument before theorize

Per the memory rule, re-ran the 2D BFS with the widest possible input before theorizing about new mechanics. `_build_multi_chunk_terrain` applies a 5×5 chunk cap; I wrote `/tmp/probe_bug043_widen.py` to bypass that and BFS over the full 64×64 map terrain grid. Result: **172 tiles reached, identical to the viewport-bounded run** — confirms the problem isn't narrow input (instrument_before_theorize rule), it's genuine disconnection under our BFS model. Of the 10 bike ramps on the map, only (10, 17) has a reachable approach tile; every other ramp's approach sits in a walled-off chamber.

### Root cause via decomp warp analysis

Read `ref/pokeplatinum/res/field/events/events_wayward_cave_b1f.json` + `events_wayward_cave_1f.json`. The B1F has **two warps** both linking back to 1F: (43, 38)↔1F(55, 54) and (16, 40)↔1F(28, 54). The east-chamber POIs can only be reached by walking from (7, 22) to warp:1 at (16, 40), warping to 1F at (28, 54), walking on 1F to (55, 54), re-entering B1F at (43, 38). That re-entry tile lands the player in the east chamber with direct access to all four POIs. Our `navigate_to` BFS is single-map — it fundamentally can't plan that round trip.

Filed as **FR-010 cross-map BFS** in the backlog (not a BUG-043 fix — the BFS correctly reports the POIs unreachable *within one map*, which is what the tool guarantees). BUG-043 closed as "cross-map by design".

### Bonus: LEDGE_DIRECTIONS decomp-mismatch fix

While enumerating terrain features I found **39 tiles of 0x3B** (row 22 cols 11–35, plus smaller clusters) and discovered our mapping was rotated 90°.

`ref/pokeplatinum/include/constants/field/map_tile_behaviors.h` lines 67-70:
```
TILE_BEHAVIOR_JUMP_EAST  = 0x38
TILE_BEHAVIOR_JUMP_WEST  = 0x39
TILE_BEHAVIOR_JUMP_NORTH = 0x3A
TILE_BEHAVIOR_JUMP_SOUTH = 0x3B
```

Confirmed by the switch in `src/unk_0205F180.c:1772-1793`:
```
case DIR_NORTH: if (TileBehavior_IsJumpNorth(t)) return TRUE;
case DIR_SOUTH: if (TileBehavior_IsJumpSouth(t)) return TRUE;
case DIR_WEST:  if (TileBehavior_IsJumpWest(t))  return TRUE;
case DIR_EAST:  if (TileBehavior_IsJumpEast(t))  return TRUE;
```

Our `LEDGE_DIRECTIONS` had `{0x38: "down", 0x39: "up", 0x3A: "left", 0x3B: "right"}` — the correct mapping is `{0x38: "right", 0x39: "left", 0x3A: "up", 0x3B: "down"}`.

Why no existing test caught it: Gen 4 ledges are sparse in the routes we've been QAing. The Wayward Cave B1F row-22 mass of 0x3B was the first dense-ledge grid we BFS'd, and even there the rotated mapping happened not to affect reachability for any tile the existing tests checked (ledge approach tiles are walled off anyway under both mappings).

### Fix

Four sites in two files, all mechanical swaps:
- `renegade_mcp/nav_constants.py:44` — `LEDGE_DIRECTIONS` dict rewritten, with a decomp cite comment.
- `renegade_mcp/nav_constants.py:257` — `_DIAG_CHAR` glyphs: `0x38:'>', 0x39:'<', 0x3A:'^', 0x3B:'v'` (arrow points in the jump direction).
- `renegade_mcp/map_state.py:58` — `BEHAVIORS` human labels: `0x38:"ledge_E", 0x39:"ledge_W", 0x3A:"ledge_N", 0x3B:"ledge_S"`.
- `renegade_mcp/map_state.py:1010` — `_BEHAVIOR_CHAR` render glyphs: same arrow convention as `_DIAG_CHAR`.

Added `TestLedgeDirections` in `tests/test_navigation.py` — three tests: (1) `LEDGE_DIRECTIONS` equals the decomp-derived dict, (2) BFS crosses a `0x3B` JUMP_SOUTH ledge with a south step, (3) BFS rejects the north-approach (wrong direction).

### Verification

`tests/test_navigation.py` + `test_map_tools.py` + `test_3d_nav_fallback.py`: **91 passed** in 76s. Full suite (`pytest tests/`): **528 passed in 2:29** (525 pre-fix + 3 new). Zero regressions across 42 test files.

### Take-away

"Instrument before theorize" paid for itself immediately — the cross-map topology was visible from one `jq` on two decomp JSONs once the widest-input BFS confirmed the single-map dead-end. The LEDGE_DIRECTIONS find was a bonus from reading the same decomp headers that pinned the ramp mechanic in session 31b; each trip back to the decomp keeps finding pre-existing bugs that were quietly surviving because no scenario tripped them. The ledge fix is small but shrinks the surface area where `navigate_to` could silently route into a wall — worth the lock-step update anytime a new direction-gated tile behavior gets added.

## Dev Session: BUG-043 re-investigation — bike ramp jump is gear-dependent (2026-04-22 session 32b)

Correction to the session-32 conclusion above. After Woj pushed back on the "cross-map by design" framing (his observation: "none of the ramp landing spots are showing as reachable in the overlay" + "the other 2 Pokéballs should be perfectly doable if BFS properly takes into account ramps"), a sub-agent decomp verification + empirical ramp test in-emulator overturned the prior session's (and session 31b's) claim about ramp jump distance.

### What session 31b got wrong

Session 31b cited `MovementAction_JumpFarEast_Step0` (`src/unk_020655F4.c::~970`) with `InitJump(DIR_EAST, FX32_CONST(2), 16, ...)` → 2-tile displacement from the entry tile. That is NOT the action a bike ramp invokes.

### What actually happens (sub-agent decomp + empirical confirmation)

1. When the cycling player **steps into** a 0xD7 tile, the normal walk movement carries them onto the ramp tile (not a jump — just a regular step).
2. On the next tick, while **standing on** the ramp, `src/unk_0205F180.c::sub_0205F95C` (lines 613-629) consults `cyclingGear` and dispatches:
   - gear **1** (fast, default) → `MOVEMENT_ACTION_JUMP_FARTHER_EAST` (0x5f). Params at `src/unk_020655F4.c:994`: `FX32_CONST(4)`, duration 12. Step-count rule (init + one `StepDir` per full FX32_CONST(16) accumulated by `MovementAction_Jump_Step1` at 817-871): **3 tile displacement past the ramp** = lands at `ramp + 3·dir`.
   - gear **0** (slow) → `MOVEMENT_ACTION_JUMP_NEAR_SLOW_EAST` (0x5d). Params at 982: `FX32_CONST(1)`, duration 16. **1 tile past the ramp** = lands at `ramp + 1·dir`.

From (7, 22) approaching ramp (10, 17) via entry (9, 17):
- Fast gear: walk → (10, 17) → jump → **(13, 17)**.
- Slow gear: walk → (10, 17) → jump → (11, 17) ← this is what our `_bike_ramp_landing` currently models.

Our `BIKE_RAMP_JUMP_TILES = 2` (entry + 2·dir = ramp + 1·dir) is the slow-gear model. Default bike state is fast gear, so the BFS has been wrong for the common case.

### Empirical verification

`/tmp/verify_ramp_jump6.py`: loaded `session31_wayward_cave_bike_ramps`, dismounted, walked on foot to (4, 17), mounted bike (auto-gear 1), held right continuously across 10×20-frame chunks. Final position: **(14, 17)** — two tiles past the next ramp's approach. That trajectory requires the jump to land at (13, 17); walking east from (11, 17) would hit the wall at (12, 17) and stop. The wall is mid-jump and skipped (the jump action does not collision-check intermediate tiles — it invokes `StepDir` mechanically for 4 tiles).

Additional finding during empirical testing: a **standing-start** press east from (9, 17) on a fast-gear bike did NOT trigger the ramp (player didn't move across 80 frames of hold). Continuous movement from further west DID trigger it. This mirrors bike slope (0xD9/0xDA) behavior where continuous momentum is required. Our `_execute_path` currently emits per-tile discrete presses; for ramps, it may need to detect the ramp sequence and emit a single held-direction input.

### What this means for BUG-043

The earlier "cross-map by design" conclusion for BUG-043 is **wrong**. The east-chamber POIs at (22, 9), (31, 16), (33, 8) are reachable single-map once the correct ramp model is in place: the row-17 ramp chain (10→13, 15→18, 20→23, 26→29) closes the corridor that the slow-gear model can't. Cross-map routing (FR-010 in the session-32 version of the backlog) is removed — the chamber-connectivity problem was a pathfinding bug, not a topology limitation.

### Scope decision

No code fix this session. The correct fix requires (a) gear-dependent jump distance in `_bike_ramp_landing`, (b) `_execute_path` changes to handle continuous-momentum ramp sequences like slope traversal, and (c) end-to-end regression tests actually routing through the east chamber. Each of those has non-trivial interactions with existing code — worth a dedicated session. Filed as reopened BUG-043 in the backlog with the empirical repro + decomp cites.

The LEDGE_DIRECTIONS fix (session 32a) stays — it's independent and was validated by the full test suite.

Per Woj's read: "This may be something to leave as an entire session's investigation in and of itself." Agreed.

### Take-aways

- Session 31b's take-away ("decomp reads paid for themselves") was half right. One decomp sighting with a plausible match is not enough — the sub-agent's more careful re-read found a DIFFERENT movement action path we missed. Empirical verification via test emulator would have caught this in 31b; the original session deferred it because an initial walk test got stuck on a black screen. That was a mistake.
- Woj's visual read of the grid dump beat my reach-set arithmetic. When a human pattern-matches an obviously-wrong layout (10 ramps with only 1 landing reachable), listen.
- Reach-set overlays are more useful than abstract unreachable counts. The overlay made the "none of the ramps chain" pattern visible; the count-based report had framed it as "3 POIs unreachable, priority medium."

## Dev Session: Bike ramp BFS edges + auto-mount traversal (2026-04-22 session 31b)

Second half of the session 31 dev pair, running in parallel with the playthrough agent on `.melonds_bridge.sock`. Standalone test emulator on `.melonds_test_bridge.sock`; all probe scripts in `/tmp`.

Player agent handoff: save state `session31_wayward_cave_bike_ramps` (Wayward Cave map 285, player at (7, 22) facing up). `view_map` legend listed `?=bike_ramp_E` but emitted no `?` glyph in the grid — ramps rendered as generic `#` walls, and four east-side POIs (Pokeballs at (22, 9), (31, 16), (33, 8) and warp:0 at (43, 38)) all sat in `unreachable_interactibles` with BFS distances equal to Manhattan (no partial path). Same pattern Woj predicted would be nasty.

### Mechanic (from decomp)

Spent the first half of the investigation reading `ref/pokeplatinum/` to pin down the ramp jump exactly:

- `include/constants/field/map_tile_behaviors.h`: `TILE_BEHAVIOR_BIKE_RAMP_EASTWARD = 0xD7`, `TILE_BEHAVIOR_BIKE_RAMP_WESTWARD = 0xD8` (no N/S variants in Gen 4 Platinum). Distinct from bike *slopes* at 0xD9/0xDA which are the Cycling Road / Wayward Cave slope mechanic already handled by `_traverse_bike_slope`.
- `src/unk_0205F180.c::sub_02060EE4`: the trigger — if `param2 == 3` (east) and the neighbor tile is `BikeRampEastward`, or `param2 == 2` (west) and the neighbor is `BikeRampWestward`, return 1. Approach direction must match the ramp's facing; wrong-direction approaches just bump into the blocked tile.
- `src/unk_020655F4.c::MovementAction_JumpFarEast_Step0`: `InitJump(mapObj, DIR_EAST, FX32_CONST(2), 16, ...)`. `MovementAction_Jump_Step1` accumulates `FX32_CONST(2)` per frame for 16 frames and fires `MapObject_StepDir` every time the accumulator crosses `FX32_CONST(16)` — net **2 tile displacement** from the entry tile over 16 frames. Landing = entry + 2 × (dx, dy), so the ramp tile itself is skipped.
- Cycling is required (`PlayerAvatar_GetPlayerState == PLAYER_STATE_CYCLING`), but gear level doesn't gate the trigger — just being on the bike. Decomp line 1172 of `sub_0205F180.c` explicitly *blocks* gear-switching while on a ramp tile, which is the only hint that gear might matter. Confirmed with Woj: the mechanic works at any gear as long as the bike is mounted.

Ramp tiles in our save-state map (`session31_wayward_cave_bike_ramps`, Wayward Cave B1F):

- 13 × 0xD7 (east jump) — rows 6/10/17 forming the east-chamber traversal sequence
- 3 × 0xD8 (west jump) — row 8/9/13 return paths
- 4 × 0xD9/0xDA bike slopes — col 7 rows 8/9, 26/27, 37/38 (existing slope traversal handles these)

Every ramp sits in a `[passable] → [ramp] → [passable] → [wall] → [passable]` pattern, so the 2-tile jump lands the player on the floor tile past the ramp, with the wall past that preventing further east motion without another ramp. Chained traversal is required to cross chambers.

### Fix

All edits in `renegade_mcp/`:

- **`nav_constants.py`** — `BIKE_RAMP_BEHAVIORS = {0xD7, 0xD8}`, `BIKE_RAMP_DIRECTIONS = {0xD7: "right", 0xD8: "left"}`, `BIKE_RAMP_TYPES = {"bike_ramp"}`, `BIKE_RAMP_JUMP_TILES = 2`.
- **`pathfinding.py::_bike_ramp_landing`** — new pure-function helper. Given `(x, y, direction, dx, dy, width, height)`, returns the 2-tile landing tile if the neighbor is a matching-direction ramp AND the landing is in-bounds + passable, else None. Doesn't check bicycle state — BFS assumes bike availability and navigate_to handles mounting at execution time, mirroring how Surf/Rock Climb treat badge-gated skills.
- **`pathfinding.py`** BFS integration — `_bfs_reachable`, `_bfs_pathfind`, `_bfs_pathfind_level`, `_flood_fill_level` all get a new branch: when the neighbor step hits an impassable tile, consult `_bike_ramp_landing`. If it returns a landing, enqueue the landing as a single-direction jump edge (one direction string emitted for the 2-tile displacement). In the 3D variants the landing is level-validated against `current_level` so a ramp whose landing sits on a different BDHC level is correctly rejected.
- **`map_state.py`** — `0xD7 → '>'`, `0xD8 → '<'` in `_BEHAVIOR_CHAR`. Ramps now render with directional glyphs plus legend entries, so view_map output visually distinguishes them from walls.
- **`navigation.py::_execute_path`** — pre-step auto-mount: when `pre_obs.type in (BIKE_SLOPE_TYPES | BIKE_RAMP_TYPES)` and the player isn't cycling, reuse `_auto_mount_for_slope` to press Bicycle. If mount fails (no Bicycle in bag), return `blocked_reason="bike_ramp_requires_bicycle"` with a clear "get the Bicycle and retry" note. After mount, the press hold is `BIKE_HOLD_FRAMES + 24f` to cover the 16-frame jump animation plus settle, and the slow-terrain retry loop is **skipped** for ramp steps — a retry after a successful jump would re-press the direction and push the player one tile past the landing.
- **`navigation.py`** path-scanner — the bike-slope population loop at `exec_obstacle_tiles` was iterating the BFS path tile-by-tile with `sx += sdx`. That breaks for ramp steps where one direction advances 2 tiles. Rewrote the loop: for each `step_dir`, inspect the next tile; if it's a ramp matching the direction, register `{"type": "bike_ramp", "behavior": nbeh}` at the ramp tile and advance `sx, sy` by `2*(sdx, sdy)` (to the landing); otherwise advance by 1 and run the existing bike-slope check.

### Path encoding choice

Considered two ways to represent ramp jumps in the BFS path:
1. Emit two direction entries `['right', 'right']` and let `_execute_path` detect tiles_moved==2 to consume both, mirroring how multi-tile Rock Climb / Waterfall paths are handled.
2. Emit one direction entry `['right']` per ramp, treating the jump as a single move (one engine press).

Picked (2). Rationale: the engine really does interpret the input as a single movement action — one press triggers the full 2-tile `JumpFar` action — so matching that semantics keeps the path length equal to the number of presses the executor issues. This means `steps_taken` reflects actions, not tiles, and the `summarize_path` summary renders as e.g. `r1` for a single ramp hop. The path-scanner compensates by advancing its position tracker by 2 tiles across ramp entries so subsequent tile-based checks (slope detection, HM obstacles) see the correct player position.

### Verification

`_bike_ramp_landing` unit tests with synthetic terrain:
- east ramp with passable landing → returns `(2, 0)`
- wrong-direction approach (moving west into a ramp_E) → returns `None`
- ramp with impassable landing → returns `None`

Save-state test against `session31_wayward_cave_bike_ramps`:
- 2D `_bfs_reachable` from player (7, 22) now reaches (11, 17) — the landing tile for ramp at (10, 17) — via the new ramp edge. Pre-fix this tile was walled off.
- Companion `TestBug038UnderBridgeReachability` + `TestUnderBridgePathfind3d` from session 31a still green.

Full regression sweep: **96 passed** across `test_navigation.py`, `test_map_tools.py`, `test_3d_nav_fallback.py`, `test_qa_bug017_clock_navigation.py` in 81s. Commit `390adf0`.

### Known follow-up (filed as BUG-043 in backlog)

The four east-chamber POIs in the repro save still sit in `unreachable_interactibles`. Ramp edges work correctly *per ramp* — the 2D BFS from (7, 22) reaches 172 tiles including `(11, 17)`, and probe scripts confirm `_bike_ramp_landing` fires for every 0xD7/0xD8 in the cave with a passable landing. The chambers are genuinely disconnected *without chained ramp+slope traversal through specific sequences* that the current BFS can't reconstruct. Likely contributors:

- Some approach tiles for ramps further east (e.g. the entry tile (14, 17) for ramp at (15, 17)) are in chambers reachable only by chaining through *other* ramps first. The BFS handles chains naturally via its work queue, but only if each approach tile is reachable from the expanding frontier. When the first ramp lands on a tile that's a dead end (wall to the east), the next ramp in the chain is unreachable from that side and the BFS can't find it.
- Row 22 ledges (`0x3B` jump-east ledges spanning x=11..35) only accept movement direction "right", so they're not usable as north-south connectors. They likely ARE usable as east-stretching connectors starting from the main corridor, but the approach tile (7, 22) is the player's starting tile and the tiles east of it (cols 8-10) are walled.
- The col 7 bike slopes at rows 26/27 and 37/38 do transition levels (multi-level flat plates with no BDHC data), and the BFS reaches the row-23-24 wide corridor (cols 11-35) through them. But the row-17 corridor (containing the first 4 ramp landings) only connects to that southern corridor via unknown routing.

Not attempted this session — the remaining work is topology instrumentation (walk the map with a human-driven player, log the actual traversal sequence the game expects) not BFS algorithmics. The ramp-edge work ships as-is and covers every individually-usable ramp; chamber connectivity is filed separately.

### Also noted (unrelated, not fixed)

Player agent flagged that `_traverse_bike_slope` mis-reports positions when auto-traversing a slope: "started at (7, 39) with target (7, 25); final was (7, 22) (3 past target); start was misreported as (7, 28); path: 'up x3' despite actual ~17-tile excursion across both slopes." Distinct code path from the ramp work (slopes use continuous-hold traversal, ramps use one-press animation). Filed as QA BUG-044 — worth a look next session when someone's running slope traversal.

### Take-away

Decomp reads paid for themselves again. Once `MovementAction_JumpFar_Step0` was in hand with its `FX32_CONST(2), 16` pair the mechanic was fully specified (2-tile jump, 16 frames, direction must match). That let me skip the empirical verification step — the initial `/tmp/verify_ramp3.py` walk-and-test attempt got stuck at (7, 19) with a black screenshot, and rather than re-debug the recording stall I trusted the decomp and moved to implementation. Got tripped up later by the topology debug (spent ~40 minutes confirming the map really is disconnected without further mechanics) but ultimately that confirms the fix is correct for ramps-specifically; the unresolved connectivity is a separate layer of work.

Chamber connectivity stayed scoped-out per the decision to ship the mechanically-correct core. Filing it as a standalone backlog entry with actionable starting points (probe-log a real playthrough traversal, check whether certain chambers need map transitions, investigate ledge-chain routing) is more valuable than continuing to debug in this session.

## Dev Session: navigate_to elevation-aware 3D pathfind under bridge (2026-04-22 session 31a)

First half of a two-fix dev pair running in parallel with a live playthrough agent on `.melonds_bridge.sock`. All work against `.melonds_test_bridge.sock`, no MCP-level reloads on the playthrough process.

Playthrough agent reported that `view_map` (post-BUG-040) correctly marks warp:7 — the east Wayward Cave entrance under the Cycling Road bridge — as reachable from under-bridge position (310, 608), but `navigate_to(poi="warp:7", flee_encounters=True)` still reports the warp unreachable. BUG-040 only touched `view_map`'s hierarchical reachability pass (`_flood_fill_level`, `_bfs_reachable_3d`); the navigate_to pathfind variants were left with the pre-BUG-040 `_tile_on_level` semantics.

### Root cause

`pathfinding.py::_bfs_pathfind_level._tile_on_level` — the single-level BFS that navigate_to uses when 3D routing is in effect — had the old early-return logic:

```python
def _tile_on_level(tx, ty, level):
    key = (tx, ty)
    if key in ramp_tiles:
        ri = ramp_tiles[key]
        if level in (ri["from_level"], ri["to_level"]):
            return True
        return _steppable(ri["from_level"]) or _steppable(ri["to_level"])  # early return
    if key in level_map:
        ...
```

On Route 206 under the Cycling Road, many ground tiles carry BOTH a bridge-ramp plate (overhead) AND a ground flat plate (underfoot) at the same XY. The early return after the ramp branch meant that for player_level=1 (ground), a tile whose ramp plate was from=14/to=12 answered "not on level 1" without ever consulting the flat plate — even though the ground plate at the same XY explicitly includes level 1. So every under-bridge-ramp ground tile looked like a wall to level-1 BFS.

`_flood_fill_level` already had the permissive fix from BUG-040: check both ramp plate and flat plate independently, accept if either permits the level. `_bfs_pathfind_level` was missed, and so was `_validate_path_elevation` (which has a structurally similar "check ramp, continue; then check flat plate" pattern — same bug class one layer deeper).

### Fix

All edits in `renegade_mcp/pathfinding.py`:

- **`_bfs_pathfind_level._tile_on_level`** — port the `_flood_fill_level` pattern directly: check `ramp_tiles.get(key)` and `level_map.get(key)` independently; if either source permits `level` (by membership or by `_steppable()`), accept the tile. Fall through to the permissive no-data case only when both are `None`.
- **`_validate_path_elevation`** — rewrote the per-step level logic to compute a `next_levels` set from the ramp plate AND flat plate independently (instead of `if ramp: ...; continue; if lvls: ...`). The 2D-fallback path validator now matches the hierarchical BFS's tolerance of multi-plate tiles. This is a defensive fix — the 3D pathfind normally succeeds now, so the 2D-fallback validator isn't on the hot path for this repro, but the same bug class would bite other bridge-overlap maps.

### Verification

Wrote `/tmp/repro_warp7.py` to exercise the BFS stack in isolation against the existing save state (`session30_route206_under_bridge`). Before the fix: `view_map._bfs_reachable_3d` reached warp:7 on player level, `navigate_to._bfs_pathfind_3d` returned `None`, `_bfs_pathfind_level` on level 1 found no direct path and only reached a distant bridge-ramp (wrong direction). After the fix: `_bfs_pathfind_3d` returns a 26-step path on level 1, matching view_map's reported 26 steps exactly.

Counter-check `/tmp/repro_bridge_blocked.py`: bridge-level Cyclist at (304, 631) remains unreachable from the ground — the permissive `_tile_on_level` rewrite doesn't accidentally let the ground player path UP onto the bridge.

New test class `TestUnderBridgePathfind3d` in `tests/test_navigation.py` with two assertions:
1. `_bfs_pathfind_3d` finds a ground-level path from under-bridge (310, 608) to warp:7 at (299, 611).
2. The same BFS correctly returns `None` for the bridge Cyclist at (304, 631) — regression guard so the fix doesn't cascade into false positives.

Full nav/map sweep: **86 passed** across `test_navigation.py`, `test_map_tools.py`, `test_3d_nav_fallback.py`, plus the auxiliary `test_qa_bug017_clock_navigation.py` (5 passed). Commit `1b7915e`.

### Take-away

BUG-040 was fixed as three separate defects in `view_map`'s reachability, but the companion navigate_to code path had the same pattern that should have been cleaned up in the same pass. Lesson for future bug-cluster fixes: when the fix is "replace early-return logic with independent-source checks on a common primitive", grep for that primitive across the module and apply the pattern everywhere — not just the call site in the repro.

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

