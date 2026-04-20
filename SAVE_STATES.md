# Save States (melonDS)

## Gameplay Progression

| Name | Description |
|------|-------------|
| `eterna_city_pokecenter_melonds` | Eterna City Pokemon Center. 5 Pokemon party. 1 Badge (Coal). Post-Eterna Forest. |
| `eterna_city_pre_gardenia` | Eterna City Pokemon Center. Healed. Explored city, got HM01 Cut + Sun Stone + TM46 Thief + TM69 Rock Polish. Grotle knows Cut. Need to reach Route 216 via Mt. Coronet to find Gardenia. |
| `route216_snow_nav_bug` | Route 216 at (331, 396). Mid-route exploration, defeated Ace Trainer Laura (Togetic/Swellow). Charmeleon fainted. Nav tools broken on snow tiles — needs fix before continuing. |
| `route216_lodge_healed` | Route 216 Snowbound Lodge, fully healed. Pre-Swinub hunt. |
| `route216_grass_swinub_hunt` | Route 216 tall grass west of lodge (295, 393). Past Ace Trainer Garrett. Ready for wild encounters. |
| `route216_shiny_swinub_caught` | Route 216 tall grass. Just caught SHINY Swinub (perfect Atk IV). Pre-heal. |
| `route216_lodge_post_shiny` | Route 216 Snowbound Lodge, fully healed. 6 party + shiny Swinub in Box 1. Session end. |
| `route211_from_coronet` | Route 211 east at (419, 527). Just exited Mt. Coronet east side. Pre-trainer battle. |
| `eterna_city_shiny_swinub_in_party` | Eterna City Pokemon Center. Shiny Swinub in party (slot 5, Never-Melt Ice). Healed. Ready for Gardenia. |
| `eterna_city_pre_gardenia_rematch` | Eterna City Pokemon Center. Post-Gardenia scout wipe. TMs not yet taught. Pre-grind. |
| `bug_auto_grind_torment_loop` | Route 205 mid-battle. Machop Lv22 vs Croagunk Lv16 (Torment). auto_grind stopped. |
| `eterna_city_grind_complete_pre_gardenia` | Eterna City Pokemon Center. Main team at 25. Swinub still in party. Pre-Chimchar swap. |
| `eterna_city_chimchar_ready_to_grind` | Eterna City Pokemon Center. Chimchar Lv12 in party (Exp. Share). Swinub deposited. Ready to grind Chimchar. |
| `eterna_city_monferno_grind_complete` | Eterna City Pokemon Center. Luxray Lv30, Monferno Lv25, rest Lv24-25. Route 205 grind done. Pre-Gardenia. |
| `pre_gardenia_rematch_v2` | Eterna City overworld, south of Pokemon Center. Full team healed. About to enter gym for Gardenia rematch. |
| `post_gardenia_forest_badge` | Eterna Gym interior, post-Gardenia dialogue. Forest Badge + TM86 Grass Knot obtained. |
| `eterna_city_post_gardenia_team_updated` | Eterna City Pokemon Center. 2 Badges (Coal + Forest). Charmeleon deposited, Swinub ✨ withdrawn. Monferno has Charcoal, Swinub has Exp. Share. |
| `eterna_city_galactic_building_doorstep` | Eterna City at (304, 520), one tile SW of T.G. Eterna Bldg warp (305, 519). Grunt NPC at (305, 520). Ready to enter Team Galactic HQ. |
| `route206_post_togepi_hatch` | Cycling Road (304, 577) on bike, Togepi hatched from egg into slot 5 (Lv1 Timid, Serene Grace). Explorer Kit obtained. Full team healed. Heading south to Route 207. |
| `route207_larvitar_caught` | Route 207 (295, 721) grass, Togepi Lv1 hatched, Larvitar Lv9 caught and sitting in PC Box 1 (slot 2, from the Renegade Platinum grass encounter table). Prinplup at 11/75 HP, rest healed. Explorer Kit obtained. 6 Cyclists defeated on the Cycling Road. Need to heal Prinplup and train Larvitar. |
| `oreburgh_pc_healed_session18` | Oreburgh City Pokemon Center (8, 6) inside. Full team healed post-Route 207 Larvitar hunt. 10 Super Potions + 5 Repels stocked; ¥12,644. |
| `route207_post_hiker_kevin` | Route 207 (319, 716) on bicycle. Picnicker Lauren + Camper Anthony + Hiker Kevin defeated. Luxray Lv33 (learned Crunch), Prinplup Lv26 (learned Scald). Grotle fainted, party damaged — pre-Youngster Austin detour. |
| `route207_all_nearby_trainers_defeated` | Route 207 (327, 715) on bicycle, next to Pokeball #2. All 4 Route 207 east-cluster trainers (Picnicker/Camper/Hiker/Youngster) defeated. Hard Stone collected. Full team still damaged — pre-heal trip. |
| `route207_north_of_slope_session18_end` | **CURRENT** — Route 207 (306, 714) on the bicycle, Repel active, full healed party. Just crested the bike slope (BUG-025 workaround verified: mount bike before any north-crossing nav call). Session 18 wrap. Next: push north to Mt. Coronet entrance. |

## Debug & Testing

| Name | Description |
|------|-------------|
| `route211_west_pre_trainer` | Route 211 west at (368, 524). Pre-trainer (Bird Keeper Alexandra 1 tile left). 6 Pokemon party, full HP. |
| `bug_wild_faint_switch_trainer_error` | Route 205 mid-battle. Charmeleon vs Volbeat Lv17, Luxio fainted. `battle_turn(run=True)` errored "Must switch in a trainer battle" on a wild battle. |
| `bug_move_learn_skip_fire_fang_stuck` | Route 205 mid-battle. Luxio Lv24, "give up on Fire Fang?" prompt. `forget_move=-1` fails to dismiss. |
| `bug_qa_throw_ball_state_mismatch` | QA save, Route 202 overworld. Shinx just caught (5th ball). `throw_ball` JSON says CAUGHT but `formatted` string ends `State: TIMEOUT`. Cosmetic. |
| `bug_qa_auto_grind_faint_switch_stuck` | QA save, Route 202 mid-battle. Wild Rattata, Shinx FNT, party grid on bottom. `auto_grind(auto_heal=True)` failed with `heal_failed` / "Failed to exit battle after faint. State: WAIT_FOR_ACTION" — prompt misclassified as FAINT_FORCED. |
| `bug_qa_auto_grind_evolution_stop_lingering_dialogue` | QA save, Route 202 grass at (163,805). "Huh? Chimchar stopped evolving!" dialogue hanging. Chimchar Lv14 with Flame Wheel learned — move-learn ok, evolution cancelled by stray B press. |
| `bug_qa_battle_turn_stuck_after_double_ko_doubles` | QA save, Route 203 mid-doubles Lass tag. Monferno 28/54 vs Azurill 20/29 (1v1 collapsed from doubles; Shinx + Sunkern both fainted). Target-pick submenu open, battle_turn returns `ACTION` with no damage. |
| `jubilife_mart_after_buy_5potions` | QA save, inside Jubilife Mart (map 4) at (3,7), ¥1948, 0 badges. **BUG-006 repro** — call `buy_item("Potion", 1)` and the tool returns `success: true` but leaves the game on the "Potion? Certainly. / How many would you like?" quantity prompt instead of driving back to overworld. |
| `fr001_repro_growlithe_battle_prompt` | QA save, mid-battle vs wild Growlithe Lv6 on Route 202, action prompt up, Chimchar Lv13 @ 25/38 HP. **BUG-005 repro** — `read_dialogue(advance=False, region="battle")` returns `"What will Chimchar do?[VAR][0200][0001][0000]"` in one call (placeholder leak). Same class of codes (`[25BD]`, `[FFFE]`) appears throughout battle logs from this point forward. |
| `debug_pokeball_cutscene_interrupt` | Eterna City at (326, 516). `interact_with(object_index=21)` on Pokeball triggers Cynthia cutscene with delayed dialogue. |
| `debug_signpost_blocking_navigate` | Route 211 at (352, 531). Arrow Signpost at (353, 531) blocks BFS pathfinding east. |
| `debug_route211_bridge_pathfind` | Route 211 at (377, 532). 3D BFS walks off bridge to reach Pokeball at (368, 535). |
| `debug_route216_blocked_down` | Route 216 at (374, 402). Deep snow movement timing bug — nav code reports impassable but `advance_frames` with held direction moves fine. |
| `route216_snow_nav_bug_v2` | Route 216 at (298, 404). Navigate blocks after 2 tiles going north in snow — works on immediate retry. melonDS era. |
| `debug_coronet218_3d_path_blocked` | Mt. Coronet map 218 at (29, 31). navigate_to(29, 35) fails 3D BFS but manual nav works. |
| `debug_doubles_target_swapped` | Route 211 double battle start. target=0/1 reversed — target=0 hits right enemy. |
| `debug_doubles_faint_switch_bug` | Route 211 double battle. Machop's turn, about to faint. battle_turn(switch_to=N) returns NO_ACTION_PROMPT after faint. |
| `debug_heal_party_dialogue_stuck` | Eterna City PC, pre-heal. heal_party doesn't dismiss final "We hope to see you again!" text. |
| `debug_deposit_extra_a_press` | Eterna City PC storage menu. deposit_pokemon presses extra A before navigating to target slot. |
| `qol_battle_wipe_blackout_handling` | Post-wipe blackout state. Used for developing auto-blackout handling in battle_turn. |
| `bug008_cheryl_trainer_01e0_01e1_codes` | QA save, mid-Cheryl battle in Eterna Forest. **BUG-009 repro** — `battle_turn` log lines containing `"Pokémon Trainer Cheryl"` leak as `[01E0][01E1] Trainer Cheryl`. Loaded state is early-conversation; trigger the full battle from `eterna_forest_entered_south` instead for deterministic repro. |
| `bug_shinx_max_hp_garbled_read_party` | QA save, Eterna Forest (29, 86) facing up. **BUG-010 repro companion** — `read_party` reported Shinx slot 3 `max_hp=37988` on fresh load. Primary repro state is `eterna_forest_entered_south`; this one is a secondary observation point. |
| `eterna_forest_entered_south` | Eterna Forest entry, Monferno Lv27 lead, 4 Pokemon party incl. Shinx slot 3 (PC-round-tripped). **BUG-010 primary repro** — fresh load shows Shinx `max_hp=37988` pre-fix. Also used as BUG-009 entry (navigate to Cheryl at (28,83) to start the Pokémon Trainer-prefixed battle). |
| `forest_exit_route205_north_post_cheryl` | Route 205 north grass, 4 Pokemon party, post-Cheryl checkpoint. **BUG-011 primary repro** — `seek_encounter` surfaces an orphan `"Slowpoke"` log entry before `"A wild Slowpoke appeared!"` pre-fix. |
| `eterna_forest_cheryl_doubles_mid_battle_buneary_paras` | QA save, mid-Cheryl double battle with wild Buneary + Paras. Imported for future doubles-flow regression — not yet referenced in tests. |
| `bug009_cheryl_post_drifloon_ko` | Playtest-created, Cheryl battle right after Drifloon KO, Wailmer incoming. Ad-hoc checkpoint kept for future Cheryl-line text investigations. |
| `bug011_cheryl_post_wailmer_ko` | Playtest-created, switch-prompt state post-Wailmer KO with Vaporeon's level-up consumed. Checkpoint for revisiting post-level-up log flows if needed. |
| `qa_session16_map75_pre_jupiter_battle` | QA-imported (copied from QA session 16). Galactic Eterna Bldg top floor (map 75) at (21, 6), facing Jupiter at (14, 6). Monferno Lv33 75/99, party Vaporeon/Mothim/Shinx, Super Potion x9 in Medicine. Walk 6 tiles west + interact to engage Jupiter's Golbat. Source fixture for `bug022_jupiter_battle_pre_super_potion`. |
| `bug022_jupiter_battle_pre_super_potion` | Frozen at Jupiter's battle action prompt after engaging from `qa_session16_map75_pre_jupiter_battle`. Monferno Lv33 75/99 vs Golbat Lv26. Used by `test_qa_bug022_battle_turn_use_item_log.py` to verify `battle_turn(use_item=...)` now surfaces the enemy's reciprocal action in the turn log. |
| `route206_pre_togepi_hatch` | Route 206 Cycling Road (304, 576) on bicycle, post-Explorer-Kit. Togepi egg in slot 5 at hatch threshold (~5000 steps accumulated). **BUG-023 repro** — call `navigate_to(304, 640)` and after ~6 tiles south the egg hatch "Oh?" dialogue fires, but `navigate_to` classifies it as `encounter.encounter == "dialogue"` identical to a trainer/NPC encounter. Expected: distinct encounter type like `egg_hatch` so callers can differentiate. |
| `route206_cyclingroad_end_nav_repro` | Route 206 (302, 681) on bicycle, just past the 2nd Cycling Road gate exit into Route 206 ground section. **BUG-024 repro** — call `navigate_to(302, 688)` (the warp destination south). The pathfinder wanders `up x19 -> right x3 -> up x8 -> right x4 -> down x31 -> right -> down x11 -> left x6 -> up x8 -> left x2` (12 "steps" reported but dozens of repath cycles) and ends at (299, 680) with `warp_failed`. Manual single-step navigation downward works fine. Likely caused by the side-warp tiles at y=681 re-triggering warp logic on every re-plan. |
| `bug_bike_slope_north_climb_fail` | Route 207 (299, 730) facing right, **on foot**, full 6-Pokemon healed team (session 18). **BUG-025 repro** — call `navigate_to(305, 715)` (or any target north of the slope). Tool runs 15 repaths and stalls at (306, 720) silently because slope traversal requires the bicycle. Verified workaround: `use_item("Bicycle")` from the stall position then retry the same nav — succeeds in 1 repath with `obstacles_cleared: bike_slope`. Suggested fix: auto-mount bicycle for slope obstacles like navigate_to already auto-Surfs. |
| `bug_battle_turn_use_item_throws_pokeball` | Mid-trainer-battle vs Youngster Austin's Lombre Lv25 on Route 207. Luxray Lv33 38/109 burned (pre-Fake Out). **BUG-026 repro** — call `battle_turn(use_item="Super Potion", party_slot=3)` and the tool throws a Poké Ball at the opposing trainer instead (`"The Trainer blocked the Ball!"`). Tool's `formatted` field falsely reports `"Used Super Potion on Monferno"` — no healing occurs. Likely wrong bag pocket tab routed. |

## Test Suite

| Name | Description |
|------|-------------|
| `test_wild_battle_action` | Route 216 wild Smoochum battle at action prompt. Prinplup Lv21 (lead) vs Smoochum Lv19. 5 Pokemon party. Hail active. |
| `test_eterna_city_overworld` | Eterna City at (305, 530) facing down. Outside Pokemon Center. 6 Pokemon party (shiny Swinub). Open streets, nearby NPCs/signs/doors. |
| `test_damaged_party_overworld` | Route 216 grass. Prinplup at 32/66 HP (48%), rest full. 5 Pokemon party. Overworld, post-battle. |
| `test_npc_dialogue_active` | Eterna City at (301, 530). Mid-dialogue with Galactic Grunt: "Hey, you! Yeah, you, Trainer!" text on screen. |
| `test_trainer_battle_action` | Route 211 west trainer battle at action prompt. Luxio Lv21 (lead) vs Bird Keeper Alexandra's Natu Lv20. 6 Pokemon party. Trainer has 2 Pokemon (Natu, Swablu). |
| `test_move_learn_prompt` | Route 211 west trainer battle. At "Make it forget?" prompt — Prinplup wants to learn Icy Wind (knows Metal Claw/Growl/Bubble Beam/Peck). Mid-battle after KO'ing Swablu. |
| `cycling_road_edge` | Route 206 at (304, 592). On bicycle, last ground tile before bridge body tiles (0x71) start. Used for cycling road navigation tests. |

## HM Field Move Testing (Wayne's E4 Save)

All states use Wayne's 8-badge team with full HM coverage:
Fly (Garchomp), Surf (Swampert), Rock Smash (Nidoking), Strength (Nidoking), Rock Climb (Nidoking), Cut (Gallade), Waterfall (Crawdaunt).

| Name | Description |
|------|-------------|
| `e4_hm_base_all_moves` | Pokemon League lobby. Base state with all HMs taught. Dusknoir still in party (deposit failed). |
| `hm_test_surf_canalave` | Canalave City at (51, 729). Canal water walled off — not suitable for direct Surf testing. |
| `hm_test_surf_route218` | Route 218 at (121, 758). East side of canal, gate entrance. |
| `hm_test_surf_route218_at_water` | Route 218 at (112, 754). Adjacent to water edge. **Best Surf test location** — navigate west to (100, 756) crosses water. |
| `hm_test_surf_waterfall_pokemon_league` | Pokemon League outdoor at (847, 560). Obstacle BFS confirms path south requires Surf + Waterfall. |
| `hm_test_rock_smash_mt_coronet` | Mt. Coronet map 207 (Route 208 entrance) at (4, 8). 4 Rock Smash objects present (coords show 0,0 in view_map — runtime loading issue). Rocks treated as impassable post-2026-04-15 trim. |
| `hm_test_rock_smash_oreburgh_mine_b2f` | Oreburgh Mine B2F at (18, 28). Standing between two decorative Rock Smash rocks at (17, 28) and (19, 28). Used to verify rocks are impassable (`TestRockSmashImpassable`) rather than auto-cleared. |
| `hm_test_cut_surf_route214` | Route 214 at (725, 678). Obstacle BFS detected Cut tree at (731, 648) + Surf tiles on path when auto-clear was enabled; Cut tree is now impassable, Surf portion still exercised if retained. |
| `hm_test_rock_climb_veilstone` | Veilstone City at (691, 617). South of a 2-tile Rock Climb wall at (691, 615-616). Navigate to (691, 614) = 3 steps through wall. 68-step clean path around. |

### Bike Slope Test States
| `route207_bike_slope_area` | Route 207 at (297, 720). Near bike slopes. E4 save (8 badges). Overview position. |
| `route207_at_bike_slope_bottom` | Route 207 at (306, 720). On bicycle, 1 tile south of bike slope bottom (0xDA at 306,719). E4 save. **Best bike slope test location.** |

### Move Services Test States
| `move_relearner_pastoria` | Pastoria City at map 129 (C06R0401), inside the Move Relearner's house. E4 save (8 badges). NPC "Collector" is the relearner. |
| `move_deleter_oreburgh` | Oreburgh City at map 58 (C03R0301), inside the Move Deleter's house. E4 save (8 badges). NPC "Old Man" is the deleter. |

### No longer needed
- **Cut / Rock Smash (standalone)** — Renegade Platinum removes every path-gating Cut tree and Rock Smash rock (per the hack's documented changes, confirmed by on-cam verification at Oreburgh Mine B2F on 2026-04-15: rocks are trivially walkable-around). Both GFX types are now treated as impassable; no new save states needed.
- **Strength** — The only mandatory Strength obstacle in Renegade is the Distortion World B5F/B6F Lake Guardian boulder puzzle. When reached, handle manually with `press_buttons` rather than building a full HM tool — it's a one-time, 3-boulder puzzle.

### ROM data reference
Full HM obstacle scan in `romdata/zone_event/` (scan performed pre-trim — kept for historical reference):
- **Cut trees (gfx=86)**: 335 across 107 archives. All have story flags. Eterna City (327,516) and (317,558) gated behind Galactic flags. Now treated as impassable.
- **Rock Smash (gfx=85)**: 49 across 19 archives. Most placeholder coords (0,0). Oreburgh Mine B2F has verified (17,28) and (19,28) — confirmed decorative. Now treated as impassable.
- **Strength boulders (gfx=84)**: 111 across 21 archives. Most placeholder coords — the real puzzle boulders spawn at runtime in Distortion World B5F (`MAP_OBJECT_B5F_UXIE_BOULDER`, `_AZELF_BOULDER`, `_MESPRIT_BOULDER`).
- **Rock Climb (0x4A/0x4B)**: 34 land_data chunks. Most in Mt. Coronet, some Route 216/217.

---

*DeSmuME-era save states (.dst) are documented in [LEGACY_SAVE_STATES.md](LEGACY_SAVE_STATES.md). These are not compatible with melonDS but preserved for reference.*
