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
| `wild_starly_battle_start` | Wild Starly Lv4 battle on Route 201. For debugging battle_poll.py. Turtwig Lv7. |
| `post_wipe_home_healed` | After whiteout, back in living room. Turtwig Lv7 26/26 HP. |
| `sandgem_town_arrival` | Just entered Sandgem Town (map 418). Turtwig Lv7. |
| `got_pokedex_rowan_lab` | Inside Rowan's lab (map 422) after receiving Pokedex. Free to move. |
| `sandgem_pokemon_center_healed` | Outside Sandgem Pokemon Center (map 418). Turtwig Lv8 healed. |
| `got_eevee_twinleaf` | In player's house (map 414) after obtaining Eevee. Turtwig Lv8, Eevee Lv5. |

## Navigation

**CRITICAL: Do not rely on screenshots for spatial reasoning in the overworld.** The isometric/overhead camera makes it very difficult to judge tile positions, room boundaries, and exits from pixel images. Instead:

- **Use `map_with_objects.py`** to get a full map with terrain, player, and NPCs — all read live from the emulator.
- **Use `navigate.py`** to walk paths — it verifies each step and stops on collision.
- **When stuck navigating, ask Michael for visual help** rather than brute-forcing positions.
- Screenshots are fine for reading dialogue, menus, and battle screens — just not for spatial navigation.

## Dialogue & Text Reading

**Use `read_dialogue.py` to read text directly from RAM** — no need to time screenshots or mash through dialogue blindly. The script reads decoded text buffers and handles both overworld and battle contexts.

```bash
python3 scripts/read_dialogue.py              # auto-detect active text (overworld or battle)
python3 scripts/read_dialogue.py --battle     # force read battle buffer
python3 scripts/read_dialogue.py --overworld  # force read overworld buffer
python3 scripts/read_dialogue.py --raw        # show raw hex values for debugging
```

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
```bash
# Step 1: Run ONCE at the start of each battle (after battle screen loads)
python3 scripts/battle_init.py          # snapshots pre-existing text markers as baseline

# Step 2: Run after selecting a move to capture the turn
python3 scripts/battle_poll.py          # poll until next stop (returns at WAIT_FOR_INPUT or WAIT_FOR_ACTION)
python3 scripts/battle_poll.py --press  # auto-dismiss trainer mid-battle dialogue, stop at action prompt
```

### Text Encoding (Gen 4)

16-bit little-endian characters:
- Uppercase A-Z: `0x012B` - `0x0144`
- Lowercase a-z: `0x0145` - `0x015E`
- Digits 0-9: `0x0161` - `0x016A` (assumed)
- Space: `0x01DE`
- `é`: `0x0188` (Pokémon)
- `!`: `0x01AB`, `?`: `0x01AC`, `,`: `0x01AD`, `.`: `0x01AE`, `'`: `0x01B3`, `:`: `0x01C4`
- Newline: `0xE000`, New text box: `0x25BC`, End: `0xFFFF`, Variable: `0xFFFE`

### Navigation Scripts (Bridge-Connected)

These scripts connect directly to the running MCP emulator via the IPC bridge — no manual arguments needed.

**Map visualization** — reads terrain, player state, and dynamic objects live:
```bash
python3 scripts/map_with_objects.py              # print to stdout
python3 scripts/map_with_objects.py map_view.txt  # write to file
```

**Automated walking** — moves one tile per direction, verifies each step, stops if position unchanged:
```bash
python3 scripts/navigate.py down down left left left  # manual: full names
python3 scripts/navigate.py d d l l l                  # manual: shorthand (u/d/l/r)
python3 scripts/navigate.py l20 u5 r3                  # manual: repeat counts
python3 scripts/navigate.py --to 6 10                  # auto: BFS pathfind to tile (local coords)
```
Auto mode reads terrain + dynamic objects, computes shortest path via BFS, and executes it. Uses local/chunk coordinates (0-31). Treats NPC tiles as blocked. Does not cross map boundaries.

**Legacy manual rendering** (if bridge is unavailable):
```bash
dump_memory(address=36819428, size=2048, file_path="terrain.bin")
python3 scripts/render_map.py terrain.bin <x> <y> <facing> nav_view.txt
```

### Movement Timing
- 1 tile = 16 frames of holding a direction, then release and wait ~8 frames for the step to complete.
- `navigate.py` handles this automatically.
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
- `map_with_objects.py` **detects this automatically** — it searches all matrix files for the current map ID.
- The script displays **local chunk coordinates (0-31)** with the chunk offset printed in the header.
- This works for any multi-chunk map: overworld, large caves, dungeons, etc.

**Important caveats:**
- Dynamic objects (NPCs, items on the floor) are NOT in the static grid. Use `map_with_objects.py` to see both.
- `navigate.py` is the most robust navigation method — it tries each step and checks the result, catching dynamic blockers and edge cases that the static grid alone would miss.
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
- `map_with_objects.py` reads this automatically — player shows as `^v<>`, NPCs/objects as `A`, `B`, `C`, etc.

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

#### Other Behaviors (not yet encountered in gameplay)

| Behavior | Name | Expected |
|----------|------|----------|
| `0x02` | Tall grass | Wild encounters |
| `0x10` | Water | Requires Surf |
| `0x38`-`0x3B` | Ledges | One-way jumps (S/N/W/E) |
| `0x5E` | Stairs (up) | Likely walk **right** to activate? (unconfirmed) |
| `0x62` | Warp | Generic warp tile |
| `0xA9` | Tree tile | Decorative trees on overworld, passable |

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
- **Current point**: Twinleaf Town, player's house (map 414). Just obtained Eevee. Save state: `got_eevee_twinleaf`.
- **Pokemon**: Turtwig Lv8 (28/28 HP, moves: Tackle, Withdraw, Absorb), Eevee Lv5 (21/21 HP, moves: Tackle, Tail Whip, Bite, Covet). Eevee nature: Gentle (+SpD, -Def), ability: Run Away.
- **Starter**: Chose Turtwig. Barry chose Chimchar (type advantage). Other starters NOT yet received — may come later.
- **Eevee**: Obtained from Poke Ball in player's house after Mom's dialogue. Lv5 with Bite (Dark) and Covet (Normal) as notable moves.
- **Items received this session**: Poke Radar (key item), Repels, Potions (from Mart NPC on Route 201). Barry's mom gave us a Parcel to deliver to Barry.
- **Route 201 notes**: Tall grass is unavoidable in the middle section (big patch columns 10-20). Wild encounters: Starly Lv4-5, Pidgey Lv4, Nidoran(M) Lv5, Nidoran(F) Lv4. One whiteout occurred previously (Nidoran KO'd Turtwig at 1 HP).
- **Route 201 navigation**: Path from Sandgem to Twinleaf goes west through tall grass, then south through a corridor at global coords ~(110, 858-863) to reach Twinleaf Town. Ledge barriers block direct south access from the main path — must go west into Verity Lakefront area, jump south ledge, then east and south to the corridor.
- **Lake Verity**: Visited per story requirement. Met Cyrus (ominous speech about time/space). Barry wanted to catch legendary but had no Poke Balls.
- **Sandgem Town**: Dawn gave town tour (Pokemon Center, Mart). Rowan gave Poke Radar + Repels outside lab.
- **Next**: Head back to Sandgem Town, then north to Route 202. Need to deliver Parcel to Barry (he's somewhere ahead).

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- Use the `player_position` watch after every movement to confirm you moved.
- Use `read_dialogue.py` to read full dialogue text from memory — far more reliable than timing screenshots.
- Use `battle_poll.py --press` after selecting a move to get the full turn log automatically.
- Use macros for repetitive sequences (dialogue, walking patterns).
- The `load_state` tool may occasionally hang without returning — check `get_status` to verify.
- Note: addresses must be passed as decimal integers to MCP tools, not hex strings. Use Python to convert: `python3 -c "print(0x0227F458)"`.
