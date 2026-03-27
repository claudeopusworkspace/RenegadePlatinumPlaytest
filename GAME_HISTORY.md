# Pokemon Renegade Platinum - Game History

Chronological playthrough archive. Current game status is in CLAUDE.md.

## Chapter 1: Twinleaf Town to Route 202

### Twinleaf Town (Maps 414-415)
- Character name: CLAUDE. Rival name: AAAAAAA (mashed through naming screen).
- Started in bedroom (map 415). Barry rushed in about Pokemon at the lake.
- Chose Turtwig as starter. Barry chose Chimchar (type advantage over us).
- Other starters NOT received at this point — may come later in the hack.
- Mom gave Running Shoes downstairs (map 414).
- Obtained Eevee from a Poke Ball in player's house after Mom's dialogue. Lv5 with Bite (Dark, 30% flinch) and Covet (Normal).

### Lake Verity (Map 334)
- Visited per story requirement.
- Met Cyrus (ominous speech about time/space).
- Barry wanted to catch the legendary Pokemon but had no Poke Balls.
- First battle: rival fight vs Barry's Chimchar Lv5. Won with Turtwig.

### Route 201 (Map 342)
- Path: North out of Twinleaf (cols 14-17), south corridor exits at ~(111, 864), then east through Route 201 to Sandgem.
- Tall grass unavoidable in the middle section (big patch, columns 10-20).
- Wild encounters: Starly Lv4-5, Pidgey Lv4, Nidoran(M) Lv5, Nidoran(F) Lv4.
- Whiteout incident: Nidoran KO'd Turtwig at 1 HP. Respawned at home, healed.
- Eevee got some EXP from a Pidgey via switch-in training.

### Sandgem Town (Map 418)
- Dawn gave town tour (Pokemon Center at (177, 842), Mart).
- Rowan gave Pokedex in his lab (map 422).
- Rowan gave Poke Radar + Repels outside the lab.
- Healed at Pokemon Center.
- North exit to Route 202 on the east side (cols 180-189).

### Route 202 (Map 343)
- Dawn battled us at the entrance with Piplup Lv9 (not a catching tutorial — this is Renegade Platinum). Gave 30 Poke Balls after winning.
- Youngster Tristan: Hoothoot Lv7 + Starly Lv7. Flying types are a problem for Turtwig — used Tackle (neutral) instead of Razor Leaf (resisted).
- Turtwig learned Curse at Lv11 — perfect fit for Naughty nature (+Atk/-SpD). Setup Curse then sweep.
- Wild Pokemon observed: Zigzagoon Lv5 (Normal, Gluttony).
- More trainers visible further north (around global coords 166-176, rows 804-816).

### Catching Shinx
- Caught Shinx Lv5 on Route 202. Jolly (+Spe/-SpA), Guts ability. Moves: Tackle, Leer, Howl.
- Lost to Youngster Logan (Growlithe/Burmy/Zigzagoon) — overextended with underleveled team.
- Whiteout, respawned at Sandgem Pokemon Center.

## Chapter 2: Rowan's Lab Starters & Grinding

### Rowan's Lab Revisit (Map 422)
- Michael hinted that the other two starters were available in Rowan's lab.
- Found Rowan's briefcase (NPC D at position 18,4) in the upper-right area of the lab.
- Interacting with briefcase triggers Rowan's dialogue: "I would feel safe if I were to entrust the two Pokémon inside that briefcase to you."
- First attempt: mash_a through dialogue accidentally nicknamed Chimchar "AAAAAAAAA". Reloaded.
- Second attempt: carefully advanced through dialogue, selected NO for both nickname prompts.
- **Received Chimchar Lv5** — Careful (+SpD/-SpA), Iron Fist ability. Moves: Scratch, Leer, Ember.
- **Received Piplup Lv5** — Lax (+Def/-SpD), Vital Spirit ability. Moves: Pound, Growl, Bubble.
- Iron Fist on Chimchar is a Renegade Platinum change — boosts punching moves. Vital Spirit on Piplup prevents sleep.

### Route 202 Grinding
- Grinded Chimchar: Lv5 → Lv8 (4 battles). Learned Taunt at Lv8. Ember super effective vs Burmy. Scratch + Iron Fist physical IVs (23 Atk, 29 Spe) making it a solid physical attacker despite Careful nature.
- Grinded Piplup: Lv5 → Lv6 (2 battles). Bubble does ~6 damage to Route 202 Normals. Fainted once to a 5-hit Fury Swipes crit from Sentret.
- Shinx attempted: Fainted to Sentret (crit Fury Swipes + Quick Attack). Only has Tackle for damage at Lv5 — needs more levels.
- Route 202 wild Pokemon: Sentret Lv5 (Normal, Run Away/Keen Eye), Poochyena Lv5 (Dark, Run Away), Zigzagoon Lv5 (Normal, Gluttony, holds Potion), Burmy Lv5 (Bug, Battle Armor).
- Sentret's Fury Swipes is surprisingly dangerous — multi-hit moves with crits can burst down low-level Pokemon.

### Tool Issues Discovered
- **Garbled map data indoors**: Using `read_party(refresh=true)` inside Rowan's lab corrupted all map collision data. Every tile read as `ff` (blocked). Had to navigate out manually with Michael's help.
- **Faint-switch prompt**: When a Pokemon faints, the "Use next Pokémon?" touch button doesn't respond to taps. Required A mashing → B twice to reach full party grid → tap Pokemon → tap SHIFT. Extremely finicky.
- **NPC movement**: Lab assistants moved during navigation, causing missed interactions.

### Pokemon Observations (as of end of Chapter 2)
- **Turtwig** Lv12: Naughty (+Atk/-SpD). IVs: 23/9/5/6/25/9. Moves: Tackle, Curse, Absorb, Razor Leaf. Team anchor, handles most threats.
- **Chimchar** Lv8: Careful (+SpD/-SpA), Iron Fist. IVs: 6/23/24/2/20/29. Moves: Scratch, Leer, Ember, Taunt. Great physical stats despite SpA-reducing nature. Ember still useful for type coverage vs Bugs.
- **Eevee** Lv7: Gentle (+SpD/-Def). IVs: 10/6/19/16/11/25. Moves: Tackle, Tail Whip, Bite, Covet. Needs leveling. Evolution path still TBD.
- **Piplup** Lv6: Lax (+Def/-SpD), Vital Spirit. IVs: 30/14/7/4/23/25. Moves: Pound, Growl, Bubble. Bulky HP IV (30). Sleep immunity is useful. Needs leveling.
- **Shinx** Lv5: Jolly (+Spe/-SpA), Guts. IVs: 13/11/23/21/6/15. Moves: Tackle, Leer, Howl. Most underleveled, needs dedicated grind time. Guts will be great once it has real attacks.
