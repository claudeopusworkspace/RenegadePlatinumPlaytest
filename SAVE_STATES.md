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
| `eterna_city_post_gardenia_team_updated` | **CURRENT** — Eterna City Pokemon Center. 2 Badges (Coal + Forest). Charmeleon deposited, Swinub ✨ withdrawn. Monferno has Charcoal, Swinub has Exp. Share. |

## Debug & Testing

| Name | Description |
|------|-------------|
| `route211_west_pre_trainer` | Route 211 west at (368, 524). Pre-trainer (Bird Keeper Alexandra 1 tile left). 6 Pokemon party, full HP. |
| `bug_wild_faint_switch_trainer_error` | Route 205 mid-battle. Charmeleon vs Volbeat Lv17, Luxio fainted. `battle_turn(run=True)` errored "Must switch in a trainer battle" on a wild battle. |
| `bug_move_learn_skip_fire_fang_stuck` | Route 205 mid-battle. Luxio Lv24, "give up on Fire Fang?" prompt. `forget_move=-1` fails to dismiss. |
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
| `hm_test_surf_canalave` | Canalave City at (51, 729). Adjacent to canal water tiles. Surf test. |
| `hm_test_surf_waterfall_pokemon_league` | Pokemon League outdoor at (847, 560). Obstacle BFS confirms path south requires Surf + Waterfall. |
| `hm_test_rock_smash_mt_coronet` | Mt. Coronet map 207 (Route 208 entrance) at (4, 8). 4 Rock Smash objects present (coords show 0,0 in view_map — runtime loading issue). |
| `hm_test_rock_smash_oreburgh_mine_b2f` | Oreburgh Mine B2F at (18, 28). Standing between two Rock Smash rocks at (17, 28) and (19, 28). Best Rock Smash test location. |
| `hm_test_cut_surf_route214` | Route 214 at (725, 678). Obstacle BFS detected Cut tree at (731, 648) + Surf tiles on path. Combined Cut + Surf test. |

### Still needed
- **Cut (standalone)** — All cut trees have story flags; may need our playthrough save (2-badge, pre-Galactic) for Eterna City trees.
- **Strength** — Oreburgh Mine B2F objects are Rock Smash, not Strength. Need cave with actual Strength boulders (gfx=85). Reliable ROM coords: Stark Mountain Room 3 (10, 13).
- **Rock Climb** — Route 217 and Mt. Coronet have walls (behaviors 0x4A/0x4B). Both require Surf or bike slopes to reach. Consider approaching from Acuity Lakefront.

### ROM data reference
Full HM obstacle scan in `romdata/zone_event/`. Key findings:
- **Cut trees (gfx=87)**: 335 across 107 archives. All have story flags. Eterna City (327,516) and (317,558) gated behind Galactic flags.
- **Rock Smash (gfx=86)**: 49 across 19 archives. Most have placeholder coords (0,0). Oreburgh Mine B2F has verified (17,28) and (19,28).
- **Strength boulders (gfx=85)**: 111 across 21 archives. Most placeholder coords. Oreburgh Mine B2F (19,28)/(17,28) per ROM but show as Rock Smash in-game.
- **Rock Climb (0x4A/0x4B)**: 34 land_data chunks. Most in Mt. Coronet, some Route 216/217.

---

*DeSmuME-era save states (.dst) are documented in [LEGACY_SAVE_STATES.md](LEGACY_SAVE_STATES.md). These are not compatible with melonDS but preserved for reference.*
