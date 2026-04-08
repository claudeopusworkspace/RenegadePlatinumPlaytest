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

## Debug & Testing

| Name | Description |
|------|-------------|
| `route211_west_pre_trainer` | Route 211 west at (368, 524). Pre-trainer (Bird Keeper Alexandra 1 tile left). 6 Pokemon party, full HP. |
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

## Test Suite

| Name | Description |
|------|-------------|
| `test_wild_battle_action` | Route 216 wild Smoochum battle at action prompt. Prinplup Lv21 (lead) vs Smoochum Lv19. 5 Pokemon party. Hail active. |
| `test_eterna_city_overworld` | Eterna City at (305, 530) facing down. Outside Pokemon Center. 6 Pokemon party (shiny Swinub). Open streets, nearby NPCs/signs/doors. |
| `test_damaged_party_overworld` | Route 216 grass. Prinplup at 32/66 HP (48%), rest full. 5 Pokemon party. Overworld, post-battle. |
| `test_npc_dialogue_active` | Eterna City at (301, 530). Mid-dialogue with Galactic Grunt: "Hey, you! Yeah, you, Trainer!" text on screen. |
| `test_trainer_battle_action` | Route 211 west trainer battle at action prompt. Luxio Lv21 (lead) vs Bird Keeper Alexandra's Natu Lv20. 6 Pokemon party. Trainer has 2 Pokemon (Natu, Swablu). |
| `test_move_learn_prompt` | Route 211 west trainer battle. At "Make it forget?" prompt — Prinplup wants to learn Icy Wind (knows Metal Claw/Growl/Bubble Beam/Peck). Mid-battle after KO'ing Swablu. |

---

*DeSmuME-era save states (.dst) are documented in [LEGACY_SAVE_STATES.md](LEGACY_SAVE_STATES.md). These are not compatible with melonDS but preserved for reference.*
