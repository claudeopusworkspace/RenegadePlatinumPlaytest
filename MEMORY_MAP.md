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

## Memory Watch Definitions

Watches are stored in `/workspace/RenegadePlatinumPlaytest/watches/` and persist across sessions.

| Watch Name        | Base Address   | Fields |
|------------------|---------------|--------|
| `player_position` | `0x0227F450`  | map_id (long +0), x (long +8), y (long +12), prev_x (long +48), prev_y (long +52) |
| `player_facing`   | `0x02335346`  | facing (byte +0, transform: 0=up, 1=down, 2=left, 3=right) |
