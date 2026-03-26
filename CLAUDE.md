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

| Buffer | Address | Context |
|--------|---------|---------|
| Overworld | `0x022A73BC` | NPC dialogue, signs, cutscene text |
| Battle | `0x02301BD0` | Move announcements, damage text, status effects |

Both buffers are preceded by the marker bytes `D2EC B6F8` and terminated by `0xFFFF`.

### Text Encoding (Gen 4)

16-bit little-endian characters:
- Uppercase A-Z: `0x012B` - `0x0144`
- Lowercase a-z: `0x0145` - `0x015E`
- Digits 0-9: `0x0161` - `0x016A` (assumed)
- Space: `0x01DE`
- `é`: `0x0188` (Pokémon)
- `!`: `0x01AB`, `,`: `0x01AD`, `.`: `0x01AE`, `'`: `0x01B3`
- Newline: `0xE000`, New text box: `0x25BC`, End: `0xFFFF`, Variable: `0xFFFE`

### Navigation Scripts (Bridge-Connected)

These scripts connect directly to the running MCP emulator via the IPC bridge — no manual arguments needed.

**Map visualization** — reads terrain, player state, and dynamic objects live:
```bash
python3 scripts/map_with_objects.py              # print to stdout
python3 scripts/map_with_objects.py map_view.txt  # write to file
```

**Automated walking** — moves one tile per direction, verifies each step, stops on collision:
```bash
python3 scripts/navigate.py down down left left left  # full names
python3 scripts/navigate.py d d l l l                  # shorthand (u/d/l/r)
```

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
- **Start**: Open menu (overworld)
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
- **Current point**: Twinleaf Town overworld (map 411), post-rival battle. Save state: `post_rival_battle_twinleaf`. Need to head north to Route 201 → Sandgem Town.
- **Pokemon**: Turtwig Lv6 (moves: Tackle, Withdraw, Absorb)
- **Starter**: Chose Turtwig. Barry chose Chimchar (type advantage). Michael says other starters join party before second town.
- **First battle**: Won vs Barry's Chimchar Lv5 in 4 turns using Tackle. Battle UI uses touch screen (FIGHT button → move selection).
- **Twinleaf Town layout** (overworld chunk 3,27): 4 houses. Player's house door at local (20,21) = global (116,885). Barry's house door at local (9,11) = global (105,875).
- **Notable**: There's an Eevee object at (4,3) in the living room. Interacting shows "It's an EEVEE! Mom is taking care of it." — Renegade Platinum likely gives this Eevee to the player at some point.

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- Use the `player_position` watch after every movement to confirm you moved.
- Use macros for repetitive sequences (dialogue, walking patterns).
- The `load_state` tool may occasionally hang without returning — check `get_status` to verify.
- Note: addresses must be passed as decimal integers to MCP tools, not hex strings. Use Python to convert: `python3 -c "print(0x0227F458)"`.
