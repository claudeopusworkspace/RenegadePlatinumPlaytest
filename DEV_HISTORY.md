# Dev History

Chronological log of tool development, bug fixes, and MCP improvements — separate from gameplay in GAME_HISTORY.md.

Older entries (2026-04-14 and earlier) live in [DEV_HISTORY_ARCHIVE.md](DEV_HISTORY_ARCHIVE.md).

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

