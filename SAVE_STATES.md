# Save States

## Gameplay Progression

| Name | Description |
|------|-------------|
| `game_start_bedroom` | After intro, in bedroom, BEFORE Barry's dialogue |
| `post_barry_bedroom` | In bedroom, AFTER Barry leaves. Position (4,7) on map 415. |
| `living_room` | Downstairs in the living room, BEFORE Mom's dialogue. Position (10,3) on map 414. |
| `post_mom_living_room` | Downstairs, AFTER Mom gives Running Shoes. Free to move. |
| `first_battle_start` | Rival battle vs AAAAAAA's Chimchar Lv5. At "What will Turtwig do?" menu. |
| `post_rival_battle_twinleaf` | After rival battle, outside in Twinleaf Town (map 411). Turtwig Lv6. |
| `post_lake_verity_cutscene` | After Lake Verity cutscene (Cyrus + Barry). Verity Lakefront. |
| `post_wipe_home_healed` | After whiteout, back in living room. Turtwig Lv7 26/26 HP. |
| `sandgem_town_arrival` | Just entered Sandgem Town (map 418). Turtwig Lv7. |
| `got_pokedex_rowan_lab` | Inside Rowan's lab (map 422) after receiving Pokedex. |
| `got_eevee_twinleaf` | In player's house after obtaining Eevee. Turtwig Lv8, Eevee Lv5. |
| `sandgem_pokemon_center_healed` | Outside Sandgem Pokemon Center. Turtwig Lv8 healed. |
| `route_201_heading_east` | Route 201 at (123, 854). Heading east to Sandgem. Turtwig Lv8, Eevee Lv5. |
| `sandgem_north_exit_healed` | Sandgem Town at (184, 833). Healed, heading to Route 202. |
| `post_dawn_battle_route202` | Route 202 at (180, 825). After beating Dawn's Piplup Lv9. Got 30 Poke Balls. Turtwig Lv9. |
| `route202_mid_healed` | Route 202 at (166, 815). Turtwig Lv10, healed. Pre-trainer area. |
| `route202_post_tristan_healed` | Route 202 at (181, 819). After beating Youngster Tristan. Turtwig Lv11 (learned Curse). |
| `route202_grinding_eevee_lv7` | Route 202 grass. Eevee Lv7, Turtwig Lv12, Shinx Lv5 (caught). Post-grind checkpoint. |
| `sandgem_pokecenter_post_wipe_logan` | Sandgem Pokemon Center. Wiped to Youngster Logan. Team healed. Shinx Lv5, Turtwig Lv12, Eevee Lv7. |
| `rowan_lab_before_briefcase` | Rowan's lab at (18,5). Before getting Chimchar + Piplup. |
| `got_starters_rowan_lab` | Rowan's lab. Just received Chimchar + Piplup from briefcase. 5 Pokemon party. |
| `sandgem_5pokemon_turtwig_lead` | Sandgem Town. 5 Pokemon, Turtwig leading. Post-reorder test. |
| `sandgem_pc_5pokemon_chimchar_lv8` | Sandgem Pokemon Center. 5 Pokemon, Chimchar Lv8. |
| `sandgem_pc_grind_session_end` | Sandgem Pokemon Center. Healed. Shinx Lv5, Piplup Lv6, Eevee Lv7, Turtwig Lv12, Chimchar Lv8. |
| `route202_grind_mid_session` | Route 202. Mid-grind. Piplup Lv7, Eevee Lv8, Shinx Lv7, Turtwig Lv12, Chimchar Lv8. |
| `route202_grind_complete` | Route 202. Grind complete. Eevee Lv9 (holding Potion), Shinx Lv8, Piplup Lv8, Turtwig Lv12, Chimchar Lv8. |
| `route202_grind_complete_no_potion` | Same as above but Potion removed from Eevee via take_item. |
| `pre_logan_rematch` | Route 202 at (174, 825). Full team healed, Turtwig leading. Pre-rematch. |
| `post_logan_victory` | Route 202. After beating Youngster Logan. Turtwig Lv13, Piplup Lv9, Chimchar Lv9. |
| `jubilife_city_arrival` | Jubilife City south entrance at (170, 798). Before Dawn/Looker cutscene. |
| `jubilife_pokecenter_healed` | Jubilife Pokemon Center. Team healed. |
| `jubilife_pokecenter_got_bulbasaur` | Jubilife Pokemon Center. After winning Bulbasaur from quiz. 6 Pokemon. |
| `jubilife_post_barry_wipe` | Jubilife Pokemon Center. After losing to Barry on Route 203. Latest gameplay state. |

## Debug & Testing

| Name | Description |
|------|-------------|
| `wild_starly_battle_start` | Wild Starly Lv4 battle on Route 201. Turtwig Lv7. |
| `wild_zigzagoon_route202` | Wild Zigzagoon Lv5 battle on Route 202. At action prompt. |
| `tristan_battle_start` | Youngster Tristan battle. Turtwig Lv10 vs Hoothoot Lv7. 2-Pokemon trainer battle. |
| `tristan_switch_prompt` | Mid-battle "Will you switch?" prompt. After KO'ing Hoothoot, before Starly. |
| `debug_read_party_missing_slot2` | read_party skips Turtwig in slot 2 with 3-Pokemon party. |
| `debug_read_battle_false_sleep` | read_battle shows Sleep(2) on awake wild Shinx. |
| `debug_read_battle_false_positive_trainer` | read_battle returns garbled in_battle:true during pre-battle trainer dialogue. |
| `debug_switch_test_baseline` | Wild Zigzagoon Lv5. 2 Pokemon (Eevee Lv7, Turtwig Lv9). Battle switch testing. |
| `debug_reorder_test_baseline` | Route 202 overworld. 3 Pokemon. Heisenbug repro — read_party stale encrypted data. |
| `debug_garbled_map_post_party_refresh` | Rowan's lab. Map data garbled after read_party(refresh=true) indoors. |
| `debug_wild_faint_use_next` | Wild Zigzagoon battle, at "Use next Pokemon?" prompt after Turtwig fainted. |
| `debug_pre_level_up_ko` | Tristan battle, Hoothoot at 7 HP. Razor Leaf KOs → Turtwig Lv11 → Curse learn prompt. |
| `debug_move_learn_give_up_prompt` | At "Should this Pokemon give up on learning?" prompt. |
| `debug_move_learn_forget_prompt` | At "Make it forget another move?" prompt. |
| `debug_move_select_screen` | Move selection grid: Tackle/Withdraw/Absorb/Razor Leaf + Curse. Move forget UI. |
| `debug_npc_blocking_jubilife` | Jubilife City. Idol NPC blocking Jubilife TV door. |
| `debug_logan_growlithe_low_hp` | Logan battle, Growlithe at 9 HP. One Tackle KOs → SWITCH_PROMPT. |
| `debug_tristan_dialogue_active` | Route 202. Stuck in Tristan's post-battle dialogue. |
| `debug_pre_heal_animation` | Sandgem Pokemon Center. Nurse Joy dialogue right before healing animation. |
| `debug_shinx_pre_levelup_ko` | Wild Sentret Lv5. Shinx Lv5. Tackle KOs → Lv6 → auto-learns Quick Attack. |
| `debug_shinx_pre_levelup_ko_5hp` | Same as above but Sentret at 5 HP. Tighter repro. |
| `pokecenter_pc_booted` | Jubilife Pokemon Center. At PC, "CLAUDE booted up the PC." dialogue active. |
| `pc_deposit_screen` | Inside PC deposit screen. Cursor on Turtwig (slot 0). 5 Pokemon party. |
| `pc_at_storage_menu` | Inside PC at storage menu (DEPOSIT/WITHDRAW/MOVE/SEE YA!). 5 Pokemon party. |
| `pc_deposited_chimchar` | Inside PC. Chimchar deposited to Box 1. |
| `pokecenter_1party_5boxed` | Jubilife Pokemon Center. Turtwig Lv14 only in party. 5 boxed in Box 1. |
