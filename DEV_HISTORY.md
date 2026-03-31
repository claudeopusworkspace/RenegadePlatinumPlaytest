# Dev History

Chronological log of tool development, bug fixes, and MCP improvements — separate from gameplay in GAME_HISTORY.md.

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
