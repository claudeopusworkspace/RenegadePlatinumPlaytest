# Pokemon Renegade Platinum Playtest

You are playtesting the DeSmuME MCP server by playing Pokemon Renegade Platinum (a difficulty/QoL hack of Pokemon Platinum by Drayano).

## Getting Started

1. Call `init_emulator` to initialize DeSmuME.
2. Call `load_rom` with path `/workspace/RenegadePlatinumPlaytest/RenegadePlatinum.nds`.
3. Load a save state if one exists (e.g., `load_state("living_room")`).
4. If no save state, you'll need to advance through the intro (~8000 frames) to reach the title screen.

## Save States

| Name | Description |
|------|-------------|
| `game_start_bedroom` | After intro, in bedroom, BEFORE Barry's dialogue |
| `post_barry_bedroom` | In bedroom, AFTER Barry leaves. Position (4,7) on map 415. |
| `living_room` | Downstairs in the living room, BEFORE Mom's dialogue. Position (10,3) on map 414. |
| `post_mom_living_room` | Downstairs, AFTER Mom gives Running Shoes. Position (10,3) on map 414. Free to move. |
| `first_battle_start` | Rival battle vs AAAAAAA's Chimchar Lv5. At "What will Turtwig do?" menu. |
| `post_rival_battle_twinleaf` | After rival battle, outside in Twinleaf Town (map 411). Turtwig Lv6. |
| `post_lake_verity_cutscene` | After Lake Verity cutscene (Cyrus + Barry). Map 334, Verity Lakefront. |
| `wild_starly_battle_start` | Wild Starly Lv4 battle on Route 201. For debugging battle_poll. Turtwig Lv7. |
| `post_wipe_home_healed` | After whiteout, back in living room. Turtwig Lv7 26/26 HP. |
| `sandgem_town_arrival` | Just entered Sandgem Town (map 418). Turtwig Lv7. |
| `got_pokedex_rowan_lab` | Inside Rowan's lab (map 422) after receiving Pokedex. Free to move. |
| `sandgem_pokemon_center_healed` | Outside Sandgem Pokemon Center (map 418). Turtwig Lv8 healed. |
| `got_eevee_twinleaf` | In player's house (map 414) after obtaining Eevee. Turtwig Lv8, Eevee Lv5. |
| `route_201_heading_east` | Route 201 (map 342) at (123, 854). Heading east to Sandgem. Turtwig Lv8, Eevee Lv5. |
| `sandgem_north_exit_healed` | Sandgem Town (map 418) at (184, 833). Healed, heading to Route 202. |
| `post_dawn_battle_route202` | Route 202 (map 343) at (180, 825). After beating Dawn's Piplup Lv9. Got 30 Poke Balls. Turtwig Lv9. |
| `route202_mid_healed` | Route 202 (map 343) at (166, 815). Turtwig Lv10, healed. Pre-trainer area. |
| `route202_post_tristan_healed` | Route 202 (map 343) at (181, 819). After beating Youngster Tristan. Turtwig Lv11 (learned Curse), 31/35 HP. |
| `tristan_battle_start` | Youngster Tristan battle start. Turtwig Lv10 vs Hoothoot Lv7. Debug state for 2-Pokemon trainer battle. |
| `tristan_switch_prompt` | Mid-battle "Will you switch?" prompt. After KO'ing Hoothoot, before Starly. Debug state. |
| `wild_zigzagoon_route202` | Wild Zigzagoon Lv5 battle. Route 202, at action prompt. For catch tool testing. |
| `route202_grinding_eevee_lv7` | Route 202 grass. Eevee Lv7, Turtwig Lv12, Shinx Lv5 (caught). Post-grind checkpoint. |
| `debug_read_party_missing_slot2` | Debug: read_party skips Turtwig in slot 2 with 3-Pokemon party. |
| `debug_read_battle_false_sleep` | Debug: read_battle shows Sleep(2) on awake wild Shinx. |
| `debug_read_battle_false_positive_trainer` | Debug: read_battle returns garbled in_battle:true during pre-battle trainer dialogue. |
| `sandgem_pokecenter_post_wipe_logan` | Sandgem Pokemon Center (map 420). Wiped to Youngster Logan. Team healed. Shinx Lv5, Turtwig Lv12, Eevee Lv7. |
| `debug_switch_test_baseline` | Wild Zigzagoon Lv5 battle, Route 202. 2 Pokemon (Eevee Lv7, Turtwig Lv9). For battle switch testing. |
| `debug_reorder_test_baseline` | Route 202 overworld. 3 Pokemon (Eevee, Turtwig, Shinx). **Heisenbug repro state** — read_party has stale encrypted data for Turtwig slot. |
| `rowan_lab_before_briefcase` | Rowan's lab (map 422) at (18,5). Before interacting with briefcase to get Chimchar + Piplup. |
| `got_starters_rowan_lab` | Rowan's lab (map 422). Just received Chimchar + Piplup from briefcase. 5 Pokemon party. |
| `debug_garbled_map_post_party_refresh` | Rowan's lab (map 422). Map data garbled after `read_party(refresh=true)` indoors. All tiles read as `ff`. |
| `sandgem_5pokemon_turtwig_lead` | Sandgem Town (map 418). 5 Pokemon, Turtwig leading. Post-reorder test. |
| `sandgem_pc_grind_session_end` | Sandgem Pokemon Center (map 420). Healed. Shinx Lv5, Piplup Lv6, Eevee Lv7, Turtwig Lv12, Chimchar Lv8. |
| `debug_wild_faint_use_next` | Wild Zigzagoon battle, at "Use next Pokemon?" prompt after Turtwig fainted. For faint-switch testing. |
| `debug_pre_level_up_ko` | Tristan battle, Hoothoot at 7 HP. Next Razor Leaf KOs → Turtwig Lv11 → Curse learn prompt. |
| `debug_move_learn_give_up_prompt` | At "Should this Pokemon give up on learning?" prompt. "Give up on Curse!" / "Don't give up on Curse!" buttons. |
| `debug_move_learn_forget_prompt` | At "Make it forget another move?" prompt. "Forget a move!" / "Keep old moves!" buttons. |
| `debug_move_select_screen` | Move selection grid visible: Tackle/Withdraw/Absorb/Razor Leaf + Curse. For move forget UI testing. |
| `route202_grind_mid_session` | Route 202 (map 343). Mid-grind checkpoint. Piplup Lv7, Eevee Lv8, Shinx Lv7, Turtwig Lv12, Chimchar Lv8. |
| `route202_grind_complete` | Route 202 (map 343). Grind complete. Eevee Lv9 (holding Potion), Shinx Lv8, Piplup Lv8, Turtwig Lv12, Chimchar Lv8. |

## Renegade MCP Tools

Game-specific tools are provided by the `renegade` MCP server (defined in `renegade_mcp/`). These run alongside the generic `desmume` MCP server. All tools connect to the emulator via the bridge socket — if the emulator isn't initialized yet, they return a clear error.

| Tool | Purpose |
|------|---------|
| `read_party(refresh=false)` | Party Pokemon: species, level, HP, moves, PP, nature, IVs, EVs. `refresh=true` opens/closes party screen to force re-encryption (overworld only). |
| `read_battle` | Live battle state: all battlers with stats, moves, ability, types, status |
| `read_bag(pocket="")` | Bag contents across all 7 pockets. Optional pocket filter. |
| `view_map` | ASCII map with terrain, player position, NPCs |
| `map_name(map_id=-1)` | Location name lookup. Defaults to current map. |
| `navigate(directions)` | Manual walk: "d2 l3 u1" or "down down left left left" |
| `navigate_to(x, y)` | BFS pathfind to target tile, then walk there |
| `read_dialogue(region="auto")` | Read dialogue/battle text from RAM |
| `battle_turn(move_index, switch_to)` | Full automated turn: FIGHT + move OR POKEMON + switch. Returns battle log + state + read_battle data. |
| `throw_ball` | Throw a Poké Ball in wild battle: BAG + ball select + USE + catch result |
| `reorder_party(from_slot, to_slot)` | Swap two party Pokemon via pause menu (overworld only) |
| `decode_rom_message(file_index)` | Decode ROM message archive (species, moves, items, etc.) |
| `search_rom_messages(query)` | Search all 724 message files for text |
| `use_item(item_name, party_slot)` | Use a Medicine item on a party Pokemon from overworld |

The original Python scripts in `scripts/` still work for debugging but are no longer the primary interface.

## Navigation

**CRITICAL: Do not rely on screenshots for spatial reasoning in the overworld.** The isometric/overhead camera makes it very difficult to judge tile positions, room boundaries, and exits from pixel images. Instead:

- **Use `view_map`** to get a full map with terrain, player, and NPCs — all read live from the emulator.
- **Use `navigate` or `navigate_to`** to walk paths — they verify each step and stop on collision.
- **When stuck navigating, ask Michael for visual help** rather than brute-forcing positions.
- Screenshots are fine for reading dialogue, menus, and battle screens — just not for spatial navigation.

Multi-chunk maps (overworld, large caves) use a matrix/chunk system detected automatically by `view_map` and `navigate_to`. See MEMORY_MAP.md for collision data format, tile behaviors, and dynamic object details.

## Game State Tools

**Use these tools instead of navigating in-game menus** — faster, more reliable, no accidental inputs.

- **`read_party`** — full party data from encrypted RAM. Works in overworld + battle. Pass `refresh=true` to force re-encryption via party screen (overworld only) — guarantees full data when encrypted blocks are stale. See MEMORY_MAP.md for data format.
- **`read_bag`** — all 7 bag pockets. Pass `pocket="Key Items"` to filter.
- **`read_battle`** — live battle data for all active battlers. Returns empty if not in battle. See MEMORY_MAP.md for struct layout.
- **`map_name`** — location name from map ID. No args = current map.
- **`read_dialogue`** — text from RAM buffers. Pass `region="overworld"` or `"battle"` to target specific buffers.
- **`decode_rom_message(file_index)`** / **`search_rom_messages(query)`** — ROM data lookup (no emulator needed).

Key ROM file indices: 0392=items, 0412=species, 0610=abilities, 0647=moves, 0433=locations, 0646=move descriptions.

## Battle Workflow

### Automated (preferred)
1. **`read_battle`** — check enemy species, types, ability, stats, moves. Plan tactics.
2. **`battle_turn(move_index=N)`** — use a move (0-3). Waits for action prompt automatically, then executes. Returns battle log + final state + updated battle state.
   - Or **`battle_turn(switch_to=N)`** — switch to party slot N (0-5) instead of attacking.
   - Works on the very first turn of battle — no need to call twice.
3. Handle the returned state:
   - `WAIT_FOR_ACTION` — next turn, call `battle_turn` again. Battle state is included in the response.
   - `SWITCH_PROMPT` — trainer sending next Pokemon. Call `battle_turn(switch_to=N)` to swap, or `battle_turn()` to keep battling.
   - `FAINT_SWITCH` — your Pokemon fainted (wild battle). Call `battle_turn(switch_to=N)` to send replacement, or `battle_turn()` to flee.
   - `FAINT_FORCED` — your Pokemon fainted (trainer battle). Call `battle_turn(switch_to=N)` to send replacement (required).
   - `BATTLE_ENDED` — back in overworld.
   - `MOVE_LEARN` — Pokemon wants to learn a new move. Response includes `move_to_learn` and `current_moves` with slot indices. Call `battle_turn(forget_move=N)` to forget move N (0-3) and learn the new move, or `battle_turn(forget_move=-1)` to skip.
   - `NO_ACTION_PROMPT` — action prompt never appeared (~30 sec timeout). Game may need manual input.
   - `TIMEOUT` / `NO_TEXT` — something unexpected. Screenshot + `read_battle` to diagnose.

Note: `battle_turn` includes `read_battle` data in every response — no separate call needed.

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
- **Location**: Route 202 (map 343). Save state: `route202_grind_complete`.
- **Eevee** Lv9 — Gentle (+SpD/-Def), Run Away. Moves: Tackle, Tail Whip, Bite, Covet. Holding Potion (stolen via Covet).
- **Shinx** Lv8 — Jolly (+Spe/-SpA), Guts. Moves: Tackle, Leer, Howl, Quick Attack.
- **Piplup** Lv8 — Lax (+Def/-SpD), Vital Spirit. Moves: Pound, Growl, Bubble, Water Sport. Gift from Rowan's lab briefcase.
- **Turtwig** Lv12 — Naughty (+Atk/-SpD). Moves: Tackle, Curse, Absorb, Razor Leaf.
- **Chimchar** Lv8 — Careful (+SpD/-SpA), Iron Fist. Moves: Scratch, Leer, Ember, Taunt. Gift from Rowan's lab briefcase.
- **Key items**: Potion x1, Repel x10, Poke Ball x29, Bicycle, Poke Radar, Parcel (deliver to Barry).
- **Defeated trainers**: Youngster Tristan (Route 202). Lost to Youngster Logan (Route 202, Growlithe/Burmy/Zigzagoon).
- **Next**: Rematch Youngster Logan. Continue north to Jubilife City. Deliver Parcel to Barry.

See GAME_HISTORY.md for full chronological playthrough details.

## Quick Reference: Common Workflows

### Entering a new area
1. `map_name` — get map ID, location name, and coordinates
2. `view_map` — see the map layout, NPCs, exits

### Before/during battle
1. `read_battle` — enemy species, types, ability, stats, moves, HP
2. `battle_turn(move_index=0)` — use a move. Returns battle log + state + updated battle data.
3. Or `battle_turn(switch_to=1)` — switch Pokemon instead of attacking.

### Checking inventory/party (overworld)
1. `read_party` — full party with moves, PP, nature, IVs, EVs. Use `refresh=true` if data looks stale.
2. `read_bag` — all items across all pockets

### Using items (overworld)
1. `use_item("Potion", 0)` — uses a Medicine item on the specified party slot (0-indexed)
2. Handles full menu flow automatically: pause menu → Bag → Medicine → item → USE → party → dismiss

### Reordering party (overworld)
1. `reorder_party(0, 2)` — swap slot 0 and slot 2. Navigates pause menu automatically.

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- **Use `read_battle` at the start of every battle** — Renegade Platinum changes abilities and movesets from vanilla.
- Use `read_dialogue` to read text from memory — more reliable than timing screenshots.
- The `load_state` tool may occasionally hang — check `get_status` to verify.
- Addresses must be passed as decimal integers to DeSmuME MCP tools, not hex strings.
- **Touch screen taps default to `frames=8`** — changed from 1 to avoid missed inputs.
- **Wait 300 frames between UI navigation steps** — Pokemon ignores input during forced text delays.
- **Always check the bottom screen for Yes/No prompts** — battle/switch prompts use touch screen.
- **`battle_turn` has a built-in timeout** (150 polls / ~37 seconds) — returns TIMEOUT rather than hanging forever.
- **Pause menu remembers cursor position** — cursor index stored at `0x0229FA28`. The `use_item` tool reads this automatically; for manual menu navigation, read this address first.
- **Trainer battles may have multiple Pokemon** — handle "Will you switch?" prompt before next action.
