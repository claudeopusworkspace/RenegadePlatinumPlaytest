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

## Debug & Testing

| Name | Description |
|------|-------------|
| `debug_pokeball_cutscene_interrupt` | Eterna City at (326, 516). `interact_with(object_index=21)` on Pokeball triggers Cynthia cutscene with delayed dialogue. |
| `debug_signpost_blocking_navigate` | Route 211 at (352, 531). Arrow Signpost at (353, 531) blocks BFS pathfinding east. |
| `debug_route211_bridge_pathfind` | Route 211 at (377, 532). 3D BFS walks off bridge to reach Pokeball at (368, 535). |
| `debug_route216_blocked_down` | Route 216 at (374, 402). Deep snow movement timing bug — nav code reports impassable but `advance_frames` with held direction moves fine. |
| `route216_snow_nav_bug_v2` | Route 216 at (298, 404). Navigate blocks after 2 tiles going north in snow — works on immediate retry. melonDS era. |

---

*DeSmuME-era save states (.dst) are documented in [LEGACY_SAVE_STATES.md](LEGACY_SAVE_STATES.md). These are not compatible with melonDS but preserved for reference.*
