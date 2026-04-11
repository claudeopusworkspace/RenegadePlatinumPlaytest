# Pokemon Renegade Platinum Playtest

You are playtesting the melonDS MCP server by playing Pokemon Renegade Platinum (a difficulty/QoL hack of Pokemon Platinum by Drayano).

## Getting Started

1. Call `init_emulator` to initialize melonDS.
2. Call `load_rom` with path `/workspace/RenegadePlatinumPlaytest/RenegadePlatinum.nds`.
3. Load a save state if one exists (e.g., `load_state("living_room")`).
4. If no save state, you'll need to advance through the intro (~8000 frames) to reach the title screen.

## Save States

See [SAVE_STATES.md](SAVE_STATES.md) for the full save state table (60+ entries).

## Battery Save Files (.sav)

melonDS associates battery saves with the ROM filename. `RenegadePlatinum.sav` is the active battery save used when the game boots cold (no save state loaded).

**Multiple save files**: We have two save files:
- **Our playthrough** — lives entirely in save states (`.mst`). The battery save on disk doesn't matter for it.
- **Wayne's E4 save** (8 badges, endgame) — backed up read-only at `saves/e4_wayne.sav`. Three save states created from it: `e4_pokemon_league_lobby`, `e4_pokemon_league_fly_ready`, `e4_pokemon_league_outdoor`.

**Importing a different .sav**: `backup_save_import` writes the file to disk, but the emulator must be told to reload it:
1. Call `backup_save_import(path)`
2. Call `load_rom` to force a fresh boot from the new battery save
3. Advance through the title screen + adventure log (~8000+ frames, press A/Start to skip)
4. **Do NOT just load a save state after import** — save states contain the full RAM from when they were created, so they'll use the old data regardless of what battery save is on disk.

**Heap address delta**: Different save files (and even different boots of the same save) produce different heap address deltas. `detect_shift()` scans a range automatically. When switching between save states from different saves, call `addresses.reset()` + `detect_shift(emu)` to re-detect. In tests, use `do_load_state(emu, name, redetect_shift=True)`.

**Protecting external saves**: Store imported saves in `saves/` (gitignored) and `chmod 444` them. The emulator only writes to `RenegadePlatinum.sav`, so files in `saves/` won't be overwritten.

## Adding New Tools

All state-changing tools (anything that presses buttons, advances frames, or writes memory) **must** use the `@renegade_tool` decorator (`renegade_mcp/tool.py`). This automatically handles:

1. **Checkpoint creation** — saves emulator state before the tool runs, with an action string auto-built from the function name and non-default args (e.g. `navigate_to(x=15, y=8)`).
2. **Frame profiling** — records start/end frame counts and wall-clock time, appended to `logs/frame_usage.jsonl`.

Pattern in `server.py`:

```python
@mcp.tool()
@renegade_tool
def my_tool(arg1: str, arg2: int = 0) -> dict[str, Any]:
    """Docstring."""
    from renegade_mcp.my_module import impl
    emu = get_client()
    return impl(emu, arg1, arg2)
```

Read-only tools (pure memory reads like `read_party`, `read_battle`, `read_bag`) use bare `@mcp.tool()` — they don't advance frames and don't need checkpoints or profiling.

Checkpoints share a unified ring buffer (300 slots) with the melonDS MCP's own checkpoints. One checkpoint per tool call is the right granularity — don't checkpoint inside helper functions. Sub-tools like `auto_grind` may create additional internal checkpoints for per-encounter granularity.

## Navigation

**CRITICAL: Do not rely on screenshots for spatial reasoning in the overworld.** The isometric/overhead camera makes it very difficult to judge tile positions, room boundaries, and exits from pixel images. Instead:

- **Use `view_map`** to get a full map with terrain, player, NPCs, and **warp destinations** — all read live from the emulator. The `warps` list shows every door/stair exit with its destination name and tile coordinates.
- **Use warp coordinates from `view_map` with `navigate_to`** to enter buildings — the (x, y) from a warp entry can be passed directly to `navigate_to` for seamless transitions.
- **Use `navigate` or `navigate_to`** to walk paths — they verify each step and stop on collision. `navigate` auto-trims paths at door/stair transitions. `navigate_to` auto-enters adjacent walk-into doors (0x69, 0x6E). **`navigate_to` auto-clears Rock Smash rocks, Cut trees, and Surfs across water** when the obstacle path is shorter — returns `obstacles_cleared` in the response. Surf requires the Fen Badge + a party Pokemon with Surf; movement speed auto-adjusts to 8f/tile while surfing.
- **When stuck navigating, ask Michael for visual help** rather than brute-forcing positions.
- Screenshots are fine for reading dialogue, menus, and battle screens — just not for spatial navigation.
- **Position dicts** (start/final in navigate responses) include full map name info (`map_id`, `name`, `display`, `code`, `room`) instead of a bare map ID. No need to call `map_name` separately.

Multi-chunk maps (overworld, large caves) use a matrix/chunk system detected automatically by `view_map` and `navigate_to`. See MEMORY_MAP.md for collision data format, tile behaviors, and dynamic object details.

**Cycling Road (Route 206)**: Bridge body tiles (0x71) force the player to slide south at ~4f/tile when on the bicycle. `navigate_to` auto-detects this (tile behavior + cycling state + path scan) and uses position-tracking instead of step-counting: south = passive slide, north = continuous UP hold (~8f/tile), lateral = 4f press with south drift. `navigate` (manual) refuses with a clear error. Encounter detection runs during all movement phases. The bridge renders as `n` in `view_map`.

## Battle Workflow

### Automated (preferred)
1. **`read_battle`** — check enemy species, types, ability, stats, moves. Plan tactics. Returns all 4 battlers in double battles. Use **`type_matchup`** to check effectiveness before committing.
2. **`battle_turn(move_index=N)`** — use a move (0-3). **Checks type effectiveness first** — returns `EFFECTIVENESS_WARNING` if the move is immune or not very effective against the target. Call with `force=True` to proceed anyway (e.g., status moves, chip damage, or when no better option). Returns battle log + final state + updated battle state.
   - Or **`battle_turn(switch_to=N)`** — switch to party slot N (0-5) instead of attacking.
   - Or **`battle_turn(run=True)`** — attempt to flee a wild battle. Returns `BATTLE_ENDED` on success, `WAIT_FOR_ACTION` on failure (enemy gets a free turn).
   - In **double battles**, add `target=` to specify the target: `0`=first enemy (slot 1), `1`=second enemy (slot 3), `2`=self/ally. Default `-1` auto-targets first enemy.
   - Works on the very first turn of battle — no need to call twice.
3. Handle the returned state:
   - `EFFECTIVENESS_WARNING` — move is immune or not very effective. Review the warning, then either pick a different move/switch, or call `battle_turn(move_index=N, force=True)` to use it anyway. No game state has changed yet.
   - `WAIT_FOR_ACTION` — next turn, call `battle_turn` again. Battle state is included in the response.
   - `WAIT_FOR_PARTNER_ACTION` — double battle: first Pokemon's action submitted, call `battle_turn` again for second Pokemon.
   - `SWITCH_PROMPT` — trainer sending next Pokemon. Call `battle_turn(switch_to=N)` to swap, `battle_turn()` to keep battling, or `battle_turn(move_index=N)` to decline the switch and use that move in one call.
   - `FAINT_SWITCH` — your Pokemon fainted (wild battle). Call `battle_turn(switch_to=N)` to send replacement, or `battle_turn()` to flee.
   - `FAINT_FORCED` — your Pokemon fainted (trainer battle). Call `battle_turn(switch_to=N)` to send replacement (required).
   - `MOVE_BLOCKED` — move was rejected by Torment, Disable, Encore, Taunt, or Choice item lock. No turn consumed, automatically backs out to main action menu. Pick a different move or switch.
   - `BATTLE_ENDED` — back in overworld. **Auto-advances post-battle dialogue** (trainer defeat text, story triggers) if present — returned as `post_battle_dialogue` list. **Handles full party wipe**: auto-advances through blackout sequence + Nurse Joy dialogue, returns with `blackout: true` and player free in Pokemon Center. No manual `read_dialogue` needed.
   - `MOVE_LEARN` — Pokemon wants to learn a new move. Response includes `move_to_learn` (the new move name, read directly from memory) and `current_moves` with slot indices. Call `battle_turn(forget_move=N)` to forget move N (0-3) and learn the new move, or `battle_turn(forget_move=-1)` to skip. Works in both trainer and wild battles.
   - `NO_ACTION_PROMPT` — action prompt never appeared (~30 sec timeout). Game may need manual input.
   - `TIMEOUT` — something unexpected. If actually in the overworld (not in battle), auto-checks for dialogue and upgrades to `BATTLE_ENDED`. Otherwise, screenshot + `read_battle` to diagnose.
   - `NO_TEXT` — something unexpected. Screenshot + `read_battle` to diagnose.

Note: `battle_turn` includes `read_battle` data in every response — no separate call needed.

## Auto Grind Workflow

`auto_grind` automates wild encounter loops. Stand in a grass/cave area.

When `move_index` is provided, fights each encounter by spamming that move (grind mode).
When `move_index` is omitted, runs from each encounter (seek mode).
When `target_species` is set, stops at the action prompt when that species appears.

### Basic call
```
auto_grind(move_index=0)                    # spam move slot 0, grind indefinitely
auto_grind(move_index=2, target_level=15)   # stop at Lv15
auto_grind(move_index=1, cave=true)         # cave encounters
auto_grind(move_index=0, iterations=5)      # stop after 5 encounters (scouting)
auto_grind(move_index=0, iterations=10, target_level=20)  # whichever comes first
auto_grind(target_species="Machop")         # run from everything until Machop appears
auto_grind(move_index=0, target_species="Larvitar")  # grind, but stop if Larvitar appears
auto_grind(move_index=3, backup_move=2)     # alternate moves when Tormented/Disabled
```

### Smart move selection
When `backup_move` is set, checks type effectiveness per encounter:
- Primary move effective (mult > 0.5) → use primary as normal
- Primary NVE/immune, backup effective → use backup for that battle
- Both NVE/immune + `flee_ineffective=True` → flee, continue to next encounter
- Both NVE/immune + `flee_ineffective=False` → fight with primary anyway (default)

```
auto_grind(move_index=0, backup_move=2, flee_ineffective=true)  # smart selection + flee
```

### Auto-heal loop
Two modes: **auto-detect** (preferred) or **coordinate-based** (legacy).

**Auto-detect** (`auto_heal=True`): No coordinates needed. Scans the overworld matrix for
the nearest Pokemon Center, navigates there (trying alternative cities if the nearest is
blocked by terrain), heals, and returns to the grind spot. Works from routes and interior
maps (exits via warps first). Handles the 5x5 chunk terrain cap with multi-hop navigation.

```
auto_grind(move_index=0, target_level=25, auto_heal=true)   # just works
auto_grind(move_index=0, auto_heal=true, max_heal_trips=20) # raise safety cap
```

**Coordinate-based** (legacy): Provide `heal_x/heal_y/grind_x/grind_y` for same-map healing.

```
auto_grind(move_index=0, target_level=25, heal_x=15, heal_y=8, grind_x=42, grind_y=20)
```

### Stop conditions (returned as `stop_reason`)
| Reason | Meaning | What to do |
|--------|---------|------------|
| `target_level` | Slot 0 reached the target level. | Done! |
| `shiny` | Wild shiny Pokemon encountered. At action prompt. | Catch it! Battle state included in response. Always triggers regardless of other params. |
| `target_species` | Found the target species. At action prompt. | Fight, catch, or flee. Battle state included in response. |
| `iterations` | Completed the requested number of encounters. | Review encounter log. |
| `fainted` | Slot 0 fainted (only when auto-heal is disabled). | Heal, then grind again or switch lead. |
| `pp_depleted` | Spam move has 0 PP (only when auto-heal is disabled). | Handle manually: flee, use another move, or use an Ether. |
| `move_learn` | Pokemon wants to learn a move but all 4 slots are full. | Call `auto_grind` again with `forget_move` to continue (see below). |
| `move_blocked` | Primary move blocked by Torment/Disable/Encore/Taunt, no `backup_move` set. | Provide `backup_move` to auto-alternate, or handle manually. |
| `turn_limit` | Battle exceeded 10 turns without ending (safety valve). | Likely move-lock or unexpectedly tanky opponent. |
| `heal_failed` | Auto-heal navigation or healing failed. | Check position, navigate manually, retry. |
| `max_heal_trips` | Reached the safety cap on heal cycles. | Increase `max_heal_trips` or investigate why healing is needed so often. |
| `seek_failed` | `seek_encounter` didn't find a battle (cutscene, blocked path). | Investigate manually. |
| `unexpected` | Unknown battle state. | Screenshot + `read_battle` to diagnose. |

### Encounter log
Every `auto_grind` response includes an `encounters` list. Each entry has:
- `species`: The wild Pokemon's species name.
- `checkpoint_id`: Hash of the checkpoint taken just before `seek_encounter`. Use `revert_to_checkpoint(checkpoint_id)` to return to the moment before that encounter — useful for catching a specific Pokemon at the cost of any XP gained after that point.

### Continuing from move_learn
When stopped for `move_learn`, the response includes `move_to_learn` and `current_moves` (with slot indices). Resume with:
```
auto_grind(move_index=0, forget_move=2)     # forget move slot 2, learn the new move, keep grinding
auto_grind(move_index=0, forget_move=-1)    # skip learning, keep grinding
```
All other parameters (cave, target_level, iterations) should be re-supplied when resuming.

## DS Screen Layout

- **Top screen** (256x192): Main game display.
- **Bottom screen** (256x192): Touch-enabled, used for menus, Pokemon selection, etc.
- Screenshots with `screen="both"` show both stacked vertically (256x384).

## Input Reference

**Buttons:** a, b, x, y, l, r, start, select, up, down, left, right

- **A**: Confirm / advance dialogue / interact. Use `press_buttons(["a"], frames=8)`.
- **B**: Cancel / advance dialogue. **Prefer B over A for advancing dialogue** — avoids re-triggering nearby NPCs.
- **X**: Open menu (overworld). **Use X, not Start** — Start does not open the menu in Platinum.
- **D-pad**: Move character / navigate menus.
- **Touch screen**: Tap targets on bottom screen. **Always use `get_screenshot(screen="bottom")`** for coordinate estimation.

### Bag Pocket Tabs (Bottom Screen, in-bag view)
Touch targets arranged in a circle around the Poketch ball:

| Pocket | Tap (x, y) |
|--------|-----------|
| Items | (27, 51) |
| Medicine | (35, 102) |
| Poke Balls | (59, 142) |
| TMs & HMs | (100, 165) |
| Berries | (156, 165) |
| Mail | (195, 142) |
| Battle Items | (220, 102) |
| Key Items | (228, 51) |

### Touch Screen Keyboard (Name Entry)
Letter grid coordinates (calibrated):
- Row 1 (A-J): y=99, x starts at 34, spacing 16px
- Row 2 (K-T): y=118
- Row 3 (U-Z): y=137
- Row 4 (0-9): y=172
- BACK button: x=188, y=74
- OK button: x=222, y=74

## Macros

Saved macros persist across sessions in `/workspace/RenegadePlatinumPlaytest/macros/`.

| Macro | Description |
|-------|-------------|
| `mash_a` | Press A 5 times (8-frame holds, 30-frame waits) for dialogue |
| `mash_b` | Press B 5 times (8-frame holds, 30-frame waits) — safer than A |
| `walk_up` | Walk up 2 tiles (32-frame hold + 4-frame wait) |
| `walk_down` | Walk down 2 tiles |
| `walk_left` | Walk left 2 tiles |
| `walk_right` | Walk right 2 tiles |

## Memory Tools

### Snapshot/Diff Workflow (for finding new addresses)
1. `snapshot_memory(name="before", address=0x02200000, size=1048576)`
2. Perform an in-game action
3. `snapshot_memory(name="after", address=0x02200000, size=1048576)`
4. `diff_snapshots(name_a="before", name_b="after", value_size="long", filter="changed")`

## Game Progress

- **Character**: CLAUDE | **Rival**: WOJ
- **Badges**: 2 (Coal, Forest)
- **Location**: Eterna City Pokemon Center. Save state: `eterna_city_post_gardenia_team_updated`.
- **Luxray** Lv30 — Jolly, Guts. Scope Lens. Spark / Bite / Howl / Ice Fang.
- **Grotle** Lv24 — Naughty, Overgrow. Muscle Band. Bulldoze / Cut / Bullet Seed / Razor Leaf.
- **Prinplup** Lv25 — Lax, Vital Spirit. Metal Claw / Growl / Bubble Beam / Icy Wind.
- **Machop** Lv25 — Brave, No Guard. Low Kick / Brick Break / Return / Knock Off. *(Replacing with Flying type.)*
- **Monferno** Lv26 — Careful, Iron Fist. Charcoal. Low Kick / Mach Punch / Flame Wheel / Taunt.
- **Swinub** ✨ Lv20 — Timid, Thick Fat. Exp. Share. Powder Snow / Ice Shard / Bulldoze / Endure.
- **Next**: Team Galactic Eterna Building (Forest Badge unlocks it). Find a Flying type to replace Machop. Shroomish on Route 203 wants an Oran Berry (come back later).

See GAME_HISTORY.md for full details (defeated trainers, story progress, box contents, items).

## Quick Reference: Common Workflows

### Entering a new area
1. `view_map` — see the map layout, NPCs, exits, and **warp destinations** with coordinates
2. `navigate_to(x, y)` — use warp coordinates from `view_map` to enter buildings directly

### Before/during battle
1. `read_battle` — enemy species, types, ability, stats, moves, HP
2. `battle_turn(move_index=0)` — use a move. Returns battle log + state + updated battle data.
3. Or `battle_turn(switch_to=1)` — switch Pokemon instead of attacking.

### Checking inventory/party (overworld)
1. `read_party` — full party with moves, PP, nature, IVs, EVs. Reliable in any game state.
2. `read_bag` — all items across all pockets

### Using items (overworld)
1. `use_item("Potion", 0)` — uses a single Medicine item on the specified party slot (0-indexed)
2. `use_medicine()` — **preferred for bulk healing**. Dry-run returns a plan, `confirm=True` executes. Handles HP, status, and revival optimally.

### Reordering party (overworld)
1. `reorder_party(0, 2)` — swap slot 0 and slot 2. Navigates pause menu automatically.

## Test Suite

Integration tests live in `tests/` (244 tests across 22 files). Require a running emulator with the ROM loaded. Legacy DeSmuME tests in `tests/legacy/` are excluded by default.

```bash
MelonMCP/.venv/bin/python -m pytest tests/ -v          # full suite (~24 min)
MelonMCP/.venv/bin/python -m pytest tests/test_X.py -v  # single file
```

Tests load save states, call implementation functions directly (bypassing MCP protocol), and assert on `final_state`, log contents, and party data. Each test resets via `load_state` so they're independent.

**Run tests after any change to `turn.py`, `auto_grind.py`, `navigation.py`, or `battle_tracker.py`.**

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- **Use `read_battle` at the start of every battle** — Renegade Platinum changes abilities and movesets from vanilla.
- **`read_dialogue` auto-advances by default** — just call it after triggering dialogue and it handles everything. Returns full conversation + status. Only need manual intervention for Yes/No prompts and multi-choice prompts.
- The `load_state` tool may occasionally hang — check `get_status` to verify.
- Addresses must be passed as decimal integers to MCP tools, not hex strings.
- **Touch screen taps default to `frames=8`** — changed from 1 to avoid missed inputs.
- **Wait 300 frames between UI navigation steps** — Pokemon ignores input during forced text delays.
- **Always check the bottom screen for Yes/No prompts** — battle/switch prompts use touch screen.
- **`battle_turn` detects battle end via text absence** — after seeing battle narration, 20 consecutive polls (~5 sec) with no text markers triggers early exit. Log-based heuristic ("fainted" + "Exp. Points") classifies as BATTLE_ENDED. Level-up cases ("grew to" in log) defer to recovery instead.
- **Pause menu remembers cursor position** — cursor index stored at `0x0229FA28`. The `use_item` tool reads this automatically; for manual menu navigation, read this address first.
- **Trainer battles may have multiple Pokemon** — handle "Will you switch?" prompt before next action.
- **Evolution is handled** — after level-up + move-learn resolution, `battle_turn` detects "is evolving" text, dismisses it with a single B press, then waits passively (no B) for the ~15s animation. "evolved into [Species]!" is captured in the log. Tested with Shinx→Luxio (Lv15). Works in both `battle_turn` and `auto_grind` flows.
