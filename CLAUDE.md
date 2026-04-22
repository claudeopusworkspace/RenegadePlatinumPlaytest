# Pokemon Renegade Platinum Playtest

You are playtesting the melonDS MCP server by playing Pokemon Renegade Platinum (a difficulty/QoL hack of Pokemon Platinum by Drayano).

**MCP tools document themselves.** Read each tool's docstring for parameters and behavior — do not duplicate that here. This file covers project-specific context that isn't (and shouldn't be) in tool docstrings.

## Getting Started

1. Call `init_emulator` to initialize melonDS.
2. Call `load_rom` with path `/workspace/RenegadePlatinumPlaytest/RenegadePlatinum.nds`.
3. Load a save state if one exists (e.g., `load_state("living_room")`).
4. If no save state, advance through the intro (~8000 frames) to reach the title screen.

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

## Navigation Philosophy

**CRITICAL: Do not rely on screenshots for spatial reasoning in the overworld.** The isometric/overhead camera makes it very difficult to judge tile positions, room boundaries, and exits from pixel images. Use `view_map` + `navigate_to(poi=...)` — read their docstrings for parameters.

Screenshots are fine for dialogue, menus, and battle screens. **When stuck navigating, ask Michael for visual help** rather than brute-forcing positions.

## DS Screen Layout

- **Top screen** (256x192): Main game display.
- **Bottom screen** (256x192): Touch-enabled, used for menus, Pokemon selection, etc.
- Screenshots with `screen="both"` show both stacked vertically (256x384).

## Input Reference

**Buttons:** a, b, x, y, l, r, start, select, up, down, left, right

- **A**: Confirm / advance dialogue / interact.
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

## Game Progress

- **Character**: CLAUDE | **Rival**: WOJ
- **Badges**: 2 (Coal, Forest)
- **Location**: Route 206 (310, 608) on foot, under the east side of the Cycling Road bridge — one tile south of the east Wayward Cave entrance (310, 607). Save state: `session30_route206_under_bridge`. Full team healed.
- **Party order**: Monferno leads, then Luxray, Prinplup, Grotle, Swinub, Togepi.
- **Monferno** Lv29 — Careful, Iron Fist. Charcoal. Low Kick / **Mach Punch** / **Flame Wheel** / Taunt.
- **Luxray** Lv34 — Jolly, Guts. Scope Lens. Spark / **Crunch** / Howl / Ice Fang.
- **Prinplup** Lv26 — Lax, Vital Spirit. Metal Claw / Growl / **Scald** / Icy Wind.
- **Grotle** Lv25 — Naughty, Overgrow. Muscle Band. Bulldoze / Cut / Bullet Seed / **Razor Leaf**.
- **Swinub** ✨ Lv28 — Timid, Thick Fat. No held item (Exp. Share moved to Togepi). **Avalanche** / **Ice Shard** / Bulldoze / Mud Bomb.
- **Togepi** Lv9 — Timid, Serene Grace. **Exp. Share**. **Metronome** / Charm / **Extrasensory** / **Disarming Voice**. Leveled Lv1→Lv9 in one Ruin Maniac fight via Exp. Share; learned Metronome at Lv2 (forgot Growl); skipped Sweet Kiss learn at Lv7.
- **PC Box 1**: Machop Lv25, Larvitar Lv9 (Rock/Ground, Guts).
- **HM plan**: Prinplup→Empoleon (Surf, Waterfall). Togepi→Togekiss (Fly). Grotle→Torterra / Swinub→Mamoswine / Larvitar→Tyranitar (Rock Climb options).
- **Notable items**: Explorer Kit, **Hard Stone**, Dawn Stone, **Dusk Stone**, Wise Glasses, **TM74 Gyro Ball**, **TM32 Double Team**, **TM85 Dazzling Gleam** (new session 29, Mira quest reward — earmarked for Togepi post-evolution), **PP Up**, TM16 Light Screen, TM33 Reflect, TM73 Thunder Wave, **Focus Band**, Oval Stone, Fire Stone, Sun Stone, Never-Melt Ice. Bag: 7 Super Potions, 6 Repels, **0 Revival Herbs** (restock before Mt. Coronet).
- **Wayward Cave status**: COMPLETE. All 10 trainers defeated across sessions 28+29. Mira's quest complete — found her Crimson Ribbon at (72, 11), received TM85 Dazzling Gleam, Mira departed. Cave freely traversable but no remaining objectives. One Pokéball at (57, 53) still puzzle-gated — skip unless easy.
- **Route 206 under-bridge status**: Remaining undefeated Cyclist obj:4 at (304, 631) — on the BRIDGE (not ground-reachable from (310, 608), need to approach from the cycling road). Pokéballs at (292, 623) + (314, 631) + Berry Soils at (293-294, 627) are all ground-level and reachable. Cycling Road south gate warps at (301-305, 688) lead through the gate house to Route 207. Ground-level west Wayward Cave warp at (299, 611) is reachable from here.
- **Next**: Clear the reachable under-bridge Pokéballs + Berry Soils, then south through the gate house (warps at y=688) to Route 207, clear Psychic Arianna, enter Mt. Coronet. Undefeated bridge Cyclists (obj:2/4/6) can be tackled when we cross the bridge northbound on the bicycle.

See GAME_HISTORY.md for full details (defeated trainers, story progress, box contents, items).

## Test Suite

Integration tests live in `tests/` (491 tests across 42 files). Require at least one running emulator with the ROM loaded. Legacy DeSmuME tests in `tests/legacy/` are excluded by default.

```bash
.venv/bin/python -m pytest tests/ -v          # full suite (~2:30 @ N=8, ~7 min @ N=2, ~13 min single)
.venv/bin/python -m pytest tests/test_X.py -v  # single file
```

Tests load save states, call implementation functions directly (bypassing MCP protocol), and assert on `final_state`, log contents, and party data. Each test resets via `load_state` so they're independent.

**Run tests after any change to `turn.py`, `auto_grind.py`, `navigation.py`, or `battle_tracker.py`.**

### Dedicated test emulator(s) — decoupled from the live session

Tests run against their own melonDS process(es) so they don't fight the emulator Claude Code is driving for interactive play. **pytest owns the fleet lifecycle by default** — no manual terminal juggling:

```bash
.venv/bin/python -m pytest tests/              # auto-spawns 8 emus, runs, tears down
.venv/bin/python -m pytest --fleet-size=2      # smaller fleet for single-file runs (~4s boot)
.venv/bin/python -m pytest --fleet-size=0 …    # skip auto-spawn (reuse a pre-booted fleet)
```

Cold-boot cost at N=8 is ~18s; after that the full suite completes in ~2:30. For many back-to-back invocations, pre-boot a persistent fleet and pytest will reuse it:

```bash
# Persistent fleet (blocks; Ctrl-C to stop):
.venv/bin/python scripts/start_test_emulators.py --count 8

# Every subsequent pytest invocation detects live sockets and reuses them
# WITHOUT tearing them down at session end.
.venv/bin/python -m pytest tests/
```

The playthrough emulator (`.melonds_bridge.sock`) is **never** in the fallback search order — tests cannot silently land on the interactive Claude-Code instance. If no test emulator is live and `--fleet-size=0` disables auto-spawn, the fixture fails with an explicit skip.

Each worker gets its own `.workers/worker_{i}/` with a ROM copy + symlinks to shared `savestates/macros/data`, bound to `.melonds_test_bridge_{i}.sock`. `pytest_xdist_auto_num_workers` resolves `-n auto` (set in `pytest.ini`) to the live socket count — no manual `-n` flag needed. CLI `-n N` still wins if you pass it.

**Container requirement** — melonDS's JIT fastmem needs ~17 MB of `/dev/shm` per worker. N=8 needs ~150 MB; our container is started with `--shm-size=8g` to provide headroom. If `/dev/shm` reverts to the Docker default 64 MB, workers SIGBUS on `savestate_load` (see MelonMCP#9) and only N≤2 is viable. Check with `df -h /dev/shm`; restart the container with `--shm-size=8g` if needed.

Staggers in the launcher + conftest are defensive and harmless at any N — leave them.

**Single standalone (debugging a specific worker manually)**:

```bash
.venv/bin/python scripts/start_test_emulator.py     # listens on .melonds_test_bridge.sock
.venv/bin/python -m pytest --fleet-size=0 tests/    # sequential, ~13 min full suite
```

## Tips

- Save state frequently — this is a difficulty hack, expect challenges.
- **Renegade Platinum changes abilities and movesets from vanilla** — always `read_battle` at the start of every fight; don't assume vanilla behavior.
- The `load_state` tool may occasionally hang — check `get_status` to verify.
- Addresses must be passed as decimal integers to MCP tools, not hex strings.
- **Wait 300 frames between UI navigation steps** when driving menus manually — Pokemon ignores input during forced text delays.
- **Always check the bottom screen for Yes/No prompts** — battle/switch prompts use the touch screen.
- **Party context menu row offsets are not constant** — when driving the overworld Pokemon sub-menu (Summary / [field moves] / Switch / Item / Cancel), use `renegade_mcp.party_submenu.switch_row(mon)` / `item_row(mon)`. The Pokemon's known field moves (Cut, Fly, Surf, Strength, Defog, Rock Smash, Waterfall, Rock Climb, Flash, Teleport, Dig, Sweet Scent, Chatter, Milk Drink, Softboiled) each push Switch and Item down one row. Always re-read party after a state-changing menu flow and verify the expected change actually committed — landing on the wrong row typically produces a silent-success failure mode.
