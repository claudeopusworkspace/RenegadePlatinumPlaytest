# Save States

| Name | Description |
|------|-------------|
| `game_start_bedroom` | After intro, in bedroom, BEFORE Barry's dialogue |
| `post_barry_bedroom` | In bedroom, AFTER Barry leaves. Position (4,7) on map 415. |
| `living_room` | Downstairs in the living room, BEFORE Mom's dialogue. Position (10,3) on map 414. |
| `post_mom_living_room` | Downstairs, AFTER Mom gives Running Shoes. Position (10,3) on map 414. Free to move. |
| `first_battle_start` | Rival battle vs AAAAAAA's Chimchar Lv5. At "What will Turtwig do?" menu. |
| `post_rival_battle_twinleaf` | After rival battle, outside in Twinleaf Town (map 411). Turtwig Lv6. |
| `post_lake_verity_cutscene` | After Lake Verity cutscene (Cyrus + Barry). Map 334, Verity Lakefront. |
| `wild_starly_battle_start` | Wild Starly Lv4 battle on Route 201. For debugging battle_poll. Turtwig Lv7. |
| `post_wipe_home_healed` | After whiteout, back in living room. Turtwig Lv7 26/26 HP. |
| `sandgem_town_arrival` | Just entered Sandgem Town (map 418). Turtwig Lv7. |
| `got_pokedex_rowan_lab` | Inside Rowan's lab (map 422) after receiving Pokedex. Free to move. |
| `sandgem_pokemon_center_healed` | Outside Sandgem Pokemon Center (map 418). Turtwig Lv8 healed. |
| `got_eevee_twinleaf` | In player's house (map 414) after obtaining Eevee. Turtwig Lv8, Eevee Lv5. |
| `route_201_heading_east` | Route 201 (map 342) at (123, 854). Heading east to Sandgem. Turtwig Lv8, Eevee Lv5. |
| `sandgem_north_exit_healed` | Sandgem Town (map 418) at (184, 833). Healed, heading to Route 202. |
| `post_dawn_battle_route202` | Route 202 (map 343) at (180, 825). After beating Dawn's Piplup Lv9. Got 30 Poke Balls. Turtwig Lv9. |
| `route202_mid_healed` | Route 202 (map 343) at (166, 815). Turtwig Lv10, healed. Pre-trainer area. |
| `route202_post_tristan_healed` | Route 202 (map 343) at (181, 819). After beating Youngster Tristan. Turtwig Lv11 (learned Curse), 31/35 HP. |
| `tristan_battle_start` | Youngster Tristan battle start. Turtwig Lv10 vs Hoothoot Lv7. Debug state for 2-Pokemon trainer battle. |
| `tristan_switch_prompt` | Mid-battle "Will you switch?" prompt. After KO'ing Hoothoot, before Starly. Debug state. |
| `wild_zigzagoon_route202` | Wild Zigzagoon Lv5 battle. Route 202, at action prompt. For catch tool testing. |
| `route202_grinding_eevee_lv7` | Route 202 grass. Eevee Lv7, Turtwig Lv12, Shinx Lv5 (caught). Post-grind checkpoint. |
| `debug_read_party_missing_slot2` | Debug: read_party skips Turtwig in slot 2 with 3-Pokemon party. |
| `debug_read_battle_false_sleep` | Debug: read_battle shows Sleep(2) on awake wild Shinx. |
| `debug_read_battle_false_positive_trainer` | Debug: read_battle returns garbled in_battle:true during pre-battle trainer dialogue. |
| `sandgem_pokecenter_post_wipe_logan` | Sandgem Pokemon Center (map 420). Wiped to Youngster Logan. Team healed. Shinx Lv5, Turtwig Lv12, Eevee Lv7. |
| `debug_switch_test_baseline` | Wild Zigzagoon Lv5 battle, Route 202. 2 Pokemon (Eevee Lv7, Turtwig Lv9). For battle switch testing. |
| `debug_reorder_test_baseline` | Route 202 overworld. 3 Pokemon (Eevee, Turtwig, Shinx). **Heisenbug repro state** — read_party has stale encrypted data for Turtwig slot. |
| `rowan_lab_before_briefcase` | Rowan's lab (map 422) at (18,5). Before interacting with briefcase to get Chimchar + Piplup. |
| `got_starters_rowan_lab` | Rowan's lab (map 422). Just received Chimchar + Piplup from briefcase. 5 Pokemon party. |
| `debug_garbled_map_post_party_refresh` | Rowan's lab (map 422). Map data garbled after `read_party(refresh=true)` indoors. All tiles read as `ff`. |
| `sandgem_5pokemon_turtwig_lead` | Sandgem Town (map 418). 5 Pokemon, Turtwig leading. Post-reorder test. |
| `sandgem_pc_grind_session_end` | Sandgem Pokemon Center (map 420). Healed. Shinx Lv5, Piplup Lv6, Eevee Lv7, Turtwig Lv12, Chimchar Lv8. |
| `debug_wild_faint_use_next` | Wild Zigzagoon battle, at "Use next Pokemon?" prompt after Turtwig fainted. For faint-switch testing. |
| `debug_pre_level_up_ko` | Tristan battle, Hoothoot at 7 HP. Next Razor Leaf KOs → Turtwig Lv11 → Curse learn prompt. |
| `debug_move_learn_give_up_prompt` | At "Should this Pokemon give up on learning?" prompt. "Give up on Curse!" / "Don't give up on Curse!" buttons. |
| `debug_move_learn_forget_prompt` | At "Make it forget another move?" prompt. "Forget a move!" / "Keep old moves!" buttons. |
| `debug_move_select_screen` | Move selection grid visible: Tackle/Withdraw/Absorb/Razor Leaf + Curse. For move forget UI testing. |
| `route202_grind_mid_session` | Route 202 (map 343). Mid-grind checkpoint. Piplup Lv7, Eevee Lv8, Shinx Lv7, Turtwig Lv12, Chimchar Lv8. |
| `route202_grind_complete` | Route 202 (map 343). Grind complete. Eevee Lv9 (holding Potion), Shinx Lv8, Piplup Lv8, Turtwig Lv12, Chimchar Lv8. |
| `route202_grind_complete_no_potion` | Route 202 (map 343). Same as above but Potion removed from Eevee via take_item. |
| `pre_logan_rematch` | Route 202 (map 343) at (174, 825). Full team healed, Turtwig leading. Pre-rematch. |
| `post_logan_victory` | Route 202 (map 343). After beating Youngster Logan. Turtwig Lv13, Piplup Lv9, Chimchar Lv9. |
| `jubilife_city_arrival` | Jubilife City (map 3) south entrance at (170, 798). Before Dawn/Looker cutscene. Great dialogue auto-advance test case. |
| `debug_npc_blocking_jubilife` | Jubilife City (map 3) at (165, 752). Idol NPC blocking Jubilife TV door — was invisible before object limit fix. |
| `jubilife_pokecenter_healed` | Jubilife Pokemon Center (map 6). Team healed. Latest state. |
| `debug_logan_growlithe_low_hp` | Logan battle, Growlithe at 9 HP. One Tackle KOs → SWITCH_PROMPT (Burmy next). For switch prompt testing. |
| `debug_tristan_dialogue_active` | Route 202 (map 343) at (181, 819). Stuck in Tristan's post-battle dialogue. For testing tool behavior during active dialogue. |
| `debug_pre_heal_animation` | Sandgem Pokemon Center (map 420). Nurse Joy dialogue at "OK, I'll take your Pokémon for a few seconds." Right before healing animation. |
| `debug_shinx_pre_levelup_ko` | Wild Sentret Lv5 battle, Route 202. Sentret at 10 HP. Shinx Lv5 (3 moves). Tackle KOs → Lv6 → auto-learns Quick Attack. |
| `debug_shinx_pre_levelup_ko_5hp` | Same as above but Sentret at 5 HP. Tighter repro for auto-learn bug testing. |
| `pokecenter_pc_booted` | Jubilife Pokemon Center (map 6). At PC, "CLAUDE booted up the PC." dialogue active. For PC tool testing. |
| `pc_deposit_screen` | Inside PC deposit screen. Cursor on Turtwig (slot 0). 5 Pokemon party. |
| `pc_at_storage_menu` | Inside PC at storage system menu (DEPOSIT/WITHDRAW/MOVE/SEE YA!). 5 Pokemon party. |
| `pokecenter_1party_5boxed` | Jubilife Pokemon Center (map 6). Turtwig Lv14 only in party. Shinx, Piplup, Eevee, Chimchar, Bulbasaur in Box 1. For withdraw tool testing. |
