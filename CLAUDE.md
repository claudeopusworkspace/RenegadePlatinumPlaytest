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
| `view_map` | ASCII map with terrain, player position, NPCs, and warp destinations (from ROM zone_event data). Warp coordinates can be passed directly to `navigate_to`. |
| `map_name(map_id=-1)` | Location name lookup. Defaults to current map. |
| `navigate(directions)` | Manual walk: "d2 l3 u1". Validates path before moving; auto-trims at door/stair/warp transitions. Returns `encounter` key if battle/dialogue detected. |
| `navigate_to(x, y)` | BFS pathfind to target tile. Handles all 14 warp tile types: doors (0x69, 0x6E), stairs (0x5E, 0x5F), cave entrances (0x62-0x65), side entries (0x6C-0x6F), panels (0x67), escalators (0x6A-0x6B). Direction-aware for directional warps. Water tiles blocked. Returns `encounter` key if battle/dialogue detected. |
| `interact_with(object_index, x, y)` | Navigate to a map object/NPC by index OR static tile by (x,y) and interact. Handles adjacent tiles, counter NPCs, facing, and dialogue. Detects trainer-spotted interruptions (facing seized by script) and falls back to polling for dialogue/battle. |
| `seek_encounter(cave=false)` | Pace in grass until wild encounter. Returns at first action prompt with full battle state. `cave=true` for non-grass encounters. |
| `read_dialogue(advance=true)` | Auto-advance through dialogue, collect full conversation. Stops at Yes/No prompts and multi-choice prompts. `advance=false` for passive read. |
| `battle_turn(move_index, switch_to)` | Full automated turn: FIGHT + move OR POKEMON + switch. Returns battle log + state + read_battle data. |
| `throw_ball` | Throw a Poké Ball in wild battle: BAG + ball select + USE + catch result |
| `reorder_party(from_slot, to_slot)` | Swap two party Pokemon via pause menu (overworld only) |
| `decode_rom_message(file_index)` | Decode ROM message archive (species, moves, items, etc.) |
| `search_rom_messages(query)` | Search all 724 message files for text |
| `use_item(item_name, party_slot)` | Use a Medicine item on a party Pokemon from overworld. Reads bag cursor state to handle remembered positions. |
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
| `buy_item(item_name, quantity)` | Buy from a standard PokéMart. Must be inside the mart (FS room). Finds correct cashier (common vs specialty), scrolls to item by ROM-calculated position, purchases, exits. Pre-checks money. |
| `auto_grind(move_index, cave, target_level, iterations, forget_move)` | Automated grinding loop: seek encounters + spam a move until a stop condition. Returns encounter log with species + checkpoint IDs. See Auto Grind Workflow below. |

The original Python scripts in `scripts/` still work for debugging but are no longer the primary interface.

### Adding New Tools

All state-changing tools (anything that presses buttons, advances frames, or writes memory) **must** create a checkpoint before performing any emulator interaction. This enables undo/revert when a tool bugs out. Pattern in `server.py`:

```python
emu = get_client()
emu.create_checkpoint(action="tool_name(relevant args)")
return _do_stuff(emu, ...)
```

Read-only tools (pure memory reads like `read_party`, `read_battle`, `read_bag`) do **not** need checkpoints.

Checkpoints share a unified ring buffer (300 slots) with the DeSmuME MCP's own checkpoints. One checkpoint per tool call is the right granularity — don't checkpoint inside helper functions.

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
1. **`read_battle`** — check enemy species, types, ability, stats, moves. Plan tactics. Returns all 4 battlers in double battles.
2. **`battle_turn(move_index=N)`** — use a move (0-3). Waits for action prompt automatically, then executes. Returns battle log + final state + updated battle state.
   - Or **`battle_turn(switch_to=N)`** — switch to party slot N (0-5) instead of attacking.
   - In **double battles**, add `target=` to specify the target: `0`=left enemy, `1`=right enemy, `2`=self/ally. Default `-1` auto-targets first enemy.
   - Works on the very first turn of battle — no need to call twice.
3. Handle the returned state:
   - `WAIT_FOR_ACTION` — next turn, call `battle_turn` again. Battle state is included in the response.
   - `WAIT_FOR_PARTNER_ACTION` — double battle: first Pokemon's action submitted, call `battle_turn` again for second Pokemon.
   - `SWITCH_PROMPT` — trainer sending next Pokemon. Call `battle_turn(switch_to=N)` to swap, or `battle_turn()` to keep battling.
   - `FAINT_SWITCH` — your Pokemon fainted (wild battle). Call `battle_turn(switch_to=N)` to send replacement, or `battle_turn()` to flee.
   - `FAINT_FORCED` — your Pokemon fainted (trainer battle). Call `battle_turn(switch_to=N)` to send replacement (required).
   - `BATTLE_ENDED` — back in overworld.
   - `MOVE_LEARN` — Pokemon wants to learn a new move. Response includes `move_to_learn` (the new move name, read directly from memory) and `current_moves` with slot indices. Call `battle_turn(forget_move=N)` to forget move N (0-3) and learn the new move, or `battle_turn(forget_move=-1)` to skip. Works in both trainer and wild battles.
   - `NO_ACTION_PROMPT` — action prompt never appeared (~30 sec timeout). Game may need manual input.
   - `TIMEOUT` / `NO_TEXT` — something unexpected. Screenshot + `read_battle` to diagnose.

Note: `battle_turn` includes `read_battle` data in every response — no separate call needed.

## Auto Grind Workflow

`auto_grind` automates wild encounter grinding. Stand in a grass/cave area with the training target in party slot 0.

### Basic call
```
auto_grind(move_index=0)                    # spam move slot 0, grind indefinitely
auto_grind(move_index=2, target_level=15)   # stop at Lv15
auto_grind(move_index=1, cave=true)         # cave encounters
auto_grind(move_index=0, iterations=5)      # stop after 5 encounters (scouting)
auto_grind(move_index=0, iterations=10, target_level=20)  # whichever comes first
```

### Stop conditions (returned as `stop_reason`)
| Reason | Meaning | What to do |
|--------|---------|------------|
| `target_level` | Slot 0 reached the target level. | Done! |
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

- **Character**: CLAUDE | **Rival**: AAAAAAA
- **Badges**: 1 (Coal Badge — Roark defeated)
- **Location**: Oreburgh Gym (post-victory). Save state: `post_roark_victory`.
- **Grotle** Lv21 — Naughty (+Atk/-SpD), Overgrow. Held: Muscle Band. Moves: Bulldoze, Curse, Bullet Seed, Razor Leaf.
- **Machop** Lv17 — Brave (+Atk/-Spe), No Guard. Held: Exp. Share. Moves: Low Kick, Brick Break, Focus Energy, Karate Chop.
- **Prinplup** Lv17 — Lax (+Def/-SpD), Vital Spirit. Moves: Metal Claw, Growl, Bubble, Peck.
- **Luxio** Lv19 — Jolly (+Spe/-SpA), Guts. Held: Scope Lens. Moves: Spark, Bite, Howl, Quick Attack.
- **Charmander** Lv13 — Hardy, Blaze. Held: Charcoal. Moves: Scratch, Metal Claw, Ember, Smokescreen.
- **Box 1**: Bulbasaur Lv5 (Docile, Chlorophyll, Miracle Seed), Squirtle Lv5 (Gentle, Mystic Water), Eevee Lv12 (Gentle, Run Away), Chimchar Lv12 (Careful, Iron Fist).
- **Key items**: Repel x~10, Poke Ball x~28, Potion x9, Antidote x3, Silk Scarf, TM58 Endure, TM Stealth Rock, Bicycle, Poke Radar, Town Map, Vs. Recorder, Poketch, Oval Stone, Fire Stone, HM Rock Smash.
- **Defeated trainers**: Youngster Tristan (Route 202), Youngster Logan (Route 202), Reporter Kayla (Jubilife Pokemon Center), Rival AAAAAAA (Route 203), Youngster D (Route 203 double battle), Youngster Sebastian (Route 203), Lass Kaitlin (Route 203), Lass Madeline (Route 203), Camper Curtis (Oreburgh Gate), Picnicker Diana (Oreburgh Gate), Youngster Jonathon (Oreburgh Gym), Youngster Darius (Oreburgh Gym), **Gym Leader Roark** (6-0 sweep, no faints).
- **Story progress**: Got Poketch from Poketch Company president. Won Bulbasaur from Jubilife TV quiz. Lost to Rival AAAAAAA on Route 203 (first attempt). Picked up Charmander + Squirtle from Reporter in Jubilife PC. Deposited Bulbasaur + Squirtle to Box 1. Grinded team on Route 202 using auto_grind tool. Beat Rival AAAAAAA on Route 203 rematch (Starly Lv10, Munchlax Lv10, Chimchar Lv11). Received Exp. Share from rival. Grinded Shinx to Lv15 on Route 202 → evolved into Luxio. Cleared Route 203 trainers. Traversed Oreburgh Gate (got HM Rock Smash from Hiker). Arrived Oreburgh City — got Oval Stone from greeter NPC. Entered Oreburgh Mine — got Muscle Band on 1F, Fire Stone from Roark on B1F. Cleared Oreburgh Gym trainers. Lost to Roark (attempt 1). Scouted Route 207 encounters: Machop, Phanpy, Ponyta, Rhyhorn, Larvitar. Evolved Turtwig → Grotle (Lv18) and Piplup → Prinplup (Lv16). Caught Machop (Brave/No Guard) on Route 207. Deposited Eevee + Chimchar. Grinded team on Route 207. **Beat Gym Leader Roark** (attempt 2, 6-0 sweep): Nosepass, Geodude, Cranidos, Onix, Larvitar, Bonsly. Received Coal Badge + TM Stealth Rock.
- **Roark's full team** (Renegade Platinum — 6 Pokemon):
  1. Nosepass Lv15 (Rock, Sturdy, Smooth Rock) — Stealth Rock, Sandstorm, Thunder Wave, Shock Wave.
  2. Geodude Lv15 (Rock/Ground, Rock Head, Expert Belt) — Bulldoze, Rock Tomb, Fire Punch, Thunder Punch.
  3. Cranidos Lv16 (Rock, Rock Head, Sitrus Berry) — Zen Headbutt, Rock Tomb, Scary Face, Thunder Punch.
  4. Onix Lv15 (Rock/Ground, Rock Head, Muscle Band) — Stealth Rock, Rock Tomb, Bulldoze, Sandstorm.
  5. Larvitar Lv15 (Rock/Ground, Guts, Flame Orb) — Rock Tomb, Bulldoze, Bite, Protect.
  6. Bonsly Lv15 (Rock, Rock Head, Rindo Berry) — Stealth Rock, Brick Break, Rollout, Defense Curl.
- **Route 207 encounters**: Machop (common), Phanpy, Ponyta, Rhyhorn, Larvitar.
- **Next**: Proceed from Oreburgh Gym. Coal Badge unlocks Rock Smash outside of battle. Head toward next story objective. Shroomish on Route 203 wants an Oran Berry (come back later).

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
1. `use_item("Potion", 0)` — uses a Medicine item on the specified party slot (0-indexed)
2. Handles full menu flow automatically: pause menu → Bag → Medicine → item → USE → party → dismiss

### Reordering party (overworld)
1. `reorder_party(0, 2)` — swap slot 0 and slot 2. Navigates pause menu automatically.

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
