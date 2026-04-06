# Save States (melonDS)

## Gameplay Progression

| Name | Description |
|------|-------------|
| `eterna_city_pokecenter_melonds` | Eterna City Pokemon Center. 5 Pokemon party. 1 Badge (Coal). Post-Eterna Forest. |
| `eterna_city_pre_gardenia` | Eterna City Pokemon Center. Healed. Explored city, got HM01 Cut + Sun Stone + TM46 Thief + TM69 Rock Polish. Grotle knows Cut. Need to reach Route 216 via Mt. Coronet to find Gardenia. |

## Debug & Testing

| Name | Description |
|------|-------------|
| `debug_pokeball_cutscene_interrupt` | Eterna City at (326, 516). `interact_with(object_index=21)` on Pokeball triggers Cynthia cutscene with delayed dialogue. |
| `debug_signpost_blocking_navigate` | Route 211 at (352, 531). Arrow Signpost at (353, 531) blocks BFS pathfinding east. |
| `debug_route211_bridge_pathfind` | Route 211 at (377, 532). 3D BFS walks off bridge to reach Pokeball at (368, 535). |

---

*DeSmuME-era save states (.dst) are documented in [LEGACY_SAVE_STATES.md](LEGACY_SAVE_STATES.md). These are not compatible with melonDS but preserved for reference.*
