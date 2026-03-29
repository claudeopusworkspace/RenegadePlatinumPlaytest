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

### Zone Header Table
**Status: SOLVED.**

| Address      | Stride | Field |
|-------------|--------|-------|
| `0x020E601E` | 24 bytes | Zone header table in ARM9 binary. One entry per zone/map_id. |

**Entry format (first field only — rest TBD):**
- `+0` (u16): Matrix ID — index into `map_matrix/` files.

**Usage:** Given a map_id, read `0x020E601E + map_id * 24` as u16 to get the matrix_id. Then load the matrix file to get the land_data file ID. This chain (zone header → matrix → land_data) resolves terrain for ANY map — indoor or overworld.

### Terrain Attributes / Collision Grid
**Status: SOLVED.**

| Address      | Size | Field |
|-------------|------|-------|
| `0x0231D1E4` | 2048 bytes | RAM copy of current map's terrain (32x32 u16, little-endian, row-major) |

**WARNING:** This RAM address is **unreliable**. It gets garbled after menu interactions (party screen, pause menu) inside buildings, and for some maps (e.g., Pokemon Center) may contain non-terrain data. **Always prefer ROM-based terrain resolution** via the zone header → matrix → land_data chain.

**Per-tile format (u16):**
- Bit 15 (`0x8000`): Collision flag. 1 = impassable, 0 = passable.
- Bits 0-7 (`0x00FF`): Tile behavior (door=`0x65`, stairs=`0x5F`, counter=`0x80`, water=`0x10`, etc.).

**Grid-to-game coordinate offset: (0, 0)** — grid position maps directly to game coordinates.

**Caveats:**
- Dynamic objects (NPCs, floor items) are NOT in the static grid.
- Stair tiles may show as blocked (`0x8000`) but allow passage via dynamic events.
- Zone ID ≠ land_data NARC index (e.g., zone 414 = land_data 186, zone 415 = land_data 187). The zone header table provides the correct mapping.

**ROM source:** `fielddata/land_data/land_data.narc` contains 666 map files. Each file has a 16-byte header (4 u32: terrain_size, props_size, model_size, bdhc_size) followed by the terrain grid at offset 0x10. Confirmed against the `pret/pokeplatinum` decompilation.

### Player Facing Direction

| Address      | Size | Field |
|-------------|------|-------|
| `0x02335346` | byte | Facing direction: 0=up, 1=down, 2=left, 3=right |

### Pause Menu Cursor

| Address      | Size | Field |
|-------------|------|-------|
| `0x0229FA28` | byte | Pause menu cursor index (persists across menu opens) |

Values: 0=Pokedex, 1=Pokemon, 2=Bag, 3=Trainer Card, 4=Save, 5=Options, 6=Exit.

Also tracked at `0x022A6528` (mirror/copy, same values).

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

## PC Box Storage (Gen 4)

**Status: SOLVED.**

PC boxes use the same Gen 4 encrypted format as party data, but only 136 bytes per slot (no PID-encrypted battle stats extension). Level must be derived from EXP + species growth rate.

| Address      | Size | Field |
|-------------|------|-------|
| `0x0228B100` | 73,440 bytes | Box data: 18 boxes × 30 slots × 136 bytes |

**Per-slot layout (136 bytes):**
- Bytes 0-3: PID (u32, unencrypted)
- Bytes 4-5: Padding (0x0000)
- Bytes 6-7: Checksum (u16)
- Bytes 8-135: 4 encrypted 32-byte blocks (A/B/C/D), same PRNG/shuffle as party

**Address calculation:**
- `GetBoxSlotAddr(box, slot) = 0x0228B100 + (box - 1) * 30 * 136 + slot * 136`
- Box 1 slot 0: `0x0228B100`
- Box 2 slot 0: `0x0228C0F0`

**Box names (UI/display):** 18 entries at `0x0229CFE0`, 40-byte stride, Gen 4 text encoding.

**Discovery method:** Loaded save state with 5 known Pokemon in Box 1. Read their PIDs from a prior party state, searched 4MB RAM for those PIDs. Found all 5 at 136-byte intervals with valid checksums.

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

## Battle Battler Struct (`BattleMon`)

Base address: `0x022C5774`. 4 slots x `0xC0` (192) bytes each. Slot 0 = player active, Slot 1 = enemy active, Slots 2-3 = doubles partners.

Struct layout verified against [pret/pokeplatinum](https://github.com/pret/pokeplatinum) decompilation (`include/battle/battle_mon.h`).

| Field | Offset | Size | Notes |
|-------|--------|------|-------|
| Species | +0x00 | u16 | National Dex # |
| Atk | +0x02 | u16 | Effective stat (after nature/EVs/IVs) |
| Def | +0x04 | u16 | |
| Spe | +0x06 | u16 | |
| SpA | +0x08 | u16 | |
| SpD | +0x0A | u16 | |
| Moves | +0x0C | u16 x 4 | Move IDs |
| IVs | +0x14 | u32 bitfield | 5 bits each: HP/Atk/Def/Spe/SpA/SpD + isEgg + hasNickname |
| Stat stages | +0x18 | s8 x 8 | Atk,Def,Spe,SpA,SpD,Acc,Eva,Crit; neutral=6 |
| Weight | +0x20 | int (4) | In 0.1 kg units |
| Type 1 | +0x24 | u8 | Gen 4 internal type ID |
| Type 2 | +0x25 | u8 | |
| Form/Shiny | +0x26 | u8 bitfield | formNum:5, isShiny:1, padding:2 |
| Ability | +0x27 | u8 | Ability ID |
| Ability flags | +0x28 | u32 bitfield | **NOT status!** Entry ability announcements (see below) |
| PP | +0x2C | u8 x 4 | Current PP per move |
| PP Ups | +0x30 | u8 x 4 | PP Up count per move |
| Level | +0x34 | u8 | |
| Friendship | +0x35 | u8 | |
| Nickname | +0x36 | u16 x 11 | Gen 4 text encoding, 0xFFFF terminated |
| Current HP | +0x4C | s32 | Live battle HP |
| Max HP | +0x50 | u32 | |
| OT Name | +0x54 | u16 x 8 | Original trainer name |
| EXP | +0x64 | u32 | |
| Personality | +0x68 | u32 | PID |
| **Status** | **+0x6C** | **u32** | **Non-volatile status bitfield (sleep/psn/brn/frz/par/tox)** |
| Status Volatile | +0x70 | u32 | Volatile status flags (confusion, attract, etc.) |
| OT ID | +0x74 | u32 | |
| Held Item | +0x78 | u16 | Item ID |

### Ability Announcement Flags (+0x28)

This u32 bitfield tracks which entry abilities have already fired. **Previously misidentified as the status field** — Shinx with Intimidate set bit 1, which decoded as `Sleep(2)`.

| Bit | Flag |
|-----|------|
| 0 | weatherAbilityAnnounced |
| 1 | intimidateAnnounced |
| 2 | traceAnnounced |
| 3 | downloadAnnounced |
| 4 | anticipationAnnounced |
| 5 | forewarnAnnounced |
| 6 | slowStartAnnounced |
| 7 | slowStartFinished |
| 8 | friskAnnounced |
| 9 | moldBreakerAnnounced |
| 10 | pressureAnnounced |

### Status Condition Bitfield (+0x6C)

| Bits | Mask | Condition |
|------|------|-----------|
| 0-2 | 0x07 | Sleep (turns remaining, 1-7; 0 = not asleep) |
| 3 | 0x08 | Poison |
| 4 | 0x10 | Burn |
| 5 | 0x20 | Freeze |
| 6 | 0x40 | Paralysis |
| 7 | 0x80 | Toxic (bad poison) |

### Garbage Detection

Outside of battle, all slots contain stale/invalid data. Post-battle, the game reuses this memory region for pointer arrays, but some fields (species, level) may retain plausible-looking stale values. **Validation checks** (in order of reliability):

1. `cur_hp > max_hp` — most reliable, impossible in a real battle
2. `species > 493` or `species == 0` — invalid species
3. `level == 0` or `level > 100` — invalid level
4. `max_hp == 0` — no Pokemon has 0 max HP

### Battle State Detection (Text-Based)

The battle struct has no dedicated "in battle" flag. Battle states are best detected via **text buffer patterns** in the battle narration region:

| State | Text Pattern | Control Code | Notes |
|-------|-------------|-------------|-------|
| Action prompt | "What will X do?" | `[FFFE][0200]` (CTRL_VAR) | Normal move selection |
| Switch prompt | "Will you switch your Pokémon?" | `[VAR][0200]` | Trainer's next Pokemon — enemy slot already updated |
| Fainted message | "X fainted!" | AUTO_ADVANCE | Enemy HP = 0 in battle struct |
| EXP gain | "gained X Exp. Points!" | AUTO_ADVANCE | |
| Level up | "grew to Lv. X!" | AUTO_ADVANCE | Battle struct updates (level, stats) immediately |
| Battle end | N/A | N/A | No text — detect via garbage in battle struct |

**Key observations from debugging:**
- Enemy slot updates to the **next Pokemon before** the switch prompt appears
- Battle struct **level/stats update immediately** at level-up, before move learning
- Move learning prompts use **d-pad + A for initial choice**, then **touch screen for move selection**
- Post-battle, battle struct becomes garbage while still "looking valid" (species/level in range)

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

## Dynamic Objects (Overworld MapObject Array)

NPCs, floor items, boulders, signs, and the player are stored in an array in RAM. Each entry is a **MapObject** struct — **0x128 (296) bytes**. Struct layout sourced from [pret/pokeplatinum](https://github.com/pret/pokeplatinum) decompilation.

**True struct base (entry 0):** `0x022A1A38`
**Legacy FPX base (entry 0 pos.x):** `0x022A1AA8` (= struct base + 0x70)
**Entry stride:** `0x128` (296 bytes). **Max entries:** 16.

### MapObject Struct Layout

| Field | Offset | Size | Description |
|-------|--------|------|-------------|
| status | +0x00 | u32 | Bitfield: active, hidden, moving, etc. |
| unk_04 | +0x04 | u32 | Unknown |
| localID | +0x08 | u32 | NPC ID within map (0=player, 1+=NPCs) |
| mapID | +0x0C | u32 | Zone/map ID this object belongs to |
| **graphicsID** | **+0x10** | **u32** | **Sprite type — identifies what the object IS** |
| movementType | +0x14 | u32 | Movement AI (0=none, 1=look_around, 3=wander, 15=stationary) |
| trainerType | +0x18 | u32 | Trainer type (0 = not a trainer) |
| flag | +0x1C | u32 | Event flag ID controlling visibility |
| script | +0x20 | u32 | Script ID triggered on interaction |
| initialDir | +0x24 | int | Initial facing (0=N, 1=S, 2=W, 3=E) |
| facingDir | +0x28 | int | Current facing direction |
| movingDir | +0x2C | int | Current movement direction |
| prevFacingDir | +0x30 | int | Previous facing direction |
| prevMovingDir | +0x34 | int | Previous movement direction |
| data[3] | +0x38 | int×3 | Generic script parameter slots |
| movementRangeX | +0x44 | int | Max wander range in X (tiles) |
| movementRangeZ | +0x48 | int | Max wander range in Z (tiles) |
| xInitial | +0x4C | int | Spawn tile X |
| yInitial | +0x50 | int | Spawn tile Y (elevation) |
| zInitial | +0x54 | int | Spawn tile Z (= map Y) |
| xPrev | +0x58 | int | Previous tile X |
| yPrev | +0x5C | int | Previous tile Y |
| zPrev | +0x60 | int | Previous tile Z |
| x | +0x64 | int | Current tile X (plain integer) |
| y | +0x68 | int | Current tile Y (elevation) |
| z | +0x6C | int | Current tile Z (= map Y) |
| pos.x | +0x70 | fx32 | Fixed-point X; tile = (val >> 16) |
| pos.y | +0x74 | fx32 | Fixed-point Y (height) |
| pos.z | +0x78 | fx32 | Fixed-point Z (= map Y); tile = (val >> 16) |
| _(rendering/task data)_ | +0x7C..+0x127 | — | Sprite offsets, movement callbacks, animation data |

### Notable graphicsID Values

Full list in `data/obj_event_gfx.txt`. Key values:

| ID | Name | Category |
|----|------|----------|
| 0 | Player M | Player |
| 97 | Player F | Player |
| 99 | Prof Rowan | Named NPC |
| 148 | Barry | Named NPC |
| 140 | Mom | Named NPC |
| 138 | Cynthia | Named NPC |
| 87 | Pokeball | Floor item |
| 174 | Briefcase | Interactable object |
| 84 | Strength Boulder | Field obstacle |
| 86 | Cut Tree | Field obstacle |
| 91-96 | Signs/Signposts | Signs |
| 26 | Pokecenter Nurse | Generic NPC |

### Usage

- `read_objects()` reads struct header for each active entry, returning `name`, `graphics_id`, `movement_type`, `trainer_type`, `local_id`, and `script`.
- `view_map` shows objects by name (e.g., "Prof Rowan (A)") instead of generic letters.
- Entry 0 = player, Entry 1+ = NPCs/objects on current map.
- Entries with pos.x=0 and pos.z=0 are empty/inactive.

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
