# Pokemon Renegade Platinum Playtest

You are playtesting the DeSmuME MCP server by playing Pokemon Renegade Platinum (a difficulty/QoL hack of Pokemon Platinum by Drayano).

## Getting Started

1. Call `init_emulator` to initialize DeSmuME.
2. Call `load_rom` with path `/workspace/RenegadePlatinumPlaytest/RenegadePlatinum.nds`.
3. Load a save state if one exists (e.g., `load_state("living_room")`).
4. If no save state, you'll need to advance through the intro (~8000 frames) to reach the title screen.

## Save States

See [SAVE_STATES.md](SAVE_STATES.md) for the full save state table (60+ entries).

## Renegade MCP Tools

Game-specific tools are provided by the `renegade` MCP server (defined in `renegade_mcp/`). These run alongside the generic `desmume` MCP server. All tools connect to the emulator via the bridge socket — if the emulator isn't initialized yet, they return a clear error.

| Tool | Purpose |
|------|---------|
| `read_party` | Party Pokemon: species, level, HP, moves, PP, nature, IVs, EVs. Three-tier encryption handling: flag-based, opposite-flag fallback, and mixed-state split-point recovery for mid-encrypt/decrypt frames. Works reliably in any game state. |
| `read_battle` | Live battle state: all battlers with stats, moves, ability, types, status |
| `read_bag(pocket="")` | Bag contents across all 7 pockets. Optional pocket filter. |
| `view_map(level=-1)` | **Player-centered viewport**: 32x32 ASCII map centered on the player, loading adjacent chunks as needed on overworld maps. Indoor/small maps use compact content-fitted rendering (no void padding). Header includes `origin:(x,y) WxH` — the global coordinate of the top-left grid corner and viewport dimensions. Convert any grid position to global coords: `global = origin + grid_pos`. Player dict includes `grid_x`/`grid_y` for the player's position in the grid. Warp coordinates can be passed directly to `navigate_to`. **Objects sorted by distance**: nearest objects/NPCs appear first in the list (Manhattan distance from player). **Trainer defeated status**: trainer NPCs show `[defeated]` in label, plus `trainer_id` and `defeated` fields (reads VarsFlags bitfield from save RAM). Works for regular trainers; gym leaders/rivals use separate story flags. **Elevation-aware**: on 3D maps, passable tiles show height level numbers (0-9), ramps show `\ /`, bridges show `n*`, directional blockers show `] [`, with an elevation summary listing all levels and the player's current height. Pass `level=N` to filter to a single elevation level (other tiles dimmed to `~`). Flat maps render unchanged. Uses BDHC data from ROM land_data files. |
| `map_name(map_id=-1)` | Location name lookup. Defaults to current map. |
| `navigate(directions, flee_encounters)` | Manual walk: "d2 l3 u1". Validates path before moving; auto-trims at door/stair/warp transitions. Returns `encounter` key if battle/dialogue detected. **`flee_encounters=True`**: auto-flees wild battles and resumes remaining directions. Trainer battles and cutscenes still halt. |
| `navigate_to(x, y, path_choice, flee_encounters)` | BFS pathfind to target tile. **Sign-aware**: reads sign positions from ROM zone_event data (gfx IDs 91-96) and blocks the activation tile (one south of each sign) in BFS to prevent auto-trigger dialogue. **Elevation-aware**: on 3D maps (gyms, caves, AND multi-chunk overworld routes with bridges/cliffs), uses hierarchical BFS — constrains search to current elevation level and brute-forces through ramp transitions when target is on a different level. Multi-chunk maps load BDHC per chunk with unified height→level mapping. Depth-capped (5 transitions) with 5-minute timeout. Enforces directional blocks (0x30/0x31). Falls through to 2D BFS for flat maps only. **Obstacle-aware**: runs dual BFS (clean vs obstacle path). When HM obstacles (Rock Smash rocks, Cut trees) shorten or enable a path, returns `obstacle_choice`/`obstacle_required` status without moving — call again with `path_choice="obstacle"` or `"clean"`. Strength boulders never auto-cleared. Handles all 14 warp tile types. Water/waterfall/rock climb terrain recognized but deferred. Returns `encounter` key if battle/dialogue detected. **`flee_encounters=True`**: auto-flees wild battles and re-BFS's from current position. Trainer battles (detected by pre-battle dialogue) and cutscenes halt for the caller. Returns `flee_log` with species/attempts. **Failure diagnostics**: on "no path found," returns a 9x9 ASCII `diagram` centered on the target (`@`=player, `X`=target, `*`=nearest reachable, `#`=wall, `.`=passable, `N`=NPC, `≈`=water) plus `nearest_reachable` with global coords and distance. |
| `interact_with(object_index, x, y, flee_encounters)` | Navigate to a map object/NPC by index OR static tile by (x,y) and interact. Handles adjacent tiles, counter NPCs, facing, and dialogue. **Auto-advances** through full multi-page dialogue (chains into `advance_dialogue`). Detects trainer-spotted interruptions and checks for battle transitions post-dialogue. **`flee_encounters=True`**: auto-flees wild battles encountered during the walk to the target. |
| `seek_encounter(cave=false)` | Pace in grass until wild encounter. Returns at first action prompt with full battle state. `cave=true` for non-grass encounters. |
| `read_dialogue(advance=true)` | Auto-advance through dialogue, collect full conversation. Stops at Yes/No prompts and multi-choice prompts. `advance=false` for passive read. |
| `battle_turn(move_index, switch_to, run, force)` | Full automated turn: FIGHT + move, POKEMON + switch, or RUN to flee. **Type effectiveness guardrail**: checks move type vs target types before executing. Returns `EFFECTIVENESS_WARNING` if move is immune or NVE — call again with `force=True` to proceed. Returns battle log + state + trimmed battle summary (species, level, hp, types, status, stages, moves name+pp; enemy gets ability+item). |
| `throw_ball` | Throw a Poké Ball in wild battle: BAG + ball select + USE + catch result |
| `reorder_party(from_slot, to_slot)` | Swap two party Pokemon via pause menu (overworld only) |
| `decode_rom_message(file_index)` | Decode ROM message archive (species, moves, items, etc.) |
| `search_rom_messages(query)` | Search all 724 message files for text |
| `use_item(item_name, party_slot)` | Use a Medicine item on a party Pokemon from overworld. Reads bag cursor state to handle remembered positions. |
| `use_field_item(item_name)` | Use a no-target field item (Repel, Escape Rope, Honey, etc.) from the Items pocket. Pre-validates `fieldUseFunc` from ROM data — rejects hold-only items (Silk Scarf, etc.). Handles BAG_MESSAGE items (Repel/Flutes), Escape Rope (warp animation), and Honey. |
| `use_medicine(confirm, exclude_items, priority)` | Bulk heal party using Medicine pocket items. Dry-run by default — returns a plan showing which items will be used on which Pokemon. Call with `confirm=True` to execute. Uses lowest-tier potions first (saves better items for battle), prefers specific status cures over general ones (Antidote before Full Heal), uses Full Restore when a Pokemon needs both status cure + HP. Revives fainted Pokemon. Optional `exclude_items` list and `priority` slot order. |
| `take_item(party_slot)` | Remove held item from a party Pokemon via pause menu (overworld only) |
| `give_item(item_name, party_slot)` | Give a held item to a party Pokemon via pause menu (overworld only). Pokemon must not already hold an item. Reads bag cursor state to handle remembered positions. |
| `heal_party` | Heal at Pokemon Center. Works from inside a PC (direct) or city overworld (auto-navigates to PC via warp lookup). Returns encounter data if interrupted during navigation. |
| `open_pc` | Boot up the PC: finds 0x83 tile, navigates, interacts, advances to storage menu (DEPOSIT/WITHDRAW/MOVE/SEE YA!). |
| `deposit_pokemon(party_slots)` | Deposit party Pokemon into Box 1. Takes list of 0-indexed slots. Multi-deposit supported. Must call open_pc first. |
| `withdraw_pokemon(box_slots)` | Withdraw Pokemon from Box 1 to party. Takes list of 0-indexed box slots. Multi-withdraw supported. Must call open_pc first. |
| `read_box(box=1)` | Read all Pokemon in a PC box from RAM. No UI needed — works anytime. Returns species, moves, nature, IVs, EVs, held item. |
| `close_pc` | Exit the PC from storage menu and return to overworld. |
| `read_trainer_status` | Read money and badges from memory. No UI needed. |
| `read_shop` | Read PokéMart inventory for current city. Badge-gated common items + city specialty items with ROM prices. Pure lookup, no UI. |
| `buy_item(item_name, quantity)` | Buy from a standard PokéMart. Works from inside the mart (FS room) or city overworld (auto-navigates to mart via warp lookup). Finds correct cashier (common vs specialty), scrolls to item by ROM-calculated position, purchases, exits. Pre-checks money. Returns encounter data if interrupted during navigation. |
| `teach_tm(tm_name, party_slot, forget_move)` | Teach a TM/HM to a party Pokemon. Accepts TM label ("HM06", "TM76") or move name ("Rock Smash"). Pre-validates ROM compatibility (personal.narc bitmasks) and badge+move availability. Handles both <4 moves (auto-learn) and 4 moves (forget prompt) flows. Pass `forget_move` (0-3) when Pokemon knows 4 moves, or -1 to cancel. |
| `tm_compatibility(tm_name)` | Check which party Pokemon can learn a given TM/HM. Pure ROM data lookup — no emulator interaction. Returns ABLE/UNABLE/ALREADY KNOWS per party slot. |
| `type_matchup(attacking_type, defending_types, move_name)` | Type effectiveness check (like Pokemon Showdown's calc). Pass `attacking_type="Fire"` + `defending_types="Grass/Steel"`, or `move_name="Spark"` + `defending_types="Water/Flying"`. Returns multiplier + label. Gen 4 chart + Fairy type. |
| `move_info(move_name)` | Move stats lookup: type, power, accuracy, PP, class (Physical/Special/Status), priority. Pure ROM data, no emulator needed. Also: `read_party` and `read_battle` now show move details inline (e.g. `Bullet Seed [Grass · Physical · 25 pwr · 100% acc]`). |
| `auto_grind(move_index, cave, target_level, iterations, forget_move, target_species)` | Automated encounter loop: seek encounters + fight (spam a move) or run. Stops on target level, iterations, or target species. Returns encounter log with species + checkpoint IDs. See Auto Grind Workflow below. |
| `reload_tools` | Reload all `renegade_mcp` implementation modules in-place via `importlib.reload()`. Call after editing any `renegade_mcp/*.py` file (except `server.py`) to pick up code changes without restarting the MCP server. Changes to `server.py` (new/removed tools, signature changes) still require a manual `/mcp` restart from the user. |

The original Python scripts in `scripts/` still work for debugging but are no longer the primary interface.

### Adding New Tools

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

Checkpoints share a unified ring buffer (300 slots) with the DeSmuME MCP's own checkpoints. One checkpoint per tool call is the right granularity — don't checkpoint inside helper functions. Sub-tools like `auto_grind` may create additional internal checkpoints for per-encounter granularity.

### Reloading After Code Changes

After editing implementation files (`renegade_mcp/*.py` except `server.py`), call `reload_tools` to pick up changes in-place. No MCP restart needed — `importlib.reload()` refreshes all cached modules, and the lazy imports in tool wrappers pick up the new code on the next call.

If `server.py` itself was changed (new tool added, tool removed, signature changed), ask the user to `/mcp` restart — `reload_tools` can't re-register tool wrappers.

## Navigation

**CRITICAL: Do not rely on screenshots for spatial reasoning in the overworld.** The isometric/overhead camera makes it very difficult to judge tile positions, room boundaries, and exits from pixel images. Instead:

- **Use `view_map`** to get a full map with terrain, player, NPCs, and **warp destinations** — all read live from the emulator. The `warps` list shows every door/stair exit with its destination name and tile coordinates.
- **Use warp coordinates from `view_map` with `navigate_to`** to enter buildings — the (x, y) from a warp entry can be passed directly to `navigate_to` for seamless transitions.
- **Use `navigate` or `navigate_to`** to walk paths — they verify each step and stop on collision. `navigate` auto-trims paths at door/stair transitions. `navigate_to` auto-enters adjacent walk-into doors (0x69, 0x6E).
- **When stuck navigating, ask Michael for visual help** rather than brute-forcing positions.
- Screenshots are fine for reading dialogue, menus, and battle screens — just not for spatial navigation.
- **Position dicts** (start/final in navigate responses) include full map name info (`map_id`, `name`, `display`, `code`, `room`) instead of a bare map ID. No need to call `map_name` separately.

Multi-chunk maps (overworld, large caves) use a matrix/chunk system detected automatically by `view_map` and `navigate_to`. See MEMORY_MAP.md for collision data format, tile behaviors, and dynamic object details.

## Game State Tools

**Use these tools instead of navigating in-game menus** — faster, more reliable, no accidental inputs.

- **`read_party`** — full party data from RAM. Works in overworld + battle. Checks encryption-state flags on each slot automatically, so reads are reliable whether data is encrypted or in a decryption context. See MEMORY_MAP.md for data format.
- **`read_bag`** — all 7 bag pockets. Pass `pocket="Key Items"` to filter.
- **`read_battle`** — live battle data for all active battlers. Returns empty if not in battle. See MEMORY_MAP.md for struct layout.
- **`map_name`** — location name from map ID. No args = current map.
- **`read_dialogue(advance=true)`** — auto-advances through overworld dialogue, collecting the full conversation. Stops at Yes/No prompts (returns `status: "yes_no_prompt"`), multi-choice prompts (`status: "multi_choice_prompt"`), or dialogue end (`status: "completed"`). Multi-choice detection uses conversation loop tracking — catches script cycles from non-Yes/No selection menus. Uses the ScriptManager/ScriptContext/TextPrinter state machine for reliable detection. Pass `advance=false` for passive read (old behavior). Pass `region="battle"` with `advance=false` for battle text.
- **`read_shop`** — PokéMart inventory for current city. Detects city from map code prefix (works inside buildings). Returns badge-gated common items + city specialty items with prices from ROM (`pl_item_data.narc`). Returns error if not in a city/town.
- **`decode_rom_message(file_index)`** / **`search_rom_messages(query)`** — ROM data lookup (no emulator needed).

Key ROM file indices: 0392=items, 0412=species, 0610=abilities, 0647=moves, 0433=locations, 0646=move descriptions.

## Battle Workflow

### Automated (preferred)
1. **`read_battle`** — check enemy species, types, ability, stats, moves. Plan tactics. Returns all 4 battlers in double battles. Use **`type_matchup`** to check effectiveness before committing.
2. **`battle_turn(move_index=N)`** — use a move (0-3). **Checks type effectiveness first** — returns `EFFECTIVENESS_WARNING` if the move is immune or not very effective against the target. Call with `force=True` to proceed anyway (e.g., status moves, chip damage, or when no better option). Returns battle log + final state + updated battle state.
   - Or **`battle_turn(switch_to=N)`** — switch to party slot N (0-5) instead of attacking.
   - Or **`battle_turn(run=True)`** — attempt to flee a wild battle. Returns `BATTLE_ENDED` on success, `WAIT_FOR_ACTION` on failure (enemy gets a free turn).
   - In **double battles**, add `target=` to specify the target: `0`=left enemy, `1`=right enemy, `2`=self/ally. Default `-1` auto-targets first enemy.
   - Works on the very first turn of battle — no need to call twice.
3. Handle the returned state:
   - `EFFECTIVENESS_WARNING` — move is immune or not very effective. Review the warning, then either pick a different move/switch, or call `battle_turn(move_index=N, force=True)` to use it anyway. No game state has changed yet.
   - `WAIT_FOR_ACTION` — next turn, call `battle_turn` again. Battle state is included in the response.
   - `WAIT_FOR_PARTNER_ACTION` — double battle: first Pokemon's action submitted, call `battle_turn` again for second Pokemon.
   - `SWITCH_PROMPT` — trainer sending next Pokemon. Call `battle_turn(switch_to=N)` to swap, `battle_turn()` to keep battling, or `battle_turn(move_index=N)` to decline the switch and use that move in one call.
   - `FAINT_SWITCH` — your Pokemon fainted (wild battle). Call `battle_turn(switch_to=N)` to send replacement, or `battle_turn()` to flee.
   - `FAINT_FORCED` — your Pokemon fainted (trainer battle). Call `battle_turn(switch_to=N)` to send replacement (required).
   - `BATTLE_ENDED` — back in overworld. **Auto-advances post-battle dialogue** (trainer defeat text, story triggers) if present — returned as `post_battle_dialogue` list. No manual `read_dialogue` needed.
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
```

### Stop conditions (returned as `stop_reason`)
| Reason | Meaning | What to do |
|--------|---------|------------|
| `target_level` | Slot 0 reached the target level. | Done! |
| `target_species` | Found the target species. At action prompt. | Fight, catch, or flee. Battle state included in response. |
| `iterations` | Completed the requested number of encounters. | Review encounter log. |
| `fainted` | Slot 0 fainted. | Heal, then grind again or switch lead. |
| `pp_depleted` | Spam move has 0 PP mid-battle. | Handle manually: flee, use another move, or use an Ether. |
| `move_learn` | Pokemon wants to learn a move but all 4 slots are full. | Call `auto_grind` again with `forget_move` to continue (see below). |
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
- **Badges**: 1 (Coal Badge — Roark defeated)
- **Location**: Route 216 (mid-route). Save state: `route216_snow_nav_bug`.
- **Prinplup** Lv21 — Lax (+Def/-SpD), Vital Spirit. Held: Exp. Share. Moves: Metal Claw, Growl, Bubble Beam, Peck. HP: 23/64.
- **Machop** Lv21 — Brave (+Atk/-Spe), No Guard. No held item. Moves: Low Kick, Brick Break, Focus Energy, Knock Off.
- **Grotle** Lv24 — Naughty (+Atk/-SpD), Overgrow. Held: Muscle Band. Moves: Bulldoze, Cut, Bullet Seed, Razor Leaf.
- **Luxio** Lv21 — Jolly (+Spe/-SpA), Guts. Held: Scope Lens. Moves: Spark, Bite, Howl, Quick Attack. HP: 53/59.
- **Charmeleon** Lv23 — Hardy, Blaze. Held: Charcoal. Moves: Bite, Metal Claw, Fire Fang, Dragon Breath. **FAINTED**.
- **Box 1**: Bulbasaur Lv5 (Docile, Chlorophyll, Miracle Seed), Squirtle Lv5 (Gentle, Mystic Water), Eevee Lv12 (Gentle, Run Away), Chimchar Lv12 (Careful, Iron Fist).
- **Key items**: Poke Ball x28, Potion x9, Antidote x3, Parlyz Heal, Honey x10, Repel x8, Energy Root x3, Revival Herb x2, Charcoal, Silk Scarf, Magnet, Soothe Bell, Sun Stone, TM58 Endure, TM Stealth Rock, TM Aerial Ace, TM34 Shock Wave, TM65 Shadow Claw, TM27 Return, TM46 Thief, TM69 Rock Polish, Fashion Case, Bicycle, Poke Radar, Town Map, Vs. Recorder, Poketch, Oval Stone, Fire Stone, HM01 Cut, HM Rock Smash.
- **Defeated trainers**: Youngster Tristan (Route 202), Youngster Logan (Route 202), Reporter Kayla (Jubilife Pokemon Center), Rival WOJ (Route 203), Youngster D (Route 203 double battle), Youngster Sebastian (Route 203), Lass Kaitlin (Route 203), Lass Madeline (Route 203), Camper Curtis (Oreburgh Gate), Picnicker Diana (Oreburgh Gate), Youngster Jonathon (Oreburgh Gym), Youngster Darius (Oreburgh Gym), **Gym Leader Roark** (6-0 sweep), 2x Team Galactic Grunts (Jubilife tag battle with Dawn), Lass Sarah (Route 204), Aroma Lady Taylor (Route 204), Bug Catcher Brandon (Route 204), Twins Liv & Liz (Route 204), Camper Jacob (Route 205), Galactic Grunt (Windworks exterior), 2x Galactic Grunts (Floaroma Meadow double battle), 2x Galactic Grunts (Windworks interior), **Commander Mars**, Hiker Daniel (Route 205), Aroma Lady Elizabeth (Route 205), Camper Zackary (Route 205), Hiker Nicholas (Route 205), Battle Girl Kelsey (Route 205), Picnicker Karina (Route 205), **Cheryl** (Eterna Forest — pre-join battle), Bug Catcher Jack (Eterna Forest), Lass Briana (Eterna Forest), Psychic Lindsey (Eterna Forest), Psychic Elijah (Eterna Forest).
- **Defeated trainers (new)**: Hiker Louis (Route 211 — Geodude, Beldum, Slugma), Ace Trainer Laura (Route 216 — Togetic, Swellow).
- **Story progress**: Beat Roark → Coal Badge. Cleared Route 204 north. Arrived Floaroma Town. Cleared Valley Windworks storyline. Looker: Team Galactic hideout is in Eterna City. Completed Route 205 north (upper path). Entered Eterna Forest, defeated Cheryl to prove strength, she joined as tag battle partner. Traversed Eterna Forest with Cheryl. Cheryl gave TM27 (Return) at exit. Crossed Route 205 bridge to Eterna City. Team Galactic grunts spotted in Eterna City. Explored Eterna City: triggered WOJ+Cyrus statue cutscene, met Cynthia (got HM01 Cut), bought herbs at Herb Shop, explored Route 211 and Mt. Coronet tunnel. Gardenia is NOT at gym — went to Route 216 (Renegade Platinum change). Galactic building requires Forest Badge. Traversed Mt. Coronet (Route 211 entrance → map 218 → map 219 → map 217 → Route 216 exit). Reached Route 216. Defeated Ace Trainer Laura.
- **Next**: Continue Route 216 to find Gardenia, return for gym battle. After gym: Team Galactic Eterna Building. Shroomish on Route 203 wants an Oran Berry (come back later).

See GAME_HISTORY.md for full chronological playthrough details.

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

## Battle Test Suite

Integration tests for `battle_turn` and `auto_grind` live in `tests/`. They require a running emulator with the ROM loaded.

```bash
DesmumeMCP/.venv/bin/python -m pytest tests/ -v          # full suite (~17 min)
DesmumeMCP/.venv/bin/python -m pytest tests/test_X.py -v  # single file
```

Tests load save states, call battle functions directly (bypassing MCP protocol), and assert on `final_state`, log contents, and party data. Each test resets via `load_state` so they're independent.

| File | Coverage |
|------|----------|
| `test_battle_end.py` | Wild KO, trainer multi-Pokemon, switch prompt after KO |
| `test_move_learn.py` | Level-up move-learn, auto-learn (open slot), skip, forget |
| `test_evolution.py` | Mid-battle evo chain, Exp Share evo, "What?" animation |
| `test_faint_switch.py` | Wild faint send/flee, trainer switch accept/decline, voluntary |
| `test_double_battle.py` | Partner action prompt, both actions complete turn |
| `test_multi_hit.py` | 5-hit Bullet Seed KO → SWITCH_PROMPT (not TIMEOUT), log completeness |
| `test_auto_grind.py` | Iteration stop, encounter log, mid-battle resume |

**Run tests after any change to `turn.py`, `auto_grind.py`, or `battle_tracker.py`.**

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- **Use `read_battle` at the start of every battle** — Renegade Platinum changes abilities and movesets from vanilla.
- **`read_dialogue` auto-advances by default** — just call it after triggering dialogue and it handles everything. Returns full conversation + status. Only need manual intervention for Yes/No prompts and multi-choice prompts.
- The `load_state` tool may occasionally hang — check `get_status` to verify.
- Addresses must be passed as decimal integers to DeSmuME MCP tools, not hex strings.
- **Touch screen taps default to `frames=8`** — changed from 1 to avoid missed inputs.
- **Wait 300 frames between UI navigation steps** — Pokemon ignores input during forced text delays.
- **Always check the bottom screen for Yes/No prompts** — battle/switch prompts use touch screen.
- **`battle_turn` detects battle end via text absence** — after seeing battle narration, 20 consecutive polls (~5 sec) with no text markers triggers early exit. Log-based heuristic ("fainted" + "Exp. Points") classifies as BATTLE_ENDED. Level-up cases ("grew to" in log) defer to recovery instead.
- **Pause menu remembers cursor position** — cursor index stored at `0x0229FA28`. The `use_item` tool reads this automatically; for manual menu navigation, read this address first.
- **Trainer battles may have multiple Pokemon** — handle "Will you switch?" prompt before next action.
- **Evolution is handled** — after level-up + move-learn resolution, `battle_turn` detects "is evolving" text, dismisses it with a single B press, then waits passively (no B) for the ~15s animation. "evolved into [Species]!" is captured in the log. Tested with Shinx→Luxio (Lv15). Works in both `battle_turn` and `auto_grind` flows.
