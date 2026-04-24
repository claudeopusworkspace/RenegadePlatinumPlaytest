# Pokemon Renegade Platinum - Game History

Chronological playthrough log — session-numbered entries from 2026-04-19 (Session 17) onward. Current game status is in CLAUDE.md.

Early chapters (Twinleaf through Commander Jupiter / pre-Session-17 era, 2nd badge) live in [GAME_HISTORY_ARCHIVE.md](GAME_HISTORY_ARCHIVE.md).

## Session 17 (2026-04-19): Explorer Kit, Togepi hatch, Cycling Road, Larvitar catch

### Explorer Kit Gate at South Eterna
- Tried to leave Eterna south — Pokemon Breeder F at (302, 565) blocks the route until we have an **Explorer Kit** ("You should have a word with the man next door to the Pokémon Center").
- Found the **Underground Man** (Expert M) in the house immediately east of the Pokemon Center (Map 84, warp (310, 530)). He gives the Explorer Kit and mentors missions — declined the mentorship dialogue but walked away with the key item.
- Key observation: `heal_party`'s auto-navigate is a great way to locate the PC when its door isn't obvious in `view_map`.

### Cycling Road (Route 206)
- Gate guard at south Eterna demands the bicycle — used `use_item("Bicycle")` to mount up.
- **Cyclists defeated** (all one-shot by Luxray's Bite/Spark): Axel (Pichu/Pichu/Pikachu), James (Ponyta/Flaaffy), John (Farfetch'd — Spark 2x SE OHKO), Ryan (Luxio — Intimidate drop was irrelevant), Rachel (Jolteon — Volt Absorb, used Bite instead).
- Luxray got paralyzed from Pichu's Static; Parlyz Heal + Super Potion fixed it.
- **Togepi hatched** mid-ride on Route 206 (~step 5000+). Slot 5 Togepi Lv1 Timid, Serene Grace, knows Growl/Charm/Extrasensory/Disarming Voice. Friendship starts at 120.

### Tool Bugs Logged
- **BUG-023** (`route206_pre_togepi_hatch`): `navigate_to` misclassifies the egg-hatch "Oh?" overworld dialogue as a generic trainer/NPC `encounter: "dialogue"` — no distinct type. Expected: `encounter: "egg_hatch"` with hatching slot.
- **BUG-024** (`route206_cyclingroad_end_nav_repro`): `navigate_to` wanders up 19 / right 3 / up 8 / right 4 / down 31 / right / down 11 / left 6 / up 8 / left 2 when targeting a warp tile that's part of a cluster of 10 identical-dest side-warps at the south end of Cycling Road's second gate. Manual `press_buttons(["down"], 120)` works fine.
- **FR-009**: `auto_throw_ball` / `throw_ball` repeat mode — catching Larvitar required 8+ individual `throw_ball` calls with identical params.

### Route 207 Scout + Larvitar Catch
- Descended the first Cycling Road ramp through the dual-tunnel split (only x=300-301 or x=305-306 are passable; the middle is a wall).
- Scouted 15 encounters via `auto_grind(iterations=15)` (no move_index = flee mode). Route 207 grass table: **Machop, Ponyta, Phanpy, Larvitar, Rhyhorn**. No Flying types.
- Revised plan: Togepi → Togetic → **Togekiss (Fairy/Flying)** covers the Flying role. So we had room to go after Larvitar instead.
- Reverted to the first Larvitar checkpoint (`9462ec09`, Larvitar Lv9 at full HP). Switched in Prinplup (safe bc Luxray's Bite would one-shot).
- Ate Screech 4x (Def at -6), sandstorm damage, ~12 Poke Balls thrown — Larvitar broke free 8 times with a mix of 1/2/3/4-shake messages before finally staying in on the final ball.
- **Larvitar (Rock/Ground, Guts ability) caught**, deposited to Box 1 alongside Machop.

### HM Coverage Plan (for Woj's requirements)
- **Surf + Waterfall**: Prinplup → Empoleon ✓
- **Fly**: Togepi → Togetic → Togekiss ✓
- **Rock Climb**: Grotle → Torterra (learnable) *or* Swinub → Mamoswine *or* Larvitar → Tyranitar — any of three options.

### Session Summary
- **Badges**: 2 (unchanged — no gym battles this session).
- **Money**: ~$23,104 post-catch shopping not done.
- **Party**: Luxray Lv32, Grotle Lv24, Prinplup Lv25 (11/75 HP — needs heal), Monferno Lv27, Swinub ✨ Lv24, Togepi Lv1.
- **PC Box 1**: Machop Lv25, Larvitar Lv9 (NEW).
- **Items obtained**: Explorer Kit.
- **Location**: Route 207 tall grass (295, 721). Save state: `route207_larvitar_caught`.
- **Next session**: Heal at Eterna PC, consider party-rotating Larvitar into slot for training, continue south to Oreburgh Gate / Route 208 / Hearthome.

## Session 18 (2026-04-20): Oreburgh heal run, Route 207 trainer cluster, bike-slope + use_item bugs

### Heal run south, not Eterna
- Planned to heal at Eterna PC (per end-of-session-17 notes), but on reading the geography it was faster to head *south* through Route 207's bike slopes to Oreburgh City. `navigate_to` bike-slope *descent* handler worked cleanly — we coasted down from (299, 730) to (299, 743) straight into Oreburgh.
- `heal_party` auto-navigated to the Oreburgh PC from street level. Full heal restored everyone including Prinplup (11/75 → 75/75).
- PokéMart stock at badge threshold 2: Poké Ball, Potion, Super Potion, Antidote, Parlyz Heal, Awakening, Burn/Ice Heal, Escape Rope, Repel + Oreburgh specialties (Heal Ball, Net Ball, Tunnel Mail). Bought **10 Super Potions (¥7,000) and 5 Repels (¥1,750)**. Money ¥21,394 → ¥12,644.

### Route 207 trainer cluster
- Re-crossed the bike slope heading *north*. First attempt on foot failed silently (see BUG-025 below) — mounting the Bicycle + retry worked in one call with `obstacles_cleared: bike_slope`.
- Grabbed the **Hard Stone** (Pokeball at (291, 711)) — perfect hold item for Larvitar/Tyranitar down the line. Fought off two wild interrupts on the way (Rhyhorn, Machop — both one-shot).
- **Picnicker Lauren** — Smoochum Lv24 (Bite 2x SE), Treecko Lv24 (Ice Fang 4x SE), Snubbull Lv24 (Prinplup Metal Claw crit SE).
- **Camper Anthony** — Magby Lv24 (Spark OHKO, Luxray burned from Flame Body), Trapinch Lv24 Bug/Ground (switched to Monferno, Flame Wheel SE), Charmander Lv24 (switched to Prinplup, Bubble Beam SE).
- **Hiker Kevin** — Dunsparce Lv25 ×2. First Dunsparce took two Crunches from Luxray. Second Dunsparce KO'd Grotle after a Body Slam + paralysis + Bullet Seed 3-hit sequence; Monferno Mach Punch finished it. First faint of the session.
- **Youngster Austin** — Lombre Lv25 (Luxray Crunch OHKO), Gligar Lv25 (Swinub Avalanche 4x OHKO). Burned Luxray clutched the Crunch KO with 6 HP remaining.

### Level-ups & moves
- **Luxray Lv32 → 33** — learned **Crunch** (Dark, 80 pwr, 20% Def drop); replaced Bite.
- **Prinplup Lv25 → 26** — learned **Scald** (Water, 80 pwr, 30% burn chance, STAB); replaced Bubble Beam.
- **Swinub Lv24 → 25** — learned **Avalanche** (Ice, 60 pwr, 120 if hit first); replaced Powder Snow.

### Bike slope workflow (take-aways for future sessions)
- Route 207's bike slope pair is at (306, 718) top / (306, 719) bottom. **Ascending requires the Bicycle** — the navigate_to slope handler will silently fail (15 repaths, stall at (306, 720)) if you're on foot.
- Protocol: before any `navigate_to` whose BFS path crosses a slope tile, call `use_item("Bicycle")` to mount. Bike slopes still render as `\` / `/` in `view_map`.
- Descent still works fine on foot (the game just slides you south) but keep the bike on for symmetry — avoids a stall if you ever want to turn back.

### Tool bugs logged
- **BUG-025** (`bug_bike_slope_north_climb_fail`): `navigate_to` stalls silently on bike-slope ascent when `on_bicycle=False`. 15 repaths, ends at (306, 720) with no error. Verified workaround: mount the bike via `use_item("Bicycle")` and retry — the same call succeeds with `obstacles_cleared: [{"type":"bike_slope","tiles":2,"x":306,"y":719}]`. Suggested fix: auto-mount bike for slope obstacles the way `navigate_to` already auto-Surfs for water.
- **BUG-026** (`bug_battle_turn_use_item_throws_pokeball`): Mid-trainer-battle, `battle_turn(use_item="Super Potion", party_slot=3)` threw a Poké Ball at the enemy Lombre (`"The Trainer blocked the Ball!"`) instead of healing our Pokemon. Tool's `formatted` field falsely claimed `"Used Super Potion on Monferno"` — no heal occurred and pre/post read_party showed identical HP. Likely the bag pocket tab navigation landed on Poké Balls instead of Medicine. Also noted a possibly-related qty drift: `use_item("Repel")` reported `old_qty:14 → 13` right after buying 5 Repels when we should have had 9. Filed high-priority — silently consumes the turn and lies about the action.
- Also observed a text code leak: `"Hit 3 time[01B9]s/!"` in Bullet Seed log — another glyph code that should be stripped by `text_encoding.py` (family of BUG-005/008/009).

### Session Summary
- **Badges**: 2 (unchanged).
- **Money**: ¥12,644 → ¥13,828 after trainer prize money (Lauren $384, Anthony unknown, Kevin $800, Austin $400).
- **Party**: Luxray Lv33, Grotle Lv24, Prinplup Lv26, Monferno Lv27, Swinub ✨ Lv25, Togepi Lv1. All healed at end.
- **PC Box 1**: Machop Lv25, Larvitar Lv9 (unchanged).
- **Items obtained**: Hard Stone (route drop), Super Potion (route drop). 10 Super Potions + 10 Repels in bag.
- **Location**: Route 207 (306, 714), on bicycle, Repel active. Save state: `route207_north_of_slope_session18_end`.
- **Next session**: Push north toward Mt. Coronet. Remaining Route 207 trainers: Hiker at (329, 715), two more to scout further up. Pokeball at (323, 730) still uncollected. Consider rotating Larvitar into party for training before Mt. Coronet (currently Lv9 vs Mt. Coronet wilds at Lv14-16).

## Session 20 (2026-04-20): Mt. Coronet blocked — forced into Wayward Cave detour

### Route 207 push east → Mt. Coronet gate
- Began at `route207_north_of_slope_session18_end`. Session 18's hint ("push north") turned out to be wrong — Mt. Coronet is *east* of the save state, not north. Detoured north first, hit Route 206 Cycling Road by mistake, came back (one bug filed in the process — see BUG-029 below).
- Headed east through the Route 207 vent corridor. **Hiker Justin** ambushed at (329, 715):
  - **Graveler Lv25** — Rock Head + Self-Destruct (full 200 BP, no recoil!). Luxray's Electric is useless here, so switched to Prinplup. Graveler crit-Magnitude knocked Prinplup to 32/77 on the switch-in turn. Scald (4x on Rock/Ground, +30% burn) OHKO'd cleanly.
  - Free switch prompt → **Grotle** for **Sandslash Lv25** (Ground). Razor Leaf 3HKO (Sandslash missed one Crush Claw). +$800.
  - Swinub hit **Lv26** from the Exp. Share.
- Healed Prinplup back to full with a Super Potion (10 → 9 Super Potions).
- **Mt. Coronet warp found at (341, 712)**, but the **Psychic NPC at (336, 710)** intercepts with a mandatory sight-line dialogue: *"A Kadabra, sending a distress signal for its trainer from Wayward Cave!"* Triggered the Mira rescue quest. The Psychic is a hard story gate — can't pass until Mira is rescued.

### Route 206 grind for the Wayward Cave entrance
- Backtracked west + north, looping around the Café Cabin instead of through it, to reach Route 206's lower path (the grass strip beside the Cycling Road bridges).
- **TM74 Gyro Ball** on the middle island between the two bridges at (302, 652). Reachable only via the gap under the bridge-merge section.
- **PP Up** on the east lower path at (313, 679).
- Hit **BUG-030** (navigate_to routes *through* bridge instead of under it) when trying to cross from middle island to west grass. Worked around with manual `navigate` inputs: up 2 + left 5 pushed through the bridge-underside tiles by hand.
- **Hiker NPC at (292, 643)** gave the canonical hint: *"Two caves on Route 206, but I can only find one entrance."* — standard Wayward-Cave-secret-entrance flavor.
- **Hiker Theodore** ambushed at (302, 631) during the grass walk:
  - **Torkoal Lv26** — Drought auto-sun + Lava Plume/Flame Wheel. Nasty matchup for most of the team (Swinub Ice/Ground takes 2x sun-boosted Fire). Stuck with Luxray — Crunch crit OHKO'd on turn 1 (Scope Lens pulled its weight). +$832.

### Entered the secret Wayward Cave branch (not Mira's room)
- **Wayward Cave secret entrance at (299, 611)** on Route 206's *west* lower path, guarded by patrolling Cyclist F #29. `interact_with` timed out on her patrol, but the pathing still walked onto the warp tile and triggered the transition — entered map 284 at (30, 55).
- Map 284 → internal warp at (28, 54) → map 285 (second floor of the secret branch).
- Bike-slope puzzle: the slopes in map 285 go north-to-south. Hit **BUG-031** (navigate_to assumes slopes are descent-only, can't ascend). Workaround: `navigate d3` to back off, then `advance_frames(90, buttons=["up"])` — held-UP rode the slope successfully.
- Reached the upper room at (30, 23). `view_map` reported a "Pokeball" at (31, 16) that turned out to be Mira's Kadabra (or an NPC sprite sharing the Pokeball graphic) — **BUG-032** filed.

### Bugs filed (playtest blocked pending fixes)
- **BUG-029** `view_map` marks under-bridge pickup as reachable (Cycling Road elevation ignored by BFS).
- **BUG-030** `navigate_to` routes through bridge tiles when player is under the bridge.
- **BUG-031** `navigate_to` bike-slope traversal fails going UP (tuned for descent-only; first ascent in the playthrough).
- **BUG-032** ~~`view_map` labels Mira's Kadabra NPC as "Pokeball"~~ — closed session 22 as no-repro; the three "Pokeballs" at (22,9) / (31,16) / (33,8) are real items (gfx 87), just on a different elevation plateau.
- **FR-009** `use_item("Repel")` misreports already-active Repel as `"menu flow may have gone wrong"` — confusing when the tool actually worked.
- Every bug has a named repro save state in `savestates/`.

### Session Summary
- **Badges**: 2 (unchanged).
- **Trainers defeated**: Hiker Justin (Route 207), Hiker Theodore (Route 206 west grass).
- **Items obtained**: TM74 Gyro Ball, PP Up.
- **Party**: Luxray Lv33, Grotle Lv24, Prinplup Lv26, Monferno Lv27, Swinub ✨ **Lv26** (+1), Togepi Lv1. All healed, Prinplup patched mid-session.
- **Bag**: 10 Super Potions, 6 Repels (burned 4 across routing detours).
- **Location**: Wayward Cave upper room, map 285 at (30, 23). Save state: `wayward_cave_session20_end`. **This is the secret branch, not the main Mira-quest branch.**
- **Next session**: Gated on dev fixing BUG-029/030/031/032. Then: exit the secret branch back to Route 206, find the *main* Wayward Cave entrance near the Route 207 Mt. Coronet gate, rescue Mira's Kadabra, return to the Psychic, proceed into Mt. Coronet.

## Session 23 (2026-04-20): Main Wayward Cave entry, Mira trainer battle, quest advanced

### Exit secret branch → Route 206
- Loaded `wayward_cave_session20_end` at Wayward Cave upper room (30, 23). Navigation into the upper-room maze was painful — spent time mashing east into cliff walls before Woj pointed out I'd been reading the map as 2D when the ">" / "^" tiles around me are elevation boundaries (ledges + cliff faces), not walkable directions. Retreated to the slope at (7, 26)-(7, 27) and rode back down to map 284.
- Exited map 284 via the (30, 55) warp back to Route 206 (299, 612). The Cyclist F #29 does not actually block the warp — she patrols on the upper Cycling Road bridge while the warp and the player share the lower-path elevation. Woj clarified: "the cyclists are at the higher level, you're underneath the bridge."

### Main Wayward Cave entrance is also on Route 206
- Contrary to my session-20 write-up, the **main Wayward Cave entrance is NOT on Route 207** — it's a second warp on Route 206 at **(310, 607)**, on the *east* lower path (the opposite side of the Cycling Road bridge from the secret west entry at (299, 611)). Both entrances land in map 284 (`D21R0101`), the main cave floor, just at different sides of the interior wall. This is how we reached Mira — via (310, 607) → (41, 53).
- Routing: from (299, 612) went right under the bridge pillars (raw right-hold is fine here — `navigate_to` kept tripping on the cycling-road tile-behavior guard), then up ~10 tiles through the narrow corridor beside the cliff, then `navigate_to(310, 607)` warp-entered cleanly.

### Mira rescue quest — it's a trainer battle in Renegade Platinum
- Approached Mira at (38, 42). First call was `interact_with(object_index=5)` on the bicycle — walked up to (40, 41) but stopped one tile short and never tapped A. Dismounted and retried; worked. Filed **BUG-033** with `bug_interact_with_on_bike` save state.
- Mira is a **trainer battle** in this hack, not a passive escort: "Pokémon Trainer Mira sent out Togetic!" (after "Eek! Stay away from Mira!" flavor intro).
  - **Togetic Lv27** (Fairy/Flying, Serene Grace, Sitrus Berry) — Dazzling Gleam / Air Cutter / Soft-Boiled / Sweet Kiss. Luxray Spark → SE → OHKO.
  - **Porygon2 Lv27** (Normal, Trace → copied Guts, Expert Belt) — Tri Attack / Charge Beam / Signal Beam / Recover. Luxray Crunch x2 → KO. Took one Signal Beam SE (Bug → Dark) mid-trade.
  - **Kadabra Lv28** (Psychic, Magic Guard, **Life Orb**) — Psybeam / Grass Knot / Dazzling Gleam / Recover. This is the nuke. Life Orb + STAB + SE coverage means most of our team can't survive a single hit:
    - Luxray (Dark) → DG 2x SE → OHKO from 66 HP (the 66-HP chip from Porygon2's Signal Beam compounded it).
    - Swinub (Ice/Ground) → Psybeam neutral but LO+STAB OHKO through our SpD 30. Lost the shiny Swinub to the switch.
    - Prinplup (Water) → Grass Knot SE → one Super Potion + one Scald, then Psybeam OHKO'd. Scald *did* land the burn, but Magic Guard negates burn chip and Kadabra is a special attacker, so the burn did nothing.
    - Grotle (Grass) → DG OHKO.
    - **Winning play:** sent Grotle as faint-switch absorber, popped **Revival Herb on Luxray** (bench) — cost Grotle to Kadabra's DG, revived Luxray at full. Luxray switched in, ate one DG (109→50), Crunch SE OHKO'd Kadabra.
  - **Haunter Lv27** (Ghost/Poison, Levitate, Spell Tag) — Shadow Ball / Double Team / Hypnosis / Curse. Luxray Crunch → SE Ghost → OHKO, no damage taken.
- **Mira wins**: Luxray levelled to Lv34 from the Kadabra XP (870 EXP), +$3360 prize. Post-battle dialogue revealed the twist — Mira's distress signal was a cover; she'd actually dropped a valuable item deep in the cave and wants help finding it. Mira now **follows the player and auto-heals the party** after every battle (confirmed: Grotle/Prinplup/Swinub all revived + fully healed immediately post-Mira).

### Wrap (Woj called session)
- Navigation tooling isn't communicating multi-level maps clearly enough. Most of the session drained on me mis-reading elevation-as-wall and walking into cliff faces. Stopped to rethink map rendering before continuing the item hunt.

### Session Summary
- **Badges**: 2 (unchanged).
- **Trainers defeated**: Pokémon Trainer Mira (Togetic/Porygon2/Kadabra/Haunter). +$3360.
- **Items obtained**: None yet from Mira's item quest.
- **Items used**: 1 Super Potion, 1 Revival Herb (0 remaining — may need to buy more before the next tough fight).
- **Party**: Luxray **Lv34** (+1), Grotle Lv24, Prinplup Lv26, Monferno Lv27, Swinub ✨ Lv26, Togepi Lv1. Full HP (Mira auto-heal).
- **Location**: Wayward Cave main branch map 284 (D21R0101) at (42, 53). Mira standing by at (38, 42). Save state: `session23_end_with_mira`.
- **Bugs filed**: **BUG-033** (`interact_with` stops one tile short on the bicycle, repro `bug_interact_with_on_bike`).
- **Next session**: blocked on map-tool redesign. Then: find Mira's lost item deeper in the cave (west/south corridors from the (42, 53) area are the unexplored parts), return to her, exit, finally unlock the Route 207 Psychic → Mt. Coronet.

## Session 28 (2026-04-21): Wayward Cave trainer sweep — 7 KOs, 3 items, major nav-tool audit

Loaded `session23_end_with_mira`. Woj's brief: playtest in careful mode — stop before/after every navigation decision, describe what the tool's showing, state intent, wait for confirmation. Goal was to sanity-check whether the nav tools actually communicate the situation clearly enough to act on. They did not, at first — this session surfaced **seven** distinct tool bugs, each fixed by the dev instance running in parallel.

### Cave traversal and trainer sweep
Starting position: Wayward Cave main branch (42, 53), Mira follower at (38, 42) standby. Worked outward from the entry chamber, clearing trainers along the BFS-reachable set:

- **Hiker Reginald** (Dugtrio Lv26, Sand Veil + Sturdy). Rough fight — Dugtrio cycles Dig and outspeeds Luxray. Howl on the burrow turn, Ice Fang into surface turn didn't OHKO due to Sturdy-free-Gen4, ended up swapping Luxray → Grotle (Grass resists Ground) → Swinub (Ice Shard priority for the KO). Needed 2 Super Potions to patch Grotle and Swinub through the Dig cycles.
- **Hiker Lorenzo** (Rhyhorn Lv25, Sudowoodo Lv25). Luxray Ice Fang 2× SE 2HKO'd Rhyhorn. Free-switch prompt used to bring in Prinplup for Sudowoodo — Scald 2× SE 2HKO'd it. Sudowoodo Mimic'd Scald off Prinplup.
- **Youngster Wayne** (Loudred Lv25, Raticate Lv25). Luxray Crunch STAB OHKO'd both Normal-types. Free-switch used to rotate Monferno in for the Meowth/Eevee line on the next battle.
- **Lass Cassidy** (Skitty Lv24 / Meowth Lv24 / Eevee Lv24). Luxray Crunch'd Skitty, Monferno Flame Wheel chained through Meowth + Eevee. Eevee tried a Wish that never resolved (KO'd first). Monferno Lv27 → **Lv28**.
- **Picnicker Tori** (Psyduck Lv25, Nidorina Lv25). Grotle (now lead, per session 28 lead swap — see below) opened with Razor Leaf 2× SE OHKO on Psyduck despite Screech dropping Def -2. Nidorina is Poison → swapped to Monferno, who 2HKO'd with Flame Wheel. Nidorina set Toxic Spikes before dying.
- **Camper Diego** (Aipom Lv25, Nidorino Lv25). Grotle Bullet Seed 5-hit crushed Aipom. Grotle Lv24 → **Lv25** mid-battle; declined the learned move (unknown — Renegade Platinum may have shifted Grotle's Lv25 learn, but staying with Bulldoze/Cut/Bullet Seed/Razor Leaf for coverage). Swapped to Monferno for Nidorino — Flame Wheel 2HKO, Poison Point proc'd but Mira auto-healed post-battle.
- **Picnicker Ana** (Illumise Lv25, Furret Lv25). **First attempt wipe risk**: Luxray as lead took 38 dmg from Silver Wind 2× SE (Bug vs Dark — I had forgotten), then Illumise's 10% Silver Wind omni-boost proc'd on the switch-in hit. +1 Spe put Illumise at 87 speed (faster than Luxray's 69), +1 SpA turned Draining Kiss into a near-OHKO Fairy-SE hit on Luxray's Dark typing. No team member had any SE move against Bug/Fairy *except* Monferno's Flame Wheel, and Monferno's slower than +1 Illumise — a switch-in would have eaten a 2× SE DK before attacking. Woj let me revert to the pre-navigation checkpoint and swap Monferno to lead (reorder blocked at first by a Cut-in-sub-menu bug — see below). Re-engaged with Monferno leading: Flame Wheel 2× SE STAB Charcoal = clean OHKO on Illumise before Silver Wind's boost could fire. Then Mach Punch priority ×2 cleaned up Furret, ignoring its Agility boost.

### Items and minor finds
- **TM32 Double Team** — Pokéball in the west chamber at (8, 44).
- **Focus Band** — Pokéball in the north chamber at (7, 15).
- **Dusk Stone** — Pokéball at (44, 15) in the east traversal corridor.
- None of these triggered Mira's quest-complete dialogue. Mira's item is presumably still deeper in the cave — either obj:27 Pokéball at (72, 11) (not yet reached) or obj:1 Pokéball at (57, 53) (still unreachable, likely requires a puzzle path we haven't found).

### Party changes
- Reordered party mid-session: **Grotle to lead** after Woj pointed out Luxray Lv34 was overkill for Lv24-27 trainers. Later swapped **Monferno to lead** for the Illumise retry.
- Final party order: **Monferno Lv28, Luxray Lv34, Prinplup Lv26, Grotle Lv25, Swinub ✨ Lv28, Togepi Lv1**. All full HP (Mira auto-heal).
- Swinub leveled Lv26 → Lv27 → Lv28 via Exp. Share. Declined Take Down at Lv28 (Normal 90 pow w/ recoil + 85% acc is strictly worse than Swinub's existing Ice/Ground STAB kit).
- Grotle leveled Lv24 → Lv25 during a wild Sandshrew flee sequence (MOVE_LEARN interrupted a failed run — see bugs). Declined the move learn offered.
- Monferno leveled Lv27 → Lv28.
- Money: +$832 Reginald +$800 Lorenzo +$400 Wayne +$400 Cassidy +$400 Tori +$400 Diego +$400 Ana = **+$3,632 this session**.

### Tool bugs surfaced and fixed (dev instance ran in parallel; see DEV_HISTORY for details)
Every one of these was a real issue the nav tools had been hiding. Careful-mode playtest caught them one by one:

1. **2D BFS stuck inside 15×15 viewport** — first nav to Mira reported ~30 interactibles as "unreachable" when Mira was plainly walkable to. 2D fallback path was capped to the viewport. Fixed.
2. **Follower NPC marked as blocker** — after re-engaging Mira, pathfinding refused to route through her tile even though follower NPCs swap-place with the player. Fixed after Woj explained the swap mechanic.
3. **`flee_encounters` failed on facing step** — `navigate_to(poi='obj:15')` walked the path, then on the auto-face step a wild double encounter spawned (Geodude + Baltoy + Mira's Kadabra) and the flee path didn't cover the facing-trigger window. Fixed.
4. **`flee_encounters` broke on level-up mid-chain** — a failed run-attempt against wild Onix+Sandshrew let Mira's Kadabra KO one, Exp. Share leveled Grotle, MOVE_LEARN state interrupted the flee loop, tool returned `"unexpected state: MOVE_LEARN"`. Woj called this "technically correct" and deferred.
5. **`read_objects` early-exit on sparse arrays** — after a test-fleet cross-contamination revert, `view_map` showed Mira and the entire east wing "missing" from both reachable and unreachable lists. Root cause: Gen 4's LocalMapObjectManager evicts NPCs into non-contiguous slots; the scanner bailed at consecutive_empty ≥ 3 and dropped 23 objects silently. Fixed to read the full array.
6. **BFS reach capped at 150 steps** — far east trainers dropped off the reachable list as we moved deeper. Woj bumped cap to 250; newly-reachable obj:27 Pokéball at 171 steps appeared in the list.
7. **`reorder_party` silent failure with field-move** — Grotle knows Cut (HM field move), which adds a "Use" row to the Pokémon sub-menu above "Switch". The reorder tool's hardcoded cursor nav landed on Cut instead, returned `success: true`, party unchanged. Fixed + verify step added.

### Non-bug oddities for the record
- **Test-fleet cross-contamination** mid-session: one of the dev instance's test-suite threads attached to our live emulator socket (instead of a test worker socket), loaded test save states, and left us on Route 202 reading an Arrow Signpost near Sandgem Town. Recovered via `revert_to_checkpoint(4f7ce163)` back to the pre-contamination wild battle.
- **Silver Wind omni-boost proc** is a brutal status in this hack — a 10% chance to +1 every stat turns a Lv25 Bug into a threat to Lv34 mons. Worth remembering for future Bug encounters.

### Session Summary
- **Badges**: 2 (unchanged).
- **Trainers defeated**: 7 (Hiker Reginald, Hiker Lorenzo, Youngster Wayne, Lass Cassidy, Picnicker Tori, Camper Diego, Picnicker Ana). **+$3,632.**
- **Items obtained**: TM32 Double Team, Focus Band, Dusk Stone.
- **Items used**: 2 Super Potions (Reginald fight). Mira's auto-heal covered everything else.
- **Party**: Monferno **Lv28** (+1), Luxray Lv34, Prinplup Lv26, Grotle **Lv25** (+1), Swinub ✨ **Lv28** (+2), Togepi Lv1.
- **Location**: Wayward Cave main map 284 at (73, 29), on defeated Picnicker Ana's interaction tile. Mira standby at (72, 29). Save state: `session28_wayward_east_wing_mid_sweep`.
- **Remaining cave content**: Camper (77, 30) — 4 steps east (probable double-battle pair with Picnicker Ana, same pattern as earlier trainer pairs). Collector (91, 48) + Ruin Maniac (93, 48) — far east duo. Pokéball (72, 11) at 136 steps north. Pokéball (57, 53) still unreachable — likely gated by puzzle we haven't found yet.
- **Next session**: finish Camper → east-wing duo → obj:27 Pokéball → figure out the (57, 53) approach → return to Mira for the quest resolution → exit, clear the Psychic, into Mt. Coronet.

## Session 29 (2026-04-22): Mira's quest complete — cave cleared, exit to Route 206, nav-tool audit continued

Loaded `session28_wayward_east_wing_mid_sweep`. Same careful-mode brief as session 28: stop before/after every navigation decision, describe what the tools show, state intent, wait for confirmation.

### Trainer sweep (3 fights, all won clean)

- **Camper Parker** (Volbeat Lv25 Bug/Electric, Linoone Lv25 Normal). Monferno Flame Wheel crit OHKO'd Volbeat (2× on Bug). Linoone stayed out — Mach Punch priority 2×SE into Normal: first hit 48 dmg, Linoone survived with 32 HP and hit back Headbutt 31 dmg, second Mach Punch finished it. Monferno **Lv28 → Lv29**.
- **Collector Terry** (Gible Lv24, Bagon Lv24, Gabite Lv24 — Dragon lineup). Switched to Prinplup for **4× Icy Wind** against all three. Gible opened Sandstorm, then Icy Wind OHKO'd; Bagon OHKO by Icy Wind too (pleasant surprise — both were single-shots); Gabite used Dragon Rage (40 fixed) but Icy Wind OHKO'd it. **Prinplup took 3 OHKOs** for free XP through a chained type matchup. Prinplup earned significant XP but stayed Lv26.
- **Ruin Maniac Gerald** (Cubone Lv25, Probopass Lv25). Switched Grotle in for 4× Bulldoze on Probopass — but Gerald opened with Cubone, and Grotle's **Grass resists Ground** turned Bonemerang into a 9-dmg-across-2-hits love-tap. Grotle Bullet Seed cleaned Cubone in 2 hits, Knock Off crit removed Muscle Band mid-fight (item returned post-battle, Gen 4 behavior confirmed), Razor Leaf finished Cubone. Probopass outsped Grotle (speed tie; cave Probopass is faster than predicted), Power Gem hit for 34, Grotle's Bulldoze dropped Probopass's Speed and did 40 dmg — too slow with Grotle at 17 HP, so switched to Monferno, took a Rock Slide (18 dmg), Mach Punch priority OHKO'd Probopass at 1 HP (Sturdy was already consumed). 

### Exp. Share swap: Swinub → Togepi
Mid-trainer-sweep, Woj flagged that Togepi was sitting at Lv1 with no way to catch up, and Exp. Share had been on an already-overlevelled Swinub (Lv28) since Route 216. Used `take_item(party_slot=4)` + `give_item("Exp. Share", party_slot=5)` — both tools worked clean first try. Immediate dividend: after the Ruin Maniac fight, Togepi gained 529 XP in one burst and rocketed **Lv1 → Lv9**, learning **Metronome** at Lv2 (forgot Growl). Dazzling Gleam later from Mira (see below) gives Togepi a real offensive option once it evolves.

### Mira's Crimson Ribbon
With all trainers in the east wing cleared, navigated to the obj:27 Pokéball at (72, 11) — 60 steps north through the winding east-half corridors. Result: **"CLAUDE found a Crimson Ribbon! / Mira: That's it! That's Mira's special ribbon that she lost! / Thank you! Now, let's get out of this scary cave!"** Quest complete.

Approaching the exit warp at (41, 53) fired Mira's farewell dialogue: she rewards us with **TM85 Dazzling Gleam** (80-pow Fairy special, "It's a rare Fairy-type move that a lot of Pokémon can use!"). Earmarked for Togepi once it evolves.

### Route 206 exit + Cycling Road 3D test
Stepped onto `warp:1` at (41, 53), transitioned to Route 206 at **(310, 608)** — under the east side of the Cycling Road bridge. Same under-bridge pocket we entered from at start of Wayward Cave questing.

### Tool bugs surfaced this session (dev instance handling)

1. **BUG-024 wander guard retired** — the `max(manhattan*5, manhattan+30)` path-length cap from session 19 was false-positive'ing on legitimate long winding cave paths (Wayward Cave 101 steps for 17 Manhattan). Live repro of the original BUG-024 scenario (Cycling Road gate-house warp cluster) failed first at the BUG-030 elevation validator now — the length guard was redundant. Removed, committed in `e5c4b6c`.
2. **view_map BFS chunk window (BUG-039, resolved parallel)** — from (73, 29) mid-cave, `view_map` classified (41, 53) as unreachable despite being perfectly walkable (`navigate_to` got there fine). Dev-instance root cause: BFS wasn't scanning all loaded cave chunks. Resolved parallel.
3. **Bridge-Cyclist misclassified as ground-reachable (NEW, open)** — from (310, 608) under Cycling Road, `view_map` lists Cyclist obj:2 at (299, 611) as reachable in 35 steps and Cyclist obj:4 at (304, 631) as reachable in 30 steps. **Woj confirmed these cyclists should only be on the bridge (3 elevation levels up), not at ground level.** They render next to the cave-entrance tiles because the 2D projection flattens the bridge atop the under-bridge pocket. The 3D BFS is failing to exclude them from ground-level reachability. Repro save: `session29_exited_wayward_under_bridge`.
4. **BUG-038 multi-level-up cascade (open)** — Togepi's Lv1→Lv9 jump in the Ruin Maniac fight exposed three minor issues: (a) `battle_turn(forget_move=0)` at Metronome learn committed silently but didn't surface a "learned Metronome" log entry; (b) `battle_turn(forget_move=-1)` at a later chained level-up returned `final_state=NO_TEXT` with the "Make it forget" prompt still on-screen; (c) mid-transition `read_party` returned stale save-block data (Togepi Lv1 with old moves while Monferno HP was current). Repro: `bug_togepi_cascade_levelup`.

### Session Summary
- **Badges**: 2 (unchanged).
- **Trainers defeated**: 3 (Camper Parker, Collector Terry, Ruin Maniac Gerald). 10/10 trainers cleared in Wayward Cave across sessions 28+29. 
- **Items obtained**: **TM85 Dazzling Gleam** (Mira's quest reward). Crimson Ribbon picked up during the quest but consumed/given back.
- **Items used**: 0 (Mira's auto-heal covered every fight).
- **Party**: Monferno **Lv29** (+1), Luxray Lv34, Prinplup Lv26, Grotle Lv25, Swinub ✨ Lv28, Togepi **Lv9** (+8!). Full HP (Mira final auto-heal on exit).
- **Party changes**: Exp. Share moved from Swinub → Togepi. Togepi learned Metronome (replaced Growl).
- **Mira**: quest complete, she's left the party. Cave freely traversable.
- **Location**: Route 206 (310, 608) on foot, under Cycling Road bridge. Save state: `session29_exited_wayward_under_bridge`.
- **Bugs filed**: BUG-024 retired (see DEV_HISTORY). BUG-039 resolved parallel. Open: BUG-038 (multi-level cascade) + new bridge-level-reachability bug (unnumbered, session 30 dev).
- **Next session**: Woj called for a **dev-focused session next** to unravel the bridge reachability bug + BUG-038 cascade rather than continuing the playthrough. After that: clear Cyclist obj:4 (only remaining undefeated trainer on under-bridge Route 206 south), pick up Pokéballs at (292, 623) and (314, 631), confirm the under-bridge → south gate → Route 207 path works, push north to Route 207's Psychic Arianna, then Mt. Coronet.

## Session 31 (2026-04-22): Wayward Cave diagnostic — bike slopes climbed, bike ramps surfaced

Loaded `session30_route206_under_bridge`. Careful-mode brief from Woj: stop before/after every navigation decision, describe what the tools show, wait for confirmation — continuing the audit of how navigation communicates multi-level map state. No real playthrough objectives this session; the intent was to critically test the updated nav tools through a well-understood puzzle room (west-secret Wayward Cave entry → bike slopes → the item chamber).

### Diagnostic excursion (player never left the cave secret branch)

- From Route 206 (310, 608): first `navigate_to(poi="warp:7", flee_encounters=True)` failed with `"No reasonable path at your current elevation (level 1). The 2D fallback would step between incompatible layers."` despite `view_map` listing the west Wayward Cave warp at (299, 611) as reachable in 26 steps. The view_map/navigate_to disagreement was the first concrete repro of the under-bridge 3D pathfind bug — dev agent resolved as **BUG-041** (commit `1b7915e`, session 31a).
- After MCP reload, retried the same call — succeeded. Path `down x4 → left x12 → up x5`, 21 steps, 1 Slugma fled. Landed in Wayward Cave map 284 `D21R0101` at (30, 55), the tiny west-entry antechamber (separate from the main cave cleared in sessions 28-29).
- `navigate_to(poi="warp:2")` → Wayward Cave map 285 `D21R0102` at (16, 40). This is the bike-slope puzzle room.
- Walked west 7 tiles with `navigate(l7)` to (9, 40). `view_map` surfaced the **first N-S bike slope at (7, 37-38)** (`\=bike_slope_top` over `/=bike_slope_bottom`) — confirming Woj's memory that the obstacle was a bike slope, not a rock-climb wall.
- `navigate_to(x=7, y=33)` first attempt: **failed** with `blocked_reason: "bike_slope_traversal_failed"` at (7, 39). Retry succeeded — slope climbed cleanly, ended at (7, 32). But the returned metadata was wrong: `start: (7, 36)` (actual (7, 39)), `path: "up x3"` (actual 7-tile excursion). Filed as **BUG-044** (open, low priority — traversal works, just reports wrong positions).
- From (7, 32): the **second N-S bike slope** became visible at (7, 26-27). `navigate_to(x=7, y=25)` traversed it successfully, this time with a richer response (`obstacles_cleared: [{type:bike_slope, tiles:2, x:7, y:27}]`). Final landed at (7, 22), overshooting target by 3 — same BUG-044 metadata glitch.
- At (7, 22): all four east-chamber POIs (Pokéballs at (22, 9), (31, 16), (33, 8) + exit warp `warp:0` at (43, 38)) reported as `unreachable_interactibles` with **Manhattan-equal BFS distances** (28 / 30 / 40 / 52) — BFS couldn't even find a partial path. Entire east half of the cave was a disconnected graph component.
- Legend advertised `?=bike_ramp_E` but **no `?` glyph ever appeared in any viewport**. Visual screenshot (`logs/wayward_cave_bike_ramps.png`) showed bright yellow bike-ramp tiles plainly, with raised rock platforms flanking them — BFS was treating the ramp tiles as walls. Filed as **BUG-042** (ramp rendering + BFS edges).
- Dev agent added bike-ramp BFS edges, auto-mount, glyph emission (`>` for east-facing), plus a companion **LEDGE_DIRECTIONS decomp-mismatch fix** (the `>>>>` at row 22 cols 11-14 turned out to be `ledge_S` mis-classified as `ledge_E`; now renders correctly as `vvvv`). Committed as `390adf0` + `ec0f47c`.
- After MCP reload: re-ran `view_map`. Confirmed `>` bike_ramp_E now renders at (10, 17); `vvvv` ledge_S now renders at (11-14, 22). **But** east-chamber POIs *still* unreachable — the session-31b ramp-jump-distance model (2 tiles past entry) turned out to be wrong for fast-gear bicycle. Reopened in session 32 as **BUG-043** — actual fast-gear jump is 3 tiles past the ramp (not 2). Gear-dependent (slow gear lands at +1, fast gear at +3). Also requires continuous-hold direction input, not per-tile presses.
- Woj called session here to hand off to a focused dev session for BUG-043.

### Tools validated this session
- **Berry-soil preview** (dev session 30c, new) — confirmed working. Both Rawst Berries under the bridge (obj:15/16 at (293-294, 627)) and the currently-unreachable Razz Berries past the south gate (obj:17/18 at (295-296, 691)) returned full patch state: `{berry: "Rawst"/"Razz", growth_stage: "fruit", yield: 1, harvestable: true, moisture: "moist", ...}`. Huge QoL — no more blind-interacting with soils to find what's planted.

### Session Summary
- **Badges**: 2 (unchanged). **No trainers defeated, no items collected, no story progress.** Four wild encounters fled during navigation (Slugma, Baltoy x2, Onix).
- **Party**: unchanged from session 30 — Monferno Lv29, Luxray Lv34, Prinplup Lv26, Grotle Lv25, Swinub ✨ Lv28, Togepi Lv9. Full HP throughout.
- **Location**: Wayward Cave B1F map 285 `D21R0102` at (7, 22). Save state: `session31_wayward_cave_bike_ramps` (primary use: BUG-043/BUG-044 repro for next dev session).
- **Playthrough resumption save**: `session30_route206_under_bridge` is still the correct entry for the next *real* play session (Route 206 under-bridge objectives remain unchanged).
- **Bugs filed**: **BUG-041** (fixed session 31a — elevation-aware 3D pathfind under bridge), **BUG-042** (fixed session 31b — bike-ramp BFS edges + auto-mount + glyph emission; chamber connectivity follow-up in BUG-043), **BUG-043** (open — gear-dependent ramp jump distance + continuous-hold input requirement), **BUG-044** (open — bike slope traversal metadata misreport). Also **LEDGE_DIRECTIONS decomp fix** shipped in session 32 as a side-discovery.
- **Next session**: dedicated dev work on BUG-043 (needs dual slow/fast gear BFS edges, path-executor rewrite to emit continuous east-hold instead of per-press, regression tests asserting all three east-chamber POIs become reachable from `session31_wayward_cave_bike_ramps`). After BUG-043: resume real playthrough from `session30_route206_under_bridge`.
