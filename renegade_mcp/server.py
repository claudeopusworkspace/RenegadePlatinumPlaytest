"""Renegade Platinum MCP server — game-specific tools for Pokemon Renegade Platinum.

Tools connect to the running melonDS emulator via the bridge socket.
The server starts without requiring the emulator — connection is lazy.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from renegade_mcp.connection import get_client
from renegade_mcp.tool import renegade_tool


def create_server() -> FastMCP:
    """Create and configure the Renegade Platinum MCP server."""
    mcp = FastMCP("renegade")

    # ── Party ──

    @mcp.tool()
    def read_party() -> dict[str, Any]:
        """Read party Pokemon from memory.

        Returns species, level, HP, moves with PP, nature, IVs, EVs for each party member.
        Works in overworld and battle — checks encryption-state flags on each slot,
        so reads are reliable whether the game has data encrypted or in a decryption context.
        """
        from renegade_mcp.party import format_party, read_party as _read_party

        emu = get_client()
        party = _read_party(emu)
        return {
            "count": len(party),
            "party": party,
            "formatted": format_party(party),
        }

    # ── Battle ──

    @mcp.tool()
    def read_battle() -> dict[str, Any]:
        """Read live battle state from memory.

        Returns all active battlers with species, stats, moves, PP, HP, ability,
        types, status conditions, held items, and stat stage changes.
        Slot 0 = player active, Slot 1 = enemy active, Slots 2-3 = doubles partners.
        Returns empty if not in battle.
        """
        from renegade_mcp.battle import format_battle, read_battle as _read_battle

        emu = get_client()
        battlers = _read_battle(emu)
        return {
            "in_battle": len(battlers) > 0,
            "battlers": battlers,
            "formatted": format_battle(battlers),
        }

    # ── Bag ──

    @mcp.tool()
    def read_bag(pocket: str = "") -> dict[str, Any]:
        """Read bag/inventory contents from memory.

        Returns all 7 pockets (Items, Key Items, TMs & HMs, Mail, Medicine, Berries,
        Battle Items) with item names and quantities.

        Args:
            pocket: Optional pocket name to filter (e.g. "Key Items"). Empty = all pockets.
        """
        from renegade_mcp.bag import format_bag, read_bag as _read_bag

        emu = get_client()
        bag = _read_bag(emu)
        filtered = bag
        if pocket:
            filtered = [p for p in bag if p["name"].lower() == pocket.lower()]
        return {
            "pockets": filtered,
            "formatted": format_bag(bag, pocket),
        }

    # ── Map ──

    @mcp.tool()
    def view_map(level: int = -1) -> dict[str, Any]:
        """Show ASCII map of current area with terrain, player position, and NPCs.

        Handles indoor maps (from RAM) and overworld multi-chunk maps (from ROM).
        Player shown as ^v<> (facing), NPCs as A-Z. Includes terrain behaviors.

        On 3D maps, shows elevation levels (0-9), ramps (/ \\), bridges (n*),
        and directional blocks (] [). Pass level=N to isolate a single level.

        Args:
            level: Show only this elevation level (-1 = show all levels).
        """
        from renegade_mcp.map_state import view_map as _view_map

        emu = get_client()
        return _view_map(emu, level=level)

    @mcp.tool()
    def map_name(map_id: int = -1) -> dict[str, Any]:
        """Look up the location name for a map ID.

        Args:
            map_id: Map ID to look up. If -1, reads current map from the emulator.
        """
        from renegade_mcp.map_names import lookup_map_name
        from renegade_mcp.map_state import read_player_state

        if map_id < 0:
            emu = get_client()
            mid, x, y, facing = read_player_state(emu)
            result = lookup_map_name(mid)
            result["x"] = x
            result["y"] = y
            return result
        return lookup_map_name(map_id)

    # ── Navigation ──

    @mcp.tool()
    @renegade_tool
    def navigate(directions: str, flee_encounters: bool = False) -> dict[str, Any]:
        """Walk a manual path in the overworld using explicit directions.

        USE THIS ONLY when you need precise directional control — e.g., walking
        through a narrow corridor in a specific sequence, activating a warp by
        stepping in a particular direction, or nudging one tile. For getting from
        point A to point B, use navigate_to(x, y) instead — it pathfinds
        automatically and avoids walls.

        Pre-validates the entire path against terrain before moving. If any step
        would hit an impassable tile, returns an error without moving at all.

        Args:
            directions: Space-separated directions: up/down/left/right (or u/d/l/r)
                       with optional repeat counts (e.g. "l20 u5 r3").
            flee_encounters: If True, auto-flee wild battles encountered during the walk.
                Trainer battles still halt for the caller.
        """
        from renegade_mcp.navigation import navigate_manual

        emu = get_client()
        return navigate_manual(emu, directions, flee_encounters=flee_encounters)

    @mcp.tool()
    @renegade_tool
    def navigate_to(x: int, y: int, path_choice: str | None = None, flee_encounters: bool = False) -> dict[str, Any]:
        """Pathfind to a target tile using BFS, then walk there automatically.

        THIS IS THE DEFAULT NAVIGATION TOOL. Use this whenever you need to move
        to a specific tile — it reads the terrain, avoids walls and NPCs, and
        finds the shortest path. Use view_map to find target coordinates.

        Obstacle-aware: when HM obstacles (Rock Smash rocks, Cut trees) or
        water tiles block or shorten the path, returns status "obstacle_choice"
        or "obstacle_required" with path info instead of moving. Call again
        with path_choice to proceed. Strength boulders are never auto-cleared.

        Only fall back to navigate(directions) when you need precise directional
        control (e.g., activating warps, single-tile nudges, or specific sequences).

        Supports local (0-31) and global coordinates (auto-detected).
        Handles multi-chunk overworld maps and door/stair transitions.

        Args:
            x: Target X coordinate (local or global). Use view_map to find these.
            y: Target Y coordinate (local or global).
            path_choice: None (default — ask if obstacles involved),
                         "obstacle" (take the path through obstacles, auto-clearing them),
                         "clean" (take the obstacle-free path).
            flee_encounters: If True, auto-flee wild battles and resume navigation.
                Trainer battles (detected by pre-battle dialogue) still halt for the caller.
        """
        from renegade_mcp.navigation import navigate_to as _navigate_to

        emu = get_client()
        return _navigate_to(emu, x, y, path_choice=path_choice, flee_encounters=flee_encounters)

    @mcp.tool()
    @renegade_tool
    def interact_with(object_index: int = -1, x: int = -1, y: int = -1, flee_encounters: bool = False) -> dict[str, Any]:
        """Navigate to a map object/NPC or static tile and interact with it.

        Two modes:
        - **Object mode**: Pass object_index (from view_map) to target a dynamic object/NPC.
        - **Coordinate mode**: Pass x and y to target a static tile (PCs, bookshelves, etc.).

        Pathfinds to the nearest adjacent tile, faces the target, presses A,
        and returns any dialogue produced.

        Args:
            object_index: The object's index from the view_map objects list. Default -1 (unused).
            x: Target tile X coordinate (global). Use with y for static tiles.
            y: Target tile Y coordinate (global). Use with x for static tiles.
            flee_encounters: If True, auto-flee wild battles encountered while walking to the target.
                Trainer battles still halt for the caller.
        """
        from renegade_mcp.navigation import interact_with as _interact_with

        emu = get_client()
        return _interact_with(emu, object_index=object_index, x=x, y=y, flee_encounters=flee_encounters)

    @mcp.tool()
    @renegade_tool
    def seek_encounter(cave: bool = False) -> dict[str, Any]:
        """Walk back and forth in grass until a wild encounter triggers.

        Finds the nearest pair of adjacent grass tiles, navigates there if
        needed, then paces between them until an encounter or 200 steps.
        When a battle triggers, advances through the transition to the first
        action prompt and returns full battle state — ready for battle_turn.

        Args:
            cave: If True, pace between any walkable tiles instead of grass.
                  Use in caves or other areas with encounters on normal ground.
        """
        from renegade_mcp.navigation import seek_encounter as _seek_encounter

        emu = get_client()
        return _seek_encounter(emu, cave=cave)

    # ── Dialogue ──

    @mcp.tool()
    @renegade_tool
    def read_dialogue(region: str = "auto", advance: bool = True) -> dict[str, Any]:
        """Read dialogue text, optionally auto-advancing through the full conversation.

        With advance=True (default): Automatically presses B to advance through
        all dialogue pages, collecting the full conversation. Stops at dialogue
        end, Yes/No prompts, or unknown states requiring input. Uses the script
        engine state machine (ScriptManager/ScriptContext/TextPrinter) for
        reliable detection of when to press, when to wait, and when to stop.

        With advance=False: Passive read — returns whatever text is currently
        in the RAM buffer without pressing any buttons.

        Args:
            region: "auto" (try overworld then battle), "overworld", or "battle".
                Only used when advance=False.
            advance: If True, auto-advance through dialogue collecting all text.
                If False, passive read only (original behavior).
        """
        from renegade_mcp.dialogue import (
            advance_dialogue as _advance_dialogue,
            read_dialogue as _read_dialogue,
        )

        emu = get_client()
        if advance:
            return _advance_dialogue(emu)
        return _read_dialogue(emu, region)

    # ── Battle Turn ──

    def _find_acting_player(emu, battlers: list[dict]) -> dict | None:
        """Identify which player Pokemon is currently acting in battle.

        Scans memory for the "What will X do?" prompt and matches X against
        player battler nicknames.  In doubles, this distinguishes the primary
        battler (slot 0) from the partner (slot 2).  Falls back to slot 0.
        """
        from renegade_mcp.battle_tracker import SCAN_SIZE, _scan_for_new_text
        from renegade_mcp.addresses import addr
        scan_start = addr("BATTLE_SCAN_START")

        data = emu.read_memory_block(scan_start, SCAN_SIZE)
        if data:
            results = _scan_for_new_text(data, scan_start, {})
            for _, text, _, _ in results:
                clean = text.replace("\n", " ")
                if "What will" in clean and "do?" in clean:
                    # Extract the Pokemon name between "What will " and " do?"
                    start = clean.index("What will") + len("What will ")
                    end = clean.index(" do?", start)
                    name = clean[start:end].strip()
                    for b in battlers:
                        if b.get("side") == "player" and b.get("nickname", "") == name:
                            return b
                    break

        # Fallback: slot 0
        return next((b for b in battlers if b["slot"] == 0), None)

    def _check_move_effectiveness(emu, move_index: int, target: int) -> dict[str, Any] | None:
        """Pre-check move type vs target types. Returns warning dict or None if OK."""
        from renegade_mcp.battle import read_battle as _read_battle
        from renegade_mcp.data import move_data as _move_data, move_type as _move_type
        from renegade_mcp.type_chart import describe, effectiveness

        battlers = _read_battle(emu)
        if not battlers:
            return None  # Not in battle — let battle_turn handle it

        # Determine which player Pokemon is currently acting by reading the
        # "What will X do?" prompt text and matching X against battler names.
        # Falls back to slot 0 if the prompt can't be parsed.
        player = _find_acting_player(emu, battlers)
        if player is None or move_index >= len(player["moves"]):
            return None

        move = player["moves"][move_index]
        move_id = move["id"]

        # Look up move type and class from ROM data
        mv_type = _move_type(move_id)
        if mv_type is None:
            return None  # No data — skip check

        # Skip check for Status moves — they don't use the type chart for damage
        # (e.g., Curse is Ghost-type but boosts stats for non-Ghost users)
        mv_entry = _move_data().get(move_id, {})
        if mv_entry.get("class") == "Status":
            return None

        # Find the target enemy (prefer alive enemies, redirect fainted targets)
        enemies = [b for b in battlers if b["side"] == "enemy"]
        if not enemies:
            return None
        alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
        if not alive_enemies:
            return None  # All enemies fainted — skip check
        if target >= 0 and target < len(enemies) and enemies[target].get("hp", 0) > 0:
            defender = enemies[target]
        else:
            defender = alive_enemies[0]

        def_type1 = defender["type1"]
        def_type2 = defender["type2"] if defender["type2"] != defender["type1"] else None

        mult = effectiveness(mv_type, def_type1, def_type2)
        if mult > 0.5:
            return None  # Neutral or super effective — no warning

        # Build warning
        label = describe(mult)
        def_str = f"{def_type1}/{def_type2}" if def_type2 else def_type1
        mv_class = mv_entry.get("class", "")

        warning_msg = (
            f"⚠ {move['name']} ({mv_type}, {mv_class}) → {defender['species']} ({def_str}): {label}\n"
            f"Call battle_turn(move_index={move_index}, force=True) to use it anyway."
        )
        return {
            "final_state": "EFFECTIVENESS_WARNING",
            "warning": warning_msg,
            "move": move["name"],
            "move_type": mv_type,
            "defender": defender["species"],
            "defender_types": def_str,
            "multiplier": mult,
            "effectiveness": label,
            "formatted": warning_msg,
        }

    @mcp.tool()
    @renegade_tool
    def battle_turn(move_index: int = -1, switch_to: int = -1, forget_move: int = -2, target: int = -1, run: bool = False, force: bool = False) -> dict[str, Any]:
        """Execute a full battle turn: use a move, switch Pokemon, or run.

        Combines battle_init + action + battle_poll into one call.
        Specify exactly one action: move_index to fight, switch_to to swap, or run to flee.

        **Type effectiveness check**: When using a move, the tool checks the move's
        type against the target's types. If the move would be IMMUNE (0x) or NOT VERY
        EFFECTIVE (0.5x or less), it returns a warning instead of executing. Pass
        force=True to proceed anyway (e.g., for status moves, chip damage, or STAB).

        Actions:
        - move_index (0-3): Tap FIGHT, select the move (top-left, top-right, bottom-left, bottom-right).
        - switch_to (1-5): Tap POKEMON, navigate to party slot, confirm switch. Slot 0 is the active battler.
        - run (True): Attempt to flee a wild battle. Returns BATTLE_ENDED on success,
          WAIT_FOR_ACTION on failure (enemy gets a free turn). Rejects trainer battles.
        - forget_move (0-3): At MOVE_LEARN prompt, forget this move slot and learn the new move.
        - forget_move=-1: At MOVE_LEARN prompt, skip learning the new move.
        - target (doubles only): Target for the move. 0=left enemy, 1=right enemy, 2=self/ally.
          -1 (default) auto-targets the first enemy. Only used when move_index is set.
        - force (bool): Skip the type effectiveness warning and execute anyway.

        States returned:
        - WAIT_FOR_ACTION: next turn ready, select another move
        - WAIT_FOR_PARTNER_ACTION: double battle — first Pokemon acted, select action for second
        - SWITCH_PROMPT: trainer sending next Pokemon, switch or keep battling
        - MOVE_LEARN: move learning prompt — includes move_to_learn and current_moves
        - EFFECTIVENESS_WARNING: move is immune or not very effective — call again with force=True to proceed
        - BATTLE_ENDED: battle over, back in overworld
        - TIMEOUT: poll limit reached, check game state manually
        - NO_TEXT: action may not have registered
        """
        from renegade_mcp.turn import battle_turn as _battle_turn

        emu = get_client()

        # Type effectiveness guardrail — check before committing to the action
        if move_index >= 0 and not force:
            warning = _check_move_effectiveness(emu, move_index, target)
            if warning is not None:
                return warning

        return _battle_turn(emu, move_index=move_index, switch_to=switch_to, forget_move=forget_move, target=target, run=run)

    # ── Catch ──

    @mcp.tool()
    @renegade_tool
    def throw_ball() -> dict[str, Any]:
        """Throw a Poké Ball at the wild Pokemon.

        Must be at the action prompt in a wild battle. Navigates BAG → Poké Balls,
        selects the first ball, and throws it. Polls for catch result and handles
        post-catch screens (Pokédex registration, nickname prompt).

        States returned:
        - CAUGHT: Pokemon caught, back in overworld
        - NOT_CAUGHT: ball failed, back at action prompt — try again or fight
        - BATTLE_ENDED: battle over (shouldn't happen normally)
        - TIMEOUT: something unexpected — check game state
        """
        from renegade_mcp.catch import throw_ball as _throw_ball

        emu = get_client()
        return _throw_ball(emu)

    # ── Battle Item Use ──

    @mcp.tool()
    @renegade_tool
    def use_battle_item(item_name: str, party_slot: int = -1, target: int = -1) -> dict[str, Any]:
        """Use an item from the bag during battle.

        Must be at the action prompt. Navigates BAG → pocket → item → USE → target.
        Consumes the trainer's turn (item use replaces a move).

        Item categories (auto-detected from ROM data):
        - Healing items (Potion, Antidote, Revive, etc.): party_slot required (0-5).
        - Stat boosters (X Attack, X Speed, Guard Spec, Dire Hit): auto-applies in singles.
          In doubles, pass target (0=first active, 1=second active).
        - Escape items (Poke Doll, Fluffy Tail): auto-flees, no target needed.
        - Poke Balls: rejected — use throw_ball instead.

        Returns success status, quantity change, and final_state (WAIT_FOR_ACTION or BATTLE_ENDED).
        """
        from renegade_mcp.use_battle_item import use_battle_item as _use_battle_item

        emu = get_client()
        return _use_battle_item(emu, item_name, party_slot, target)

    # ── ROM Message Decoding ──

    @mcp.tool()
    def decode_rom_message(file_index: int) -> dict[str, Any]:
        """Decode all strings in a ROM message file by index.

        Key file indices:
        - 392: Item names (index = item ID)
        - 412: Pokemon species names (index = national dex #)
        - 610: Ability names (index = ability ID)
        - 647: Move names (index = move ID)
        - 433: Location/map names
        - 646: Move descriptions

        Args:
            file_index: Message file index (0-723).
        """
        from renegade_mcp.rom_messages import decode_file

        results = decode_file(file_index)
        if not results:
            return {"file_index": file_index, "count": 0, "strings": [], "error": "File not found or empty."}

        return {
            "file_index": file_index,
            "count": len(results),
            "strings": results,
        }

    @mcp.tool()
    def search_rom_messages(query: str) -> dict[str, Any]:
        """Search all ROM message files for strings containing the query text.

        Searches all 724 message files (species names, moves, items, dialogue, etc.).
        Case-insensitive.

        Args:
            query: Text to search for.
        """
        from renegade_mcp.rom_messages import search_all

        matches = search_all(query)
        return {
            "query": query,
            "match_count": len(matches),
            "matches": matches,
        }

    # ── Type Matchup ──

    @mcp.tool()
    def type_matchup(
        attacking_type: str = "",
        defending_types: str = "",
        move_name: str = "",
    ) -> dict[str, Any]:
        """Check type effectiveness — works like Pokemon Showdown's damage calc.

        Two modes:
        1. Type vs types: type_matchup(attacking_type="Fire", defending_types="Grass/Steel")
        2. Move vs types: type_matchup(move_name="Spark", defending_types="Water/Flying")
           Looks up the move's type from ROM data automatically.

        defending_types is slash-separated (e.g. "Water", "Fire/Flying", "Normal/Fairy").
        Uses Gen 4 type chart + Fairy type (Renegade Platinum).

        Args:
            attacking_type: The attacking type name (e.g. "Fire"). Ignored if move_name is set.
            defending_types: Slash-separated defending types (e.g. "Water/Flying").
            move_name: Move name to look up type for (e.g. "Spark", "Earthquake").
        """
        from renegade_mcp.data import move_data, move_names
        from renegade_mcp.type_chart import (
            VALID_TYPES,
            _normalize_type,
            describe,
            effectiveness,
            format_matchup,
        )

        # Resolve attacking type
        atk_type = None
        move_info = None
        if move_name:
            mv_names = move_names()
            name_lower = move_name.strip().lower()
            mv_id = None
            for mid, mname in mv_names.items():
                if mname.lower() == name_lower:
                    mv_id = mid
                    break
            if mv_id is None:
                return {"error": f"Unknown move: '{move_name}'"}
            mv_data = move_data()
            entry = mv_data.get(mv_id)
            if entry is None:
                return {"error": f"No data for move '{move_name}' (run scripts/extract_move_data.py)"}
            atk_type = entry["type"]
            move_info = entry
        elif attacking_type:
            atk_type = _normalize_type(attacking_type)
            if atk_type is None:
                return {"error": f"Unknown type: '{attacking_type}'. Valid: {', '.join(sorted(VALID_TYPES))}"}
        else:
            return {"error": "Provide attacking_type or move_name."}

        # Parse defending types
        if not defending_types:
            return {"error": "Provide defending_types (e.g. 'Water', 'Fire/Flying')."}
        parts = [p.strip() for p in defending_types.split("/")]
        def_type1 = _normalize_type(parts[0])
        def_type2 = _normalize_type(parts[1]) if len(parts) > 1 else None
        if def_type1 is None:
            return {"error": f"Unknown defending type: '{parts[0]}'"}
        if len(parts) > 1 and def_type2 is None:
            return {"error": f"Unknown defending type: '{parts[1]}'"}

        mult = effectiveness(atk_type, def_type1, def_type2)
        label = describe(mult)
        matchup_str = format_matchup(atk_type, def_type1, def_type2)

        result: dict[str, Any] = {
            "attacking_type": atk_type,
            "defending_types": f"{def_type1}/{def_type2}" if def_type2 else def_type1,
            "multiplier": mult,
            "label": label,
            "formatted": matchup_str,
        }
        if move_info:
            result["move"] = move_info
        return result

    # ── Move Info ──

    @mcp.tool()
    def move_info(move_name: str) -> dict[str, Any]:
        """Look up a move's full stats: type, power, accuracy, PP, class, priority.

        Pure ROM data lookup — no emulator interaction needed.
        This is the same information visible on the move summary screen in-game.

        Args:
            move_name: The move name (e.g. "Earthquake", "Bullet Seed", "Swords Dance").
        """
        from renegade_mcp.data import move_data, move_names

        mv_names = move_names()
        name_lower = move_name.strip().lower()
        mv_id = None
        for mid, mname in mv_names.items():
            if mname.lower() == name_lower:
                mv_id = mid
                break
        if mv_id is None:
            return {"error": f"Unknown move: '{move_name}'"}

        mv_data = move_data()
        entry = mv_data.get(mv_id)
        if entry is None:
            return {"error": f"No data for move '{move_name}' (run scripts/extract_move_data.py)"}

        # Build formatted summary
        parts = [entry["type"], entry["class"]]
        if entry.get("power"):
            parts.append(f"{entry['power']} pwr")
        if entry.get("accuracy"):
            parts.append(f"{entry['accuracy']}% acc")
        parts.append(f"{entry['pp']} PP")
        if entry.get("priority", 0) != 0:
            parts.append(f"priority {entry['priority']:+d}")

        return {
            "move_id": mv_id,
            "name": entry["name"],
            "type": entry["type"],
            "class": entry["class"],
            "power": entry.get("power"),
            "accuracy": entry.get("accuracy"),
            "pp": entry["pp"],
            "priority": entry.get("priority", 0),
            "formatted": f"{entry['name']} [{' · '.join(parts)}]",
        }

    # ── Trainer Status ──

    @mcp.tool()
    def read_trainer_status() -> dict[str, Any]:
        """Read trainer money and badge count from memory.

        Pure memory read — works anytime, no UI interaction.
        Returns current money and badge count (badges TBD until first gym).
        """
        from renegade_mcp.trainer import read_trainer_status as _read_status

        emu = get_client()
        return _read_status(emu)

    # ── Shop ──

    @mcp.tool()
    def read_shop() -> dict[str, Any]:
        """Read the PokéMart inventory for the player's current city.

        Detects which city/town the player is in, looks up the standard
        PokéMart stock (common items filtered by badge count + city-specific
        specialty items), and returns all items with names and prices.

        Prices are read from ROM data (pl_item_data.narc). Common mart items
        are badge-gated using the same thresholds as the game.

        Pure data lookup — no UI interaction, no checkpoint needed.
        """
        from renegade_mcp.shop import read_shop as _read_shop
        from renegade_mcp.trainer import read_trainer_status as _read_status

        emu = get_client()

        # Read badge count (may be unconfirmed)
        status = _read_status(emu)
        badge_count = status.get("badges") if isinstance(status.get("badges"), int) else None

        return _read_shop(emu, badge_count=badge_count)

    @mcp.tool()
    @renegade_tool
    def buy_item(item_name: str, quantity: int = 1) -> dict[str, Any]:
        """Buy an item from a standard PokéMart.

        Works from inside a PokéMart or from a city/town overworld (auto-navigates
        to the mart). Finds the correct cashier (Cashier F for common items,
        Cashier M for specialty), navigates to them, opens the shop, scrolls to
        the item, purchases the specified quantity, and exits.

        Item position is calculated from ROM data — common items appear first
        (badge-filtered, in PokeMartCommonItems[] order), then specialty items.

        Args:
            item_name: Item to buy (e.g. "Potion", "Heal Ball"). Case-insensitive.
            quantity: How many to buy (default 1).
        """
        from renegade_mcp.shop import buy_item as _buy_item
        from renegade_mcp.trainer import read_trainer_status as _read_status

        emu = get_client()

        status = _read_status(emu)
        badge_count = status.get("badges") if isinstance(status.get("badges"), int) else None

        return _buy_item(emu, item_name, quantity=quantity, badge_count=badge_count)

    @mcp.tool()
    @renegade_tool
    def sell_item(item_name: str, quantity: int = 1) -> dict[str, Any]:
        """Sell an item at a standard PokéMart.

        Works from inside a PokéMart or from a city/town overworld (auto-navigates
        to the mart). Talks to Cashier F, selects SELL, navigates the sell bag to
        the target item, sells the specified quantity, and exits.

        Sell price = buy price / 2 (standard Pokémon formula).

        Cannot sell Key Items, TMs/HMs, or Mail.

        Args:
            item_name: Item to sell (e.g. "Potion", "Repel"). Case-insensitive.
            quantity: How many to sell (default 1).
        """
        from renegade_mcp.shop import sell_item as _sell_item

        emu = get_client()
        return _sell_item(emu, item_name, quantity=quantity)

    # ── Item Use ──

    @mcp.tool()
    @renegade_tool
    def use_item(item_name: str, party_slot: int = 0) -> dict[str, Any]:
        """Use a Medicine pocket item on a party Pokemon in the overworld.

        Opens the pause menu, navigates to Bag → Medicine pocket, selects the
        item, uses it on the target party member, and closes all menus.

        Args:
            item_name: Item name (e.g. "Potion", "Antidote"). Case-insensitive.
            party_slot: Party index 0-5 (0 = first Pokemon).
        """
        from renegade_mcp.use_item import use_item as _use_item

        emu = get_client()
        return _use_item(emu, item_name, party_slot)

    @mcp.tool()
    @renegade_tool
    def use_field_item(item_name: str) -> dict[str, Any]:
        """Use a field item (Repel, Escape Rope, Honey, etc.) from the Items pocket.

        For items that activate directly without targeting a party Pokemon.
        Opens pause menu → Bag → Items pocket → select item → USE → dismiss.
        Pre-validates that the item is field-usable (rejects hold-only items
        like Silk Scarf). For Medicine items, use use_item() instead.

        Args:
            item_name: Item name (e.g. "Repel", "Escape Rope"). Case-insensitive.
        """
        from renegade_mcp.use_item import use_field_item as _use_field_item

        emu = get_client()
        return _use_field_item(emu, item_name)

    @mcp.tool()
    @renegade_tool
    def use_key_item(item_name: str) -> dict[str, Any]:
        """Use a key item from the Key Items pocket.

        Currently supports: Bicycle (mount/dismount toggle).
        Opens pause menu → Bag → Key Items pocket → select item → USE.
        Menu closes automatically after use.

        Args:
            item_name: Item name (e.g. "Bicycle"). Case-insensitive.
        """
        from renegade_mcp.use_item import use_key_item as _use_key_item

        emu = get_client()
        return _use_key_item(emu, item_name)

    @mcp.tool()
    @renegade_tool
    def use_medicine(
        confirm: bool = False,
        exclude_items: list[str] | None = None,
        priority: list[int] | None = None,
    ) -> dict[str, Any]:
        """Plan and execute bulk party healing using Medicine pocket items.

        Reads party HP/status + bag, computes an optimal healing plan.
        First call (confirm=False): returns the plan without using any items.
        Second call (confirm=True): executes the plan via repeated item uses.

        Strategy: heals status conditions with the most specific cure available
        (e.g. Antidote before Full Heal), heals HP using lowest-tier potions
        first but avoids wasting multiple items when one higher-tier item
        suffices. Uses Full Restore when a Pokemon needs both status cure and
        HP healing. Revives fainted Pokemon before healing.

        Args:
            confirm: If True, execute the plan. If False (default), just return it.
            exclude_items: Item names to exclude from the plan (e.g. ["Max Revive"]).
            priority: Party slot indices in healing priority order (e.g. [2, 0, 1]).
                      Defaults to natural party order.
        """
        from renegade_mcp.use_medicine import use_medicine as _use_medicine

        emu = get_client()
        return _use_medicine(emu, confirm, exclude_items, priority)

    @mcp.tool()
    @renegade_tool
    def teach_tm(
        tm_name: str, party_slot: int = 0, forget_move: int | None = None
    ) -> dict[str, Any]:
        """Teach a TM or HM move to a party Pokemon from the overworld.

        Opens pause menu → Bag → TMs & HMs → select TM → USE → dialogue →
        party select → move-forget flow → close menus. Pre-validates that
        the Pokemon can learn the move using ROM compatibility data.

        Args:
            tm_name: TM/HM label (e.g. "HM06", "TM76") or move name
                     (e.g. "Rock Smash", "Stealth Rock"). Case-insensitive.
            party_slot: Party index 0-5 (0 = first Pokemon).
            forget_move: Move slot 0-3 to forget (required when Pokemon
                         knows 4 moves). Pass -1 to cancel without teaching.
        """
        from renegade_mcp.teach_tm import teach_tm as _teach_tm

        emu = get_client()
        return _teach_tm(emu, tm_name, party_slot, forget_move)

    @mcp.tool()
    @renegade_tool
    def use_fly(destination: str) -> dict[str, Any]:
        """Fly to a destination city or town from the overworld.

        Uses HM02 Fly: opens Pokemon menu, selects a Fly user, navigates
        the town map cursor to the destination, and warps there.

        Requires: Cobble Badge (3rd), a party Pokemon that knows Fly,
        and a location that allows Fly (outdoors, no partner).

        Args:
            destination: City/town name (e.g. "Jubilife City", "Eterna City")
                         or code (e.g. "C01", "T03"). Case-insensitive,
                         partial match supported (e.g. "jubilife").
        """
        from renegade_mcp.fly import use_fly as _use_fly

        emu = get_client()
        return _use_fly(emu, destination)

    @mcp.tool()
    def tm_compatibility(tm_name: str) -> dict[str, Any]:
        """Check which party Pokemon can learn a given TM/HM.

        Pure data lookup from ROM — no emulator interaction needed.

        Args:
            tm_name: TM/HM label (e.g. "HM06", "TM76") or move name
                     (e.g. "Rock Smash"). Case-insensitive.
        """
        from renegade_mcp.bag import read_bag
        from renegade_mcp.data import (
            can_learn_tm,
            item_id_to_tm_index,
            tm_move_name,
        )
        from renegade_mcp.party import read_party

        emu = get_client()
        tm_lower = tm_name.strip().lower()

        # Find the TM in the bag
        bag = read_bag(emu)
        tm_pocket = next(
            (p for p in bag if p["name"] == "TMs & HMs"), None
        )
        if tm_pocket is None:
            return {"success": False, "error": "TMs & HMs pocket not found."}

        tm_idx = None
        tm_label = None
        for item in tm_pocket["items"]:
            idx = item_id_to_tm_index(item["id"])
            if idx is None:
                continue
            bag_name = item["name"].lower()
            move = tm_move_name(idx)
            if bag_name == tm_lower or move.lower() == tm_lower:
                tm_idx = idx
                tm_label = item["name"]
                break

        if tm_idx is None:
            return {"success": False, "error": f"'{tm_name}' not found in bag."}

        move = tm_move_name(tm_idx)
        party = read_party(emu)
        results = []
        for i, mon in enumerate(party):
            sid = mon.get("species_id", 0)
            name = mon.get("name", f"Slot {i}")
            able = can_learn_tm(sid, tm_idx)
            already = any(
                mn.lower() == move.lower()
                for mn in mon.get("move_names", [])
            )
            results.append({
                "slot": i,
                "name": name,
                "able": able,
                "already_knows": already,
            })

        formatted_lines = [f"{tm_label} teaches {move}:"]
        for r in results:
            status = "ABLE" if r["able"] else "UNABLE"
            if r["already_knows"]:
                status = "ALREADY KNOWS"
            formatted_lines.append(f"  Slot {r['slot']}: {r['name']} — {status}")

        return {
            "success": True,
            "tm": tm_label,
            "move": move,
            "party": results,
            "formatted": "\n".join(formatted_lines),
        }

    @mcp.tool()
    @renegade_tool
    def take_item(party_slot: int = 0) -> dict[str, Any]:
        """Take the held item from a party Pokemon in the overworld.

        Opens pause menu → Pokemon → select slot → Item → Take. Verifies
        the item was removed afterward.

        Args:
            party_slot: Party index 0-5 (0 = first Pokemon).
        """
        from renegade_mcp.take_item import take_item as _take_item

        emu = get_client()
        return _take_item(emu, party_slot)

    @mcp.tool()
    @renegade_tool
    def give_item(item_name: str, party_slot: int = 0) -> dict[str, Any]:
        """Give a held item to a party Pokemon in the overworld.

        Opens pause menu → Pokemon → select slot → Item → Give → bag →
        select item. Verifies the item was applied afterward.

        Pokemon must not already be holding an item (use take_item first).

        Args:
            item_name: Item name (e.g. "Scope Lens"). Case-insensitive.
            party_slot: Party index 0-5 (0 = first Pokemon).
        """
        from renegade_mcp.give_item import give_item as _give_item

        emu = get_client()
        return _give_item(emu, item_name, party_slot)

    # ── PC Storage ──

    @mcp.tool()
    @renegade_tool
    def open_pc() -> dict[str, Any]:
        """Boot up the Pokemon Storage PC and reach the storage menu.

        Finds the PC tile (behavior 0x83) on the current map, navigates to it,
        interacts, and advances through dialogue to the storage system menu
        (DEPOSIT / WITHDRAW / MOVE / MOVE ITEMS / SEE YA!).

        Must be in a building with a PC (e.g., Pokemon Center).
        """
        from renegade_mcp.pc import open_pc as _open_pc

        emu = get_client()
        return _open_pc(emu)

    @mcp.tool()
    @renegade_tool
    def deposit_pokemon(party_slots: list[int]) -> dict[str, Any]:
        """Deposit party Pokemon into PC Box 1.

        Must be called after open_pc (at the storage system menu).
        Deposits each specified party slot, then returns to the storage menu.
        Can deposit multiple Pokemon in one call.

        Args:
            party_slots: List of 0-indexed party slots to deposit (e.g. [4, 5]).
        """
        from renegade_mcp.pc import deposit_pokemon as _deposit_pokemon

        emu = get_client()
        return _deposit_pokemon(emu, party_slots)

    @mcp.tool()
    @renegade_tool
    def withdraw_pokemon(box_slots: list[int]) -> dict[str, Any]:
        """Withdraw Pokemon from PC Box 1 to the party.

        Must be called after open_pc (at the storage system menu).
        Withdraws each specified box slot, then returns to the storage menu.
        Can withdraw multiple Pokemon in one call.

        Args:
            box_slots: List of 0-indexed box slots to withdraw (e.g. [0, 1, 2]).
        """
        from renegade_mcp.pc import withdraw_pokemon as _withdraw_pokemon

        emu = get_client()
        return _withdraw_pokemon(emu, box_slots)

    @mcp.tool()
    def read_box(box: int = 1) -> dict[str, Any]:
        """Read Pokemon data from a PC box directly from memory.

        No UI interaction needed — reads encrypted box data from RAM
        and decrypts it. Works anytime (overworld, in PC, during menus).

        Args:
            box: Box number 1-18 (default: Box 1).
        """
        from renegade_mcp.pc import read_box as _read_box

        emu = get_client()
        return _read_box(emu, box)

    @mcp.tool()
    @renegade_tool
    def close_pc() -> dict[str, Any]:
        """Close the PC and return to the overworld.

        Must be called from the storage system menu (after open_pc or deposit_pokemon).
        Selects SEE YA!, exits through the PC menus, and returns to free movement.
        """
        from renegade_mcp.pc import close_pc as _close_pc

        emu = get_client()
        return _close_pc(emu)

    # ── Heal ──

    @mcp.tool()
    @renegade_tool
    def heal_party() -> dict[str, Any]:
        """Heal the entire party at a Pokemon Center.

        Works from two starting positions:
        - Inside a Pokemon Center: finds the nurse and heals directly.
        - On a city/town overworld: auto-navigates to the Pokemon Center
          via warp lookup + pathfinding, then heals.

        Returns encounter data if a wild battle interrupts navigation.
        Aborts gracefully if Nurse Joy isn't found, navigation is blocked,
        or the dialogue doesn't match the expected greeting (possible event).
        """
        from renegade_mcp.heal_party import heal_party as _heal_party

        emu = get_client()
        return _heal_party(emu)

    # ── Party Reorder ──

    @mcp.tool()
    @renegade_tool
    def reorder_party(from_slot: int, to_slot: int) -> dict[str, Any]:
        """Swap two party Pokemon positions in the overworld.

        Opens pause menu → Pokemon → selects source → Switch → selects destination.
        Both slots must be occupied. Cannot be used in battle.

        Args:
            from_slot: Source party slot (0-5).
            to_slot: Destination party slot (0-5).
        """
        from renegade_mcp.reorder_party import reorder_party as _reorder_party

        emu = get_client()
        return _reorder_party(emu, from_slot, to_slot)

    # ── Auto Grind ──

    @mcp.tool()
    @renegade_tool
    def auto_grind(
        move_index: int = -1,
        cave: bool = False,
        target_level: int = 0,
        iterations: int = 0,
        forget_move: int = -2,
        target_species: str = "",
        backup_move: int = -1,
        heal_x: int = -1,
        heal_y: int = -1,
        grind_x: int = -1,
        grind_y: int = -1,
        max_heal_trips: int = 10,
        flee_ineffective: bool = False,
        target_slot: int = 0,
        auto_heal: bool = False,
    ) -> dict[str, Any]:
        """Grind wild encounters automatically: seek → battle → repeat.

        Place the Pokemon to train in party slot 0 and stand in a grass/cave area.
        The tool loops seek_encounter + battle_turn until a stop condition is hit.

        When move_index is provided, fights each encounter by spamming that move.
        When move_index is omitted, runs from each encounter instead.
        When target_species is set, stops at the action prompt when that species
        appears — ready to fight or catch.

        Smart move selection: when backup_move is set, checks type effectiveness
        per encounter. If primary is NVE/immune but backup is effective, uses backup
        for that battle. If both are ineffective and flee_ineffective=True, flees.

        Auto-heal: two modes available.
        1. Coordinate-based: provide heal_x/heal_y/grind_x/grind_y for same-map healing.
        2. Auto-detect: set auto_heal=True for cross-map healing. No coordinates needed —
           finds the nearest Pokemon Center, navigates there across the overworld, heals,
           and returns to the grind spot. Works from routes and interior maps (caves).

        Stop conditions (returned as stop_reason):
        - fainted: Slot 0 Pokemon fainted (only when auto-heal is disabled).
        - pp_depleted: The spam move has 0 PP (only when auto-heal is disabled).
        - target_level: Slot 0 reached the target level.
        - target_species: Found the target species. At action prompt.
        - iterations: Completed the requested number of encounters.
        - seek_failed: Unexpected interruption while seeking encounters.
        - move_learn: Pokemon wants to learn a new move but has no room.
        - move_blocked: Move blocked by Torment/Disable/Encore/Taunt with no backup.
        - turn_limit: Battle exceeded 10 turns without ending (safety valve).
        - heal_failed: Auto-heal navigation or healing failed.
        - max_heal_trips: Reached the safety cap on heal cycles.
        - unexpected: Unknown battle state — check game manually.

        Returns an `encounters` list: each entry has `species` (name) and
        `checkpoint_id` (hash to revert to for catching that Pokemon).

        Args:
            move_index: Move slot (0-3) to spam every turn. -1 (default) = run from encounters.
            cave: True for cave/indoor encounters (no grass tiles).
            target_level: Stop when slot 0 reaches this level. 0 = no limit.
            iterations: Stop after this many encounters. 0 = no limit.
            forget_move: Resume from a move_learn stop. 0-3 = forget that move slot,
                        -1 = skip learning. -2 (default) = not resuming.
            target_species: Stop when this species is encountered. Case-insensitive.
            backup_move: Fallback move slot (0-3) for Torment/Disable alternation AND
                        smart effectiveness swapping. -1 = no backup.
            heal_x: Town/city tile X to navigate to before healing. -1 = disabled.
            heal_y: Town/city tile Y. -1 = disabled.
            grind_x: Grind area tile X to return to after healing. -1 = disabled.
            grind_y: Grind area tile Y. -1 = disabled.
            max_heal_trips: Safety cap on auto-heal cycles. Default 10.
            flee_ineffective: Flee encounters where both primary and backup moves are
                            ineffective (NVE or immune). Default False.
            target_slot: Party slot (0-5) to check for target_level. Default 0.
                        Use to target an Exp. Share Pokemon in a non-lead slot.
            auto_heal: Auto-detect nearest Pokemon Center and heal on faint/PP depletion.
                      No coordinates needed. Navigates across the overworld and back.
                      Overrides heal_x/heal_y/grind_x/grind_y when True. Default False.
        """
        from renegade_mcp.auto_grind import auto_grind as _auto_grind

        emu = get_client()
        return _auto_grind(
            emu,
            move_index=move_index,
            cave=cave,
            target_level=target_level,
            iterations=iterations,
            forget_move=forget_move,
            target_species=target_species,
            backup_move=backup_move,
            heal_x=heal_x,
            heal_y=heal_y,
            grind_x=grind_x,
            grind_y=grind_y,
            max_heal_trips=max_heal_trips,
            flee_ineffective=flee_ineffective,
            target_slot=target_slot,
            auto_heal=auto_heal,
        )

    # ── Reload ──

    @mcp.tool()
    def reload_tools() -> dict[str, Any]:
        """Reload all renegade_mcp implementation modules in-place.

        Call this after editing any renegade_mcp/*.py file (except server.py)
        to pick up code changes without restarting the MCP server.

        How it works: importlib.reload() refreshes each module in sys.modules.
        Since tool wrappers use lazy imports (from X import Y inside the function
        body), the next tool call automatically picks up the reloaded code.

        Limitation: Changes to server.py itself (new tools, changed signatures)
        require a manual /mcp restart from the user.
        """
        import importlib
        import sys as _sys

        prefix = "renegade_mcp."
        # Collect modules to reload (skip __main__ and server — they define the
        # tool wrappers themselves and can't be meaningfully reloaded in-process).
        to_reload = [
            name
            for name in sorted(_sys.modules)
            if name.startswith(prefix)
            and name not in ("renegade_mcp.server", "renegade_mcp.__main__")
        ]

        reloaded = []
        errors = []
        for name in to_reload:
            try:
                importlib.reload(_sys.modules[name])
                reloaded.append(name.removeprefix(prefix))
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        result: dict[str, Any] = {
            "reloaded": reloaded,
            "count": len(reloaded),
        }
        if errors:
            result["errors"] = errors
        return result

    return mcp
