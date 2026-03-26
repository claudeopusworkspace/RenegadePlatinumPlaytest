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

## Renegade MCP Tools

Game-specific tools are provided by the `renegade` MCP server (defined in `renegade_mcp/`). These run alongside the generic `desmume` MCP server. All tools connect to the emulator via the bridge socket — if the emulator isn't initialized yet, they return a clear error.

| Tool | Purpose |
|------|---------|
| `read_party` | Party Pokemon: species, level, HP, moves, PP, nature, IVs, EVs |
| `read_battle` | Live battle state: all battlers with stats, moves, ability, types, status |
| `read_bag(pocket="")` | Bag contents across all 7 pockets. Optional pocket filter. |
| `view_map` | ASCII map with terrain, player position, NPCs |
| `map_name(map_id=-1)` | Location name lookup. Defaults to current map. |
| `navigate(directions)` | Manual walk: "d2 l3 u1" or "down down left left left" |
| `navigate_to(x, y)` | BFS pathfind to target tile, then walk there |
| `read_dialogue(region="auto")` | Read dialogue/battle text from RAM |
| `battle_init` | Snapshot text baseline at battle start |
| `battle_poll(auto_press=false)` | Poll for turn narration after selecting a move |
| `decode_rom_message(file_index)` | Decode ROM message archive (species, moves, items, etc.) |
| `search_rom_messages(query)` | Search all 724 message files for text |

The original Python scripts in `scripts/` still work for debugging but are no longer the primary interface.

## Navigation

**CRITICAL: Do not rely on screenshots for spatial reasoning in the overworld.** The isometric/overhead camera makes it very difficult to judge tile positions, room boundaries, and exits from pixel images. Instead:

- **Use `view_map`** to get a full map with terrain, player, and NPCs — all read live from the emulator.
- **Use `navigate` or `navigate_to`** to walk paths — they verify each step and stop on collision.
- **When stuck navigating, ask Michael for visual help** rather than brute-forcing positions.
- Screenshots are fine for reading dialogue, menus, and battle screens — just not for spatial navigation.

## Party Status

**Use `read_party` to read party Pokemon directly from RAM** — no menu navigation needed. Returns structured data with species, moves, PP, nature, IVs, EVs, plus a formatted text summary.

Uses TWO data sources:
1. **Encrypted Gen 4 party data** at `0x0227E26C` (count) / `0x0227E270` (236 bytes/slot) — species, moves, PP, nature, item, friendship, EXP. Always available (overworld + battle).
2. **Party summary structure** at `0x022C0130` (44 bytes/slot) — current HP, max HP, level. Overworld only (zeroed during battle/menus).

The encrypted data uses standard Gen 4 format: PID + checksum + 4 shuffled/encrypted 32-byte blocks. Decryption: PRNG seeded by checksum; block shuffle index = `((PID >> 13) & 0x1F) % 24`.

## Bag / Inventory

**Use `read_bag` to read bag contents directly from RAM** — no menu navigation needed. Pass `pocket="Key Items"` to filter to a specific pocket.

Reads 7 pockets from `0x0227E800` (1844 bytes total). Each pocket is an array of `(item_id u16, qty u16)` pairs:

| Pocket | Max Slots | Offset |
|--------|-----------|--------|
| Items | 165 | 0x000 |
| Key Items | 50 | 0x294 |
| TMs & HMs | 100 | 0x35C |
| Mail | 12 | 0x4EC |
| Medicine | 40 | 0x51C |
| Berries | 64 | 0x5BC |
| Battle Items | 30 | 0x6BC |

## Battle State

**Use `read_battle` to read live battle data from RAM** — species, stats, HP, moves, PP, stat stages, types, ability, and status for all active battlers. Returns structured data plus a formatted summary. Returns empty if not in battle.

Reads from `0x022C5774` (4 slots × 0xC0 bytes). Key fields per battler:

| Field | Offset | Size | Notes |
|-------|--------|------|-------|
| Species | +0x00 | u16 | National Dex # |
| Atk/Def/Spe/SpA/SpD | +0x02-0x0A | u16 each | Effective stats (after nature) |
| Moves | +0x0C | u16 × 4 | Move IDs |
| Stat stages | +0x18 | u8 × 8 | Atk,Def,Spe,SpA,SpD,Acc,Eva,Crit; neutral=6 |
| Weight | +0x20 | u16 | In 0.1 kg units |
| Types | +0x24 | u8 × 2 | Gen 4 internal type IDs |
| Ability | +0x27 | u8 | Ability ID |
| Status | +0x28 | u32 | Bitfield (sleep/psn/brn/frz/par/tox) |
| PP | +0x2C | u8 × 4 | Current PP per move |
| Level | +0x34 | u8 | |
| Current HP | +0x4C | u16 | Live battle HP |
| Max HP | +0x50 | u16 | |

Slot 0 = player active, Slot 1 = enemy active, Slots 2-3 = doubles partners. Outside of battle, all slots contain stale/invalid data (detected automatically).

## Map Name Lookup

**Use `map_name` to identify maps by ID** — no more guessing which building you're in. Call with no arguments to get the current map, or pass `map_id=414` to look up a specific ID.

Map IDs → location names are derived from ROM data (`romdata/mapname.bin`). Indoor maps show the area code (e.g., `T01R0201` = Twinleaf Town, Room 2, Floor 1).

## ROM Message Decoder

**Use `decode_rom_message(file_index)` to decode ROM message archives** and `search_rom_messages(query)` to search across all files. These do not require the emulator — they read directly from ROM data.

Key file indices:
| File | Content |
|------|---------|
| 0392 | Item names (index = item ID) |
| 0412 | Pokemon species names (index = national dex #) |
| 0610 | Ability names (index = ability ID) |
| 0647 | Move names (index = move ID) |
| 0433 | Location/map names |
| 0646 | Move descriptions |

## Dialogue & Text Reading

**Use `read_dialogue` to read text directly from RAM** — no need to time screenshots or mash through dialogue blindly. Pass `region="auto"` (default), `"overworld"`, or `"battle"` to control which buffer is scanned.

### Text Buffers

| Region | Scan range | Context |
|--------|-----------|---------|
| Overworld | `0x022A7000` - `0x022A9800` | NPC dialogue, signs, cutscene text |
| Battle | `0x022FF000` - `0x02303000` | Move announcements, damage text, status effects |

Text is stored in slots preceded by the marker `D2EC B6F8` and terminated by `0xFFFF`. The overworld buffer address is **dynamic** — it shifts between slots depending on the dialogue context (e.g., `0x022A73BC` for NPC dialogue, `0x022A77FC` for cutscenes). The battle buffer is also **dynamic** — it shifts between `~0x022FF000` (wild battles) and `~0x02301BD0` (trainer battles). Both scripts scan for active marker slots automatically.

### Battle Text Indicators

The last value(s) before `[END]` indicate whether the game auto-advances or waits:
- **No trailing control code** (e.g., `! [END]`) → auto-advancing narration
- **`0xE000` before `[END]`** → game waits for B press to dismiss
- **`0xFFFE` sequence before `[END]`** → game waits for player action (move selection, etc.)

**Battle turn logger** — two-step workflow for capturing battle narration:
1. **`battle_init`** — Run ONCE at the start of each battle (after battle screen loads). Snapshots pre-existing text markers as baseline. State is held in memory (no temp files).
2. **`battle_poll(auto_press=true)`** — Run after selecting a move. Polls until a stopping point. With `auto_press=true`, auto-dismisses mid-battle dialogue (trainer taunts) and continues until the action prompt.

### Text Encoding (Gen 4)

16-bit little-endian characters:
- Uppercase A-Z: `0x012B` - `0x0144`
- Lowercase a-z: `0x0145` - `0x015E`
- Digits 0-9: `0x0161` - `0x016A` (assumed)
- Space: `0x01DE`
- `é`: `0x0188` (Pokémon)
- `!`: `0x01AB`, `?`: `0x01AC`, `,`: `0x01AD`, `.`: `0x01AE`, `'`: `0x01B3`, `:`: `0x01C4`
- Newline: `0xE000`, New text box: `0x25BC`, End: `0xFFFF`, Variable: `0xFFFE`

### Navigation Tools

**`view_map`** — reads terrain, player state, and dynamic objects live. Returns ASCII map with legend.

**`navigate(directions)`** — manual walking. Accepts space-separated directions with optional repeat counts: `"d2 l3 u1"`, `"down down left"`, etc. Moves one tile per direction (16 frames hold + 8 frames wait), verifies each step, stops if blocked.

**`navigate_to(x, y)`** — BFS pathfinding. Reads terrain + dynamic objects, computes shortest path, executes it step by step. Supports both local (0-31) and global coordinates — global coords are auto-detected and trigger multi-chunk terrain loading (up to 5x5 chunks = 160x160 tiles). Ledge tiles (0x38-0x3B) are treated as one-way passable in the correct direction. NPC tiles are blocked. Does not cross map boundaries (warps).

### Movement Timing
- 1 tile = 16 frames of holding a direction, then release and wait ~8 frames for the step to complete.
- `navigate` and `navigate_to` handle this automatically.
- The walk macros (`walk_up/down/left/right`) use 32-frame holds and move **2 tiles** per execution.

### Map Collision Data

#### Indoor Maps
The current map's terrain attributes (collision grid) are loaded in RAM at **`0x0231D1E4`** (decimal: 36819428). This is a fixed address — the game loads whichever map's data is active into this slot.

**Format:** 2048 bytes = 32x32 grid of `u16` (little-endian), row-major.
- **Bit 15** (`0x8000`): Collision flag. **1 = impassable, 0 = passable.** This is the authoritative source for pathfinding — no need to check individual behavior values.
- **Bits 0-7** (`0x00FF`): Tile behavior (door, stairs, water, etc.). See "Tile Behaviors" section below.
- Coordinate offset is **(0, 0)** — grid coords match game coords directly.

#### Multi-Chunk Maps (Overworld, Large Caves, etc.)
When player coordinates exceed 31 (or RAM terrain is empty), the map uses a **matrix/chunk system**:

- Maps are composed of a grid of **32×32-tile chunks** (e.g., the Sinnoh overworld is 30×30 chunks via matrix 0).
- Player global coords map to chunks: `chunk = (x÷32, y÷32)`, local = `(x%32, y%32)`.
- Each chunk's terrain is stored in a ROM file: `romdata/land_data/XXXX.bin`.
- Matrix files (`romdata/map_matrix/XXXX.bin`) map chunk positions to land_data file IDs.
- `view_map` **detects this automatically** — it searches all matrix files for the current map ID.
- The tool displays **local chunk coordinates (0-31)** with the chunk offset printed in the header.
- This works for any multi-chunk map: overworld, large caves, dungeons, etc.

**Important caveats:**
- Dynamic objects (NPCs, items on the floor) are NOT in the static grid. Use `view_map` to see both.
- `navigate`/`navigate_to` are the most robust navigation methods — they try each step and check the result, catching dynamic blockers and edge cases that the static grid alone would miss.
- Overworld door tiles (`0x69`) are marked as blocked in terrain but the warp system overrides collision.

### Dynamic Objects (Overworld Object Array)

NPCs, floor items, and the player are stored in an array in RAM. Each entry is **0x128 (296) bytes** apart.

| Field | Offset from entry base | Size | Notes |
|-------|----------------------|------|-------|
| Fixed-point X | +0x00 | long | Upper 16 bits = tile X, lower 16 = sub-tile |
| Fixed-point Y | +0x08 | long | Upper 16 bits = tile Y, lower 16 = sub-tile |

**Entry 0 (player)** fixed-point X is at `0x022A1AA8`. Subsequent entries are at `+0x128` intervals.

- Entry 0 = player, Entry 1+ = NPCs/objects on current map.
- Entries with fpx=0 and fpy=0 are empty/inactive.
- `view_map` reads this automatically — player shows as `^v<>`, NPCs/objects as `A`, `B`, `C`, etc.

### Tile Behaviors

**Passability is determined by bit 15, not the behavior value.** The behavior byte tells us what *special effect* a tile has, not whether we can walk on it.

#### Known Warp/Transition Tiles

These tiles are **passable** (bit 15 = 0). You walk *onto* the tile, then press a specific direction to activate the transition.

| Behavior | Name | Activation | Example |
|----------|------|------------|---------|
| `0x5F` | Stairs (down) | Stand on tile, walk **left** | Living room (10,3) → bedroom upstairs |
| `0x65` | Door / Exit | Stand on tile, walk **down** | Living room (6,10) → exit house |

#### Known Blocked Tiles

These tiles are **impassable** (bit 15 = 1) but may have special behavior.

| Behavior | Name | Notes |
|----------|------|-------|
| `0x69` | Door (overworld) | House entrances on overworld maps. Marked blocked but warp system overrides collision — walk into the tile to enter. |
| `0x80` | Counter | Kitchen counter, can interact across it |

#### Other Known Behaviors (encountered in gameplay)

| Behavior | Name | Notes |
|----------|------|-------|
| `0x02` | Tall grass | Wild encounters. Passable but triggers random battles. |
| `0x21` | Sand/beach | Passable, decorative. Seen in Sandgem Town. |
| `0x3B` | Ledge (east) | One-way east jump. Blocked bit set. Route 201/202 shortcuts. |
| `0xA9` | Tree tile | Decorative trees on overworld, passable. |

#### Other Behaviors (not yet encountered in gameplay)

| Behavior | Name | Expected |
|----------|------|----------|
| `0x10` | Water | Requires Surf |
| `0x38`-`0x3A` | Ledges (S/N/W) | One-way jumps |
| `0x5E` | Stairs (up) | Likely walk **right** to activate? (unconfirmed) |
| `0x62` | Warp | Generic warp tile |

*This table will grow as we encounter new tile types during the playthrough.*

## Player Watches

```
read_watch("player_position")  # → map_id, x, y, prev_x, prev_y
read_watch("player_facing")    # → facing (0=up, 1=down, 2=left, 3=right)
```

| Watch | Base Address | Fields |
|-------|-------------|--------|
| `player_position` | `0x0227F450` | map_id, x, y, prev_x, prev_y |
| `player_facing` | `0x02335346` | facing (with display transform) |

See MEMORY_MAP.md for full address documentation.

## DS Screen Layout

- **Top screen** (256x192): Main game display.
- **Bottom screen** (256x192): Touch-enabled, used for menus, Pokemon selection, etc.
- Screenshots with `screen="both"` show both stacked vertically (256x384).

## Input Reference

**Buttons:** a, b, x, y, l, r, start, select, up, down, left, right

- **A**: Confirm / advance dialogue / interact with overworld objects. Use `press_buttons(["a"], frames=8)` — the game needs a few frames of sustained input to register.
- **B**: Cancel / back / advance dialogue. **Prefer B over A for advancing dialogue** — B progresses text just like A but won't accidentally trigger a new interaction with a nearby NPC or object when the dialogue ends.
- **X**: Open menu (overworld). **Use X, not Start** — Start does not open the menu in Platinum.
- **Start**: Does NOT open the menu in Platinum.
- **D-pad**: Move character / navigate menus
- **Touch screen**: Tap targets on bottom screen. **Always use `get_screenshot(screen="bottom")` to estimate coordinates**, as the combined "both" view distorts positions.

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
| `mash_b` | Press B 5 times (8-frame holds, 30-frame waits) for dialogue — safer than A, avoids re-triggering NPCs |
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

### Dump Memory (for offline analysis)
`dump_memory(address=0x02200000, size=1048576, file_path="/workspace/.../dump.bin")`
Then analyze with Python scripts.

## Game Progress

- **Character name**: CLAUDE
- **Rival name**: AAAAAAA (mashed through naming screen)
- **Current point**: Route 202 (map 343) at (181, 819). Midway through route, after beating Youngster Tristan. Save state: `route202_post_tristan_healed`.
- **Pokemon**: Turtwig Lv11 (31/35 HP, Naughty +Atk/-SpD, moves: Tackle, Curse, Absorb, Razor Leaf), Eevee Lv5 (21/21 HP, Gentle +SpD/-Def, moves: Tackle, Tail Whip, Bite, Covet, ability: Run Away).
- **Starter**: Chose Turtwig. Barry chose Chimchar (type advantage). Other starters NOT yet received — may come later.
- **Eevee**: Obtained from Poke Ball in player's house after Mom's dialogue. Lv5 with Bite (Dark, 30% flinch) and Covet (Normal) as notable moves. Needs leveling — hasn't seen much combat since the Pidgey fight on Route 201.
- **Items**: Potion x8, Repel x10, Poke Ball x30, Bicycle, Poke Radar, Journal, Parcel (deliver to Barry).
- **Route 201 notes**: Tall grass is unavoidable in the middle section (big patch columns 10-20). Wild encounters: Starly Lv4-5, Pidgey Lv4, Nidoran(M) Lv5, Nidoran(F) Lv4. One whiteout occurred previously (Nidoran KO'd Turtwig at 1 HP).
- **Route 201 navigation**: Path from Twinleaf to Sandgem goes north out of Twinleaf (cols 14-17), then east through Route 201. South corridor from Twinleaf exits at ~(111, 864). Route goes east through open areas and tall grass to Sandgem Town.
- **Lake Verity**: Visited per story requirement. Met Cyrus (ominous speech about time/space). Barry wanted to catch legendary but had no Poke Balls.
- **Sandgem Town**: Dawn gave town tour (Pokemon Center, Mart). Rowan gave Poke Radar + Repels outside lab. Pokemon Center door at (177, 842). North exit to Route 202 on the east side (cols 180-189).
- **Route 202**: Dawn battled us with Piplup Lv9 at the entrance (not a catching tutorial — this is Renegade Platinum). Gave 30 Poke Balls after. Youngster Tristan has Hoothoot Lv7 + Starly Lv7. Wild encounters include Zigzagoon Lv5 (Gluttony). More trainers and grass ahead.
- **Route 202 wild Pokemon observed**: Zigzagoon Lv5 (Normal, Gluttony).
- **Route 202 trainers defeated**: Dawn (Piplup Lv9), Youngster Tristan (Hoothoot Lv7 + Starly Lv7).
- **Next**: Continue north through Route 202 to Jubilife City. Still need to deliver Parcel to Barry. Eevee needs leveling badly — consider leading with Eevee against weaker wild Pokemon or switching in for EXP.

## Quick Reference: Common Workflows

### Entering a new area
1. `map_name` — get map ID, location name, and coordinates
2. `view_map` — see the map layout, NPCs, exits

### Before/during battle
1. `read_battle` — see enemy species, types, ability, stats, moves, and HP. **Do this at battle start** to plan tactics (especially important in this difficulty hack — enemy abilities and movesets may be changed from vanilla).
2. `battle_init` — snapshot text baseline (once per battle)
3. Select move, then `battle_poll(auto_press=true)` — get full turn narration
4. `read_battle` — check updated HP, PP, stat stages, status after the turn

### Checking inventory/party (overworld)
1. `read_party` — full party with moves, PP, nature, IVs, EVs
2. `read_bag` — all items across all pockets

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- **Use `read_battle` at the start of every battle** — it reveals the enemy's ability, types, moves, and stats. Renegade Platinum changes many of these from vanilla (e.g., Chimchar has Iron Fist instead of Blaze).
- **Use `read_bag` instead of navigating the bag menu** — faster and avoids accidental inputs.
- **Use `read_party` instead of the party menu** — shows everything including IVs/EVs without menu navigation.
- Use `read_dialogue` to read full dialogue text from memory — far more reliable than timing screenshots.
- Use `battle_poll(auto_press=true)` after selecting a move to get the full turn log automatically.
- Use macros for repetitive sequences (dialogue, walking patterns).
- The `load_state` tool may occasionally hang without returning — check `get_status` to verify.
- Note: addresses must be passed as decimal integers to DeSmuME MCP tools, not hex strings.
- **Touch screen taps need `frames=8`** — single-frame taps (default) often don't register. Always use 8-frame holds for touch input.
- **Wait 300 frames between UI navigation steps** — Pokemon has forced text scroll delays before accepting input. Pressing buttons during these delays wastes them.
- **Always check the bottom screen for Yes/No prompts** — in battle, move-learning, and switch prompts use the bottom touch screen, not the top.
- **NEVER call `battle_poll` without first selecting a move** — it polls for NEW text, so if no action was taken, it loops forever. Always: select move → verify Pokeball screen → THEN poll.
- **`battle_poll` may stall on KO turns** — the tool has a built-in MAX_POLLS limit (300 polls = ~75 seconds) so it will eventually return with TIMEOUT state rather than hanging forever.
- **Pause menu remembers cursor position** — don't assume it starts on a specific item. Check the screenshot before pressing A.
- **Trainer battles may have multiple Pokemon** — after a KO, the game asks "Will you switch?" with touch buttons on the bottom screen. Handle this before the next action prompt.
