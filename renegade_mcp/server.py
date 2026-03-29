"""Renegade Platinum MCP server — game-specific tools for Pokemon Renegade Platinum.

Tools connect to the running DeSmuME emulator via the bridge socket.
The server starts without requiring the emulator — connection is lazy.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from renegade_mcp.connection import get_client


def create_server() -> FastMCP:
    """Create and configure the Renegade Platinum MCP server."""
    mcp = FastMCP("renegade")

    # ── Party ──

    @mcp.tool()
    def read_party(refresh: bool = False) -> dict[str, Any]:
        """Read party Pokemon from memory.

        Returns species, level, HP, moves with PP, nature, IVs, EVs for each party member.
        Works in overworld and battle (HP/level unavailable during battle).

        If any slot has stale encrypted data, it returns partial info (species,
        level, HP, nature) with a "partial" flag — moves/IVs/EVs will be missing.

        Args:
            refresh: If True, briefly open/close the party screen to force the
                     game to re-encrypt data. Guarantees full data but only works
                     in the overworld with player control. Do not use in battle.
        """
        from renegade_mcp.party import format_party, read_party as _read_party

        emu = get_client()
        party = _read_party(emu, refresh=refresh)
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
    def view_map() -> dict[str, Any]:
        """Show ASCII map of current area with terrain, player position, and NPCs.

        Handles indoor maps (from RAM) and overworld multi-chunk maps (from ROM).
        Player shown as ^v<> (facing), NPCs as A-Z. Includes terrain behaviors.
        """
        from renegade_mcp.map_state import view_map as _view_map

        emu = get_client()
        return _view_map(emu)

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
    def navigate(directions: str) -> dict[str, Any]:
        """Walk a manual path in the overworld.

        Moves one tile per direction (16 frames hold + 8 frames wait), verifying
        each step. Stops early if blocked (collision, encounter, cutscene).

        Args:
            directions: Space-separated directions: up/down/left/right (or u/d/l/r)
                       with optional repeat counts (e.g. "l20 u5 r3").
        """
        from renegade_mcp.navigation import navigate_manual

        emu = get_client()
        return navigate_manual(emu, directions)

    @mcp.tool()
    def navigate_to(x: int, y: int) -> dict[str, Any]:
        """Pathfind to a target tile using BFS, then walk there.

        Reads terrain and NPC positions, computes shortest path, and executes it
        step by step with position verification. Supports local (0-31) and global
        coordinates (auto-detected). Handles multi-chunk overworld maps.

        Args:
            x: Target X coordinate (local or global).
            y: Target Y coordinate (local or global).
        """
        from renegade_mcp.navigation import navigate_to as _navigate_to

        emu = get_client()
        return _navigate_to(emu, x, y)

    @mcp.tool()
    def interact_with(object_index: int = -1, x: int = -1, y: int = -1) -> dict[str, Any]:
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
        """
        from renegade_mcp.navigation import interact_with as _interact_with

        emu = get_client()
        return _interact_with(emu, object_index=object_index, x=x, y=y)

    @mcp.tool()
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

    @mcp.tool()
    def battle_turn(move_index: int = -1, switch_to: int = -1, forget_move: int = -2) -> dict[str, Any]:
        """Execute a full battle turn: use a move OR switch Pokemon.

        Combines battle_init + action + battle_poll into one call.
        Specify exactly one action: move_index to fight, or switch_to to swap.

        Actions:
        - move_index (0-3): Tap FIGHT, select the move (top-left, top-right, bottom-left, bottom-right).
        - switch_to (1-5): Tap POKEMON, navigate to party slot, confirm switch. Slot 0 is the active battler.
        - forget_move (0-3): At MOVE_LEARN prompt, forget this move slot and learn the new move.
        - forget_move=-1: At MOVE_LEARN prompt, skip learning the new move.

        States returned:
        - WAIT_FOR_ACTION: next turn ready, select another move
        - SWITCH_PROMPT: trainer sending next Pokemon, switch or keep battling
        - MOVE_LEARN: move learning prompt — includes move_to_learn and current_moves
        - BATTLE_ENDED: battle over, back in overworld
        - TIMEOUT: poll limit reached, check game state manually
        - NO_TEXT: action may not have registered
        """
        from renegade_mcp.turn import battle_turn as _battle_turn

        emu = get_client()
        return _battle_turn(emu, move_index=move_index, switch_to=switch_to, forget_move=forget_move)

    # ── Catch ──

    @mcp.tool()
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

    # ── Item Use ──

    @mcp.tool()
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

    # ── PC Storage ──

    @mcp.tool()
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
    def heal_party() -> dict[str, Any]:
        """Heal the entire party at a Pokemon Center.

        Finds the Pokecenter Nurse on the current map by graphicsID, walks up,
        talks to her, advances through the healing dialogue, and verifies all
        party HP is restored. Must be inside a Pokemon Center.

        Aborts gracefully if Nurse Joy isn't found, navigation is interrupted,
        or the dialogue doesn't match the expected greeting (possible event).
        """
        from renegade_mcp.heal_party import heal_party as _heal_party

        emu = get_client()
        return _heal_party(emu)

    # ── Party Reorder ──

    @mcp.tool()
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

    return mcp
