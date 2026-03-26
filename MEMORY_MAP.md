# Renegade Platinum - Memory Map

Known RAM addresses for game state. All addresses are for the US Platinum ROM running in DeSmuME.
These should be stable across sessions when using the same ROM + save states.

## Player Overworld State

These are runtime addresses used by the game engine's overworld system (not save file offsets).
The player struct starts around `0x0227F400` with a sentinel `0xBEEFCAFE` at the end.

| Address      | Size | Field   | Notes |
|-------------|------|---------|-------|
| `0x0227F450` | long | Map ID  | Current map/room number. Twinleaf bedroom = 415. |
| `0x0227F458` | long | X position (tiles) | Increases when moving right, decreases left. 1 unit = 1 tile. |
| `0x0227F45C` | long | Y position (tiles) | Increases when moving down, decreases up. 1 unit = 1 tile. |
| `0x0227F478` | long | Map ID (copy) | Same as 0x0227F450. Purpose of second copy unclear. |
| `0x0227F480` | long | X position (copy) | Often holds a slightly different (possibly previous?) X value. |
| `0x0227F484` | long | Y position (copy) | Often holds a slightly different (possibly previous?) Y value. |

### Player Struct Context

```
0x0227F400: [zeros...]
0x0227F450: map_id, 0x0000, 0xFFFFFFFF, X, Y, [zeros...]
0x0227F478: map_id, 0x0000, 0xFFFFFFFF, X2, Y2, [zeros...]
0x0227F4BC: 0x00040001, [zeros...]
...
0x0227F4F8: 0xBEEFCAFE (sentinel/debug marker)
```

### Discovery Method
Found via snapshot/diff: snapshot RAM at position A, walk one direction, snapshot at position B, diff.
Cross-referenced right-only vs down-only changes to isolate X and Y axes.

### Related Addresses (unconfirmed purpose)

| Address      | Size | Behavior | Hypothesis |
|-------------|------|----------|------------|
| `0x0227E1F4` | long | +2 per move regardless of direction | Step/movement counter |
| `0x0227E25C` | long | +256 per move regardless of direction | Packed step counter? (high byte increments) |
| `0x022A1A90` | long | Same value as X, changes on right only | Mirror/copy of X (possibly rendering) |
| `0x022A1A9C` | long | Same value as X, changes on right only | Mirror/copy of X |
| `0x022A1A98` | long | Same value as Y, changes on down only | Mirror/copy of Y (possibly rendering) |
| `0x022A1AA4` | long | Same value as Y, changes on down only | Mirror/copy of Y |

## Movement Timing

- DS runs at 60fps
- One tile of walking = ~16 frames of holding a direction
- 32-frame hold = 2 tiles of movement
- Walk macros (32 frame hold + 4 frame wait) move 2 tiles per execution

## Map Data Structures

### Map Header Table
Located at approximately `0x020EFD64`. Each entry is 8 bytes:

| Offset | Size  | Field |
|--------|-------|-------|
| +0     | short | Map ID |
| +2     | short | Data size / entry count |
| +4     | long  | Pointer to map event/script data |

Example entries:
- Map 415: size=20, pointer=`0x020EFF0C`
- Map 416: size=27, pointer=`0x020EFFA4`

### Map Index Table
Located at approximately `0x020E7F88`. Each entry appears to be 12 bytes:

| Offset | Size  | Field |
|--------|-------|-------|
| +0     | short | Map ID |
| +2     | short | Matrix index? (sequential values 902, 903...) |
| +4     | short | Tileset index? (sequential values 400, 401...) |
| +6     | short | Unknown (1021, 1009...) |

### Terrain Attributes / Collision Grid
**Status: SOLVED.**

| Address      | Size | Field |
|-------------|------|-------|
| `0x0231D1E4` | 2048 bytes | Current map's terrain attribute grid (32x32 u16, little-endian, row-major) |

The game loads the active map's terrain attributes from `land_data.narc` (ROM filesystem: `fielddata/land_data/land_data.narc`) into this fixed RAM slot. When the map changes, this data is replaced.

**Per-tile format (u16):**
- Bit 15 (`0x8000`): Collision flag. 1 = impassable, 0 = passable.
- Bits 0-7 (`0x00FF`): Tile behavior (door=`0x65`, stairs=`0x5F`, counter=`0x80`, water=`0x10`, etc.).

**Grid-to-game coordinate offset: (0, 0)** — grid position maps directly to game coordinates.

**Caveats:**
- Dynamic objects (NPCs, floor items) are NOT in the static grid.
- Stair tiles may show as blocked (`0x8000`) but allow passage via dynamic events.
- Zone ID ≠ land_data NARC index (e.g., zone 414 = land_data 186, zone 415 = land_data 187). The mapping is done via a header table in the ARM9. Since we read terrain directly from RAM, this mapping is only needed for offline analysis.

**ROM source:** `fielddata/land_data/land_data.narc` contains 666 map files. Each file has a 16-byte header (4 u32: terrain_size, props_size, model_size, bdhc_size) followed by the terrain grid at offset 0x10. Confirmed against the `pret/pokeplatinum` decompilation.

### Player Facing Direction

| Address      | Size | Field |
|-------------|------|-------|
| `0x02335346` | byte | Facing direction: 0=up, 1=down, 2=left, 3=right |

## Encrypted Party Data (Gen 4)

The game stores party Pokemon in encrypted Gen 4 format. Count at `0x0227E26C`, data at `0x0227E270` (236 bytes per slot, up to 6 slots).

Each slot: PID (4 bytes) + checksum (2 bytes) + 4 shuffled/encrypted 32-byte blocks (A/B/C/D).

**Decryption:** PRNG seeded by checksum. Each 16-bit value XOR'd with successive PRNG outputs.
**Block shuffle:** Index = `((PID >> 13) & 0x1F) % 24`. Maps to one of 24 permutations of blocks A/B/C/D.

**Block contents (after decryption + unshuffle):**
- **Block A (Growth):** Species, held item, EXP, friendship, ability
- **Block B (Moves):** Move IDs (u16 x4), PP (u8 x4), PP-Ups
- **Block C (EVs):** HP/Atk/Def/Spe/SpA/SpD EVs, contest stats
- **Block D (Misc):** Nature (from PID in Gen 4), origin info, IVs (packed u32)

This data is always available (overworld + battle). See also Party Summary Structure below for the runtime overlay with current HP/level.

## Bag Data

Base address: `0x0227E800` (1844 bytes total). Each pocket is an array of `(item_id u16, qty u16)` pairs.

| Pocket | Max Slots | Offset from Base |
|--------|-----------|-----------------|
| Items | 165 | 0x000 |
| Key Items | 50 | 0x294 |
| TMs & HMs | 100 | 0x35C |
| Mail | 12 | 0x4EC |
| Medicine | 40 | 0x51C |
| Berries | 64 | 0x5BC |
| Battle Items | 30 | 0x6BC |

## Battle Battler Struct

Base address: `0x022C5774`. 4 slots x `0xC0` (192) bytes each. Slot 0 = player active, Slot 1 = enemy active, Slots 2-3 = doubles partners.

| Field | Offset | Size | Notes |
|-------|--------|------|-------|
| Species | +0x00 | u16 | National Dex # |
| Atk | +0x02 | u16 | Effective stat (after nature) |
| Def | +0x04 | u16 | |
| Spe | +0x06 | u16 | |
| SpA | +0x08 | u16 | |
| SpD | +0x0A | u16 | |
| Moves | +0x0C | u16 x 4 | Move IDs |
| Stat stages | +0x18 | u8 x 8 | Atk,Def,Spe,SpA,SpD,Acc,Eva,Crit; neutral=6 |
| Weight | +0x20 | u16 | In 0.1 kg units |
| Types | +0x24 | u8 x 2 | Gen 4 internal type IDs |
| Ability | +0x27 | u8 | Ability ID |
| Status | +0x28 | u32 | Bitfield (sleep/psn/brn/frz/par/tox) |
| PP | +0x2C | u8 x 4 | Current PP per move |
| Level | +0x34 | u8 | |
| Current HP | +0x4C | u16 | Live battle HP |
| Max HP | +0x50 | u16 | |

Outside of battle, all slots contain stale/invalid data (detected automatically by `read_battle`).

## Party Summary Structure

**Status: PARTIALLY SOLVED.** Species, level, and HP are confirmed. Move data and some fields are still unknown.

The game maintains a party summary array at `0x022C0130`. Each slot is **44 bytes (0x2C)**, up to 6 party members. Empty slots have species = 0.

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| +0x00 | long | Data pointer | Points to full PokePara tree structure |
| +0x04 | u16 | Species | National Dex number (e.g., 387 = Turtwig) |
| +0x06 | u16 | Current HP | |
| +0x08 | u16 | Max HP | |
| +0x0A | u8 | Level | |
| +0x0B | u8 | Status? | 0 = no status (tentative) |
| +0x0C | u16 | Held item? | 0 = none (tentative) |
| +0x0E | u8 | Unknown | Always 0x07 for occupied slots |
| +0x0F | u8 | Unknown | Varies per Pokemon |
| +0x10-0x23 | varies | Unknown | Various values, purpose unclear |
| +0x24 | long | Display pointer | Points to sprite/rendering data |
| +0x28 | u32 | Flags? | 0x00000100 for occupied slots |

**The full PokePara tree** (at the data pointer) uses a node-based structure with linked pointers, NOT the standard flat 236-byte party format. Property nodes contain individual attributes (name at prop_id=11, etc.). Move data has not been located yet.

**Note:** The standard Gen 4 party structure (PID + encrypted blocks + battle stats) was NOT found anywhere in the 4MB main RAM during overworld play. The game appears to use the PokePara tree exclusively and only constructs flat structures when saving or entering battle.

## Save File Structure (from PKHeX / Bulbapedia)

The save file uses an encrypted format in RAM. String searches (e.g. trainer name) won't work on raw memory.
Save file offsets (relative to small block start) are documented but the RAM base address for the save block
has not been confirmed in our environment.

| Save Offset | Field | Notes |
|------------|-------|-------|
| `+0x0068`  | Trainer Name | UTF-16LE, encrypted in RAM |
| `+0x1280`  | Map ID (save) | UInt16 |
| `+0x1288`  | X position (save) | UInt16 — this is the SAVE copy, not the live runtime value |
| `+0x128C`  | Y position (save) | UInt16 — this is the SAVE copy, not the live runtime value |

## Text / Dialogue Buffers

### Text Encoding (Gen 4)

All decoded text in RAM uses 16-bit little-endian character values:

| Range | Characters |
|-------|-----------|
| `0x012B` - `0x0144` | Uppercase A-Z |
| `0x0145` - `0x015E` | Lowercase a-z |
| `0x0161` - `0x016A` | Digits 0-9 (assumed) |
| `0x0188` | é (as in Pokémon) |
| `0x01AB` | ! |
| `0x01AC` | ? |
| `0x01AD` | , |
| `0x01AE` | . |
| `0x01B3` | ' (apostrophe) |
| `0x01C4` | : (colon) |
| `0x01DE` | (space) |

Control codes:

| Value | Meaning |
|-------|---------|
| `0xFFFF` | End of text |
| `0xFFFE` | Variable substitution (followed by argument bytes) |
| `0xE000` | Newline within text box |
| `0x25BC` | Page break / new text box |

### Overworld Dialogue Buffer

**Region:** `0x022A7000` - `0x022A9800` (10KB scan range)

Text is stored in a slot array. Each slot is preceded by the header marker `D2EC B6F8` (bytes: `EC D2 F8 B6`). Slots are spaced `0xAC` bytes apart. An active slot has text immediately after the marker; an empty slot has `0xFFFF` immediately after.

The buffer address is **dynamic** — different dialogue contexts write to different slots:
- NPC dialogue observed at `0x022A73BC`
- Cutscene dialogue (Mom) observed at `0x022A77FC`

The `read_dialogue.py` script scans for active slots automatically.

**Segment structure:** The buffer contains a full "segment" of dialogue — multiple text boxes separated by `0x25BC`. The game loads one segment at a time and advances through its boxes. At a segment boundary (e.g., item receive jingle), the next segment replaces the previous one.

**Trailing bytes before `[END]`:**
- `[BOX][END]` — observed in cutscene segments that wait for input and precede script events
- `[END]` with no trailing control — observed in both wait-for-input (NPC dialogue) and auto-advance (item receive) contexts. Not a reliable wait indicator for overworld text.

### Battle Text Buffer

**Region:** `0x02301000` - `0x02303000` (8KB scan range)

Stable address observed at `0x02301BD0`. Uses the same `D2EC B6F8` header marker. Contains **one message at a time** — each new battle event overwrites the previous.

**Trailing bytes before `[END]` (reliable indicators):**

| Pattern | Meaning | Action |
|---------|---------|--------|
| `text [END]` (no trailing control) | Auto-advancing narration | Wait, it will progress on its own |
| `[E000] [END]` (trailing newline) | Waits for player input | Press B to dismiss |
| `[FFFE]... [END]` (variable sequence) | Waits for player action | Select move/item/switch |

These indicators are **confirmed reliable** across all tested battle messages.

## Dynamic Objects (Overworld Object Array)

NPCs, floor items, and the player are stored in an array in RAM. Each entry is **0x128 (296) bytes** apart.

| Field | Offset from entry base | Size | Notes |
|-------|----------------------|------|-------|
| Fixed-point X | +0x00 | long | Upper 16 bits = tile X, lower 16 = sub-tile |
| Fixed-point Y | +0x08 | long | Upper 16 bits = tile Y, lower 16 = sub-tile |

**Entry 0 (player)** fixed-point X is at `0x022A1AA8`. Subsequent entries are at `+0x128` intervals.

- Entry 0 = player, Entry 1+ = NPCs/objects on current map.
- Entries with fpx=0 and fpy=0 are empty/inactive.
- `view_map` reads this automatically — player shows as `^v<>`, NPCs/objects as `A`, `B`, `C`, etc.

## Tile Behaviors

Passability is determined by bit 15 of the terrain u16, not the behavior value. The behavior byte (bits 0-7) indicates what special effect a tile has.

### Warp/Transition Tiles (passable, bit 15 = 0)

Walk *onto* the tile, then press a specific direction to activate the transition.

| Behavior | Name | Activation | Example |
|----------|------|------------|---------|
| `0x5F` | Stairs (down) | Stand on tile, walk **left** | Living room (10,3) -> bedroom |
| `0x5E` | Stairs (up) | Likely walk **right** (unconfirmed) | |
| `0x62` | Warp | Generic warp tile | |
| `0x65` | Door / Exit | Stand on tile, walk **down** | Living room (6,10) -> outside |

### Blocked Tiles (impassable, bit 15 = 1)

| Behavior | Name | Notes |
|----------|------|-------|
| `0x69` | Door (overworld) | House entrances on overworld maps. Marked blocked but warp system overrides collision — walk into the tile to enter. |
| `0x80` | Counter | Kitchen counter, can interact across it |

### Other Known Behaviors

| Behavior | Name | Notes |
|----------|------|-------|
| `0x02` | Tall grass | Wild encounters. Passable. |
| `0x10` | Water | Requires Surf. |
| `0x21` | Sand/beach | Passable, decorative. Seen in Sandgem Town. |
| `0x38`-`0x3A` | Ledges (S/N/W) | One-way jumps. Blocked bit set. |
| `0x3B` | Ledge (east) | One-way east jump. Blocked bit set. Route 201/202 shortcuts. |
| `0xA9` | Tree tile | Decorative trees on overworld, passable. |

*This table grows as we encounter new tile types during the playthrough.*

## Memory Watch Definitions

Watches are stored in `/workspace/RenegadePlatinumPlaytest/watches/` and persist across sessions.

| Watch Name        | Base Address   | Fields |
|------------------|---------------|--------|
| `player_position` | `0x0227F450`  | map_id (long +0), x (long +8), y (long +12), prev_x (long +48), prev_y (long +52) |
| `player_facing`   | `0x02335346`  | facing (byte +0, transform: 0=up, 1=down, 2=left, 3=right) |
