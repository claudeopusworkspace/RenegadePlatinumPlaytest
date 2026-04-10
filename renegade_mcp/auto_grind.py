"""Auto-grind tool — seek encounters and battle automatically until a stop condition."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# Lazy imports — resolved at call time so reload_tools order doesn't matter.
# from renegade_mcp.battle import read_battle
# from renegade_mcp.navigation import seek_encounter
# from renegade_mcp.party import read_party
# from renegade_mcp.turn import battle_turn


# States that mean "battle is over, back in overworld"
_BATTLE_OVER = {"BATTLE_ENDED"}

# States that mean "need user decision on move learning"
_MOVE_LEARN = {"MOVE_LEARN"}

# States that mean "our Pokemon fainted"
_FAINT = {"FAINT_SWITCH", "FAINT_FORCED"}

# States that are unexpected / errors
_ERROR = {"TIMEOUT", "NO_TEXT", "NO_ACTION_PROMPT", "LEVEL_UP"}


def auto_grind(
    emu: EmulatorClient,
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
    """Grind wild encounters automatically.

    Loops: seek_encounter → battle/run → repeat.

    When move_index is provided, fights each encounter by spamming that move.
    When move_index is omitted, runs from each encounter instead.
    When target_species is set, stops at the action prompt when that species
    appears — ready to fight or catch.

    Args:
        emu: Emulator client.
        move_index: Move slot (0-3) to use every turn. -1 = run from encounters.
        cave: Pass to seek_encounter for cave/indoor encounters.
        target_level: Stop when the target_slot Pokemon reaches this level. 0 = no limit.
        iterations: Stop after this many wild encounters. 0 = no limit.
        forget_move: If resuming from a MOVE_LEARN stop, pass the choice here
                     (0-3 = forget that slot, -1 = skip learning). -2 = not resuming.
        target_species: Stop when this species appears. Case-insensitive.
                        Empty = no species filter.
        backup_move: Fallback move slot (0-3) when primary is blocked by Torment/Disable/
                     Encore/Taunt. Also used when primary is ineffective (NVE/immune)
                     against the current encounter. -1 = no backup.
        heal_x: Town/city tile X to navigate to before healing. -1 = disabled.
        heal_y: Town/city tile Y. -1 = disabled.
        grind_x: Grind area tile X to return to after healing. -1 = disabled.
        grind_y: Grind area tile Y. -1 = disabled.
        max_heal_trips: Safety cap on auto-heal cycles. Default 10.
        flee_ineffective: If True, flee encounters where both primary and backup
                          moves are ineffective (mult <= 0.5). Default False.
        target_slot: Party slot (0-5) to check for target_level. Default 0.
                     Use to target an Exp. Share Pokemon in a non-lead slot.
        auto_heal: If True, auto-detect the nearest Pokemon Center and heal
                   there on faint/PP depletion. No coordinates needed — navigates
                   across the overworld matrix and back. For interior maps
                   (cave sub-floors), exits via warps to reach the overworld first.
                   Overrides heal_x/heal_y/grind_x/grind_y if both are set.

    Returns:
        Dict with stop_reason, battles fought, encounters list (species + checkpoint),
        log of each battle, party state, and heal_trips count.
    """
    from renegade_mcp.battle import read_battle as _read_battle
    from renegade_mcp.navigation import seek_encounter as _seek_encounter
    from renegade_mcp.party import read_party as _read_party
    from renegade_mcp.turn import battle_turn as _battle_turn
    from renegade_mcp.phase_timer import phase

    fighting = move_index >= 0
    battles: list[dict[str, Any]] = []
    encounters: list[dict[str, str]] = []
    stop_reason = ""
    stop_detail = ""
    heal_enabled = auto_heal or (heal_x >= 0 and heal_y >= 0 and grind_x >= 0 and grind_y >= 0)
    heal_trips = 0
    fled_ineffective: list[str] = []  # Species fled due to ineffective moves

    # ── If resuming from a MOVE_LEARN, handle that first ──
    if forget_move >= -1:
        emu.create_checkpoint(action=f"auto_grind:resume(forget_move={forget_move})")
        result = _battle_turn(emu, forget_move=forget_move)
        state = result.get("final_state", "")

        if state in _BATTLE_OVER:
            if result.get("blackout"):
                return _finish(
                    "fainted",
                    "Full party wipe — blacked out to Pokemon Center.",
                    battles, _read_party(emu),
                )
            # Move learn resolved, battle ended — check level then continue grinding
            party = _read_party(emu)
            target_mon = party[target_slot] if len(party) > target_slot else None
            if target_level > 0 and target_mon and target_mon["level"] >= target_level:
                return _finish(
                    "target_level",
                    f"Slot {target_slot} ({target_mon.get('name', '?')}) reached Lv{target_mon['level']} (target: {target_level}).",
                    battles, party,
                )
            # Fall through to the main grind loop
        elif state == "WAIT_FOR_ACTION":
            # Move learn resolved mid-battle — continue this battle
            if fighting:
                stop_reason, stop_detail, battle_log, detected_level = _fight_battle(
                    emu, move_index, backup_move=backup_move,
                    initial_result=result, resuming=True,
                )
            else:
                stop_reason, stop_detail, battle_log, detected_level = _run_battle(emu)
            battles.append({"turns": battle_log})
            if stop_reason:
                party = _read_party(emu)
                return _finish(stop_reason, stop_detail, battles, party)
            # Battle ended normally — check level from log first
            if target_level > 0 and detected_level is not None and detected_level >= target_level:
                party = _read_party(emu)
                return _finish(
                    "target_level",
                    f"Slot 0 reached Lv{detected_level} (target: {target_level}).",
                    battles, party,
                )
            # Fall back to read_party
            party = _read_party(emu)
            target_mon = party[target_slot] if len(party) > target_slot else None
            if target_level > 0 and target_mon and not target_mon.get("partial") and target_mon["level"] >= target_level:
                return _finish(
                    "target_level",
                    f"Slot {target_slot} ({target_mon.get('name', '?')}) reached Lv{target_mon['level']} (target: {target_level}).",
                    battles, party,
                )
            # Fall through to main loop
        elif state in _MOVE_LEARN:
            # Another move learn immediately — stop again for user input
            return _finish(
                "move_learn",
                _move_learn_detail(result),
                battles, _read_party(emu),
                move_learn=result,
            )
        elif state in _FAINT:
            return _finish(
                "fainted",
                f"Slot 0 fainted after move-learn resolution. State: {state}",
                battles, _read_party(emu),
            )
        else:
            return _finish(
                "unexpected",
                f"Unexpected state after move-learn resolution: {state}",
                battles, _read_party(emu),
            )

    # ── Main grind loop ──
    first_loop = True
    while True:
        # Check if we're already in battle (mid-battle resume)
        already_in_battle = False
        if first_loop:
            battlers = _read_battle(emu)
            if battlers:
                already_in_battle = True

        if already_in_battle:
            # Mid-battle resume — skip seek_encounter, go straight to fighting
            enemy_species = "unknown"
            for b in battlers:
                if b.get("side") == "enemy":
                    enemy_species = b.get("species", "unknown")
                    break
            enc_cp = emu.create_checkpoint(action=f"auto_grind:resume_battle({enemy_species})")
            encounters.append({"species": enemy_species, "checkpoint_id": enc_cp.get("checkpoint_id", "")})
        else:
            # Seek a wild encounter
            mode = "cave" if cave else "grass"
            emu.create_checkpoint(action=f"auto_grind:seek_encounter({mode})")
            with phase("ag_seek_encounter"):
                enc = _seek_encounter(emu, cave=cave)
            enc_result = enc.get("result", "")

            if enc_result != "encounter":
                stop_reason = "seek_failed"
                stop_detail = (
                    f"seek_encounter returned '{enc_result}' instead of 'encounter'. "
                    f"Position: {enc.get('position', '?')}. "
                    "Possible cutscene trigger or blocked path."
                )
                break

            # Log the encountered species + checkpoint for potential revert-to-catch
            battlers = _read_battle(emu)
            enemy_species = "unknown"
            for b in battlers:
                if b.get("side") == "enemy":
                    enemy_species = b.get("species", "unknown")
                    break
            enc_cp = emu.create_checkpoint(action=f"auto_grind:encounter({enemy_species})")
            encounters.append({"species": enemy_species, "checkpoint_id": enc_cp.get("checkpoint_id", "")})

        first_loop = False

        # Check for shiny before anything else — always stop on shinies
        enemy_shiny = any(
            b.get("shiny") for b in battlers if b.get("side") == "enemy"
        )
        if enemy_shiny:
            stop_reason = "shiny"
            stop_detail = (
                f"SHINY {enemy_species}! At action prompt — ready to fight or catch."
            )
            break

        # Check target_species before fighting/running
        if target_species and enemy_species.lower() == target_species.lower():
            stop_reason = "target_species"
            stop_detail = (
                f"Found {enemy_species}! At action prompt — ready to fight or catch."
            )
            break

        # ── Smart move selection: pick best move for this encounter ──
        effective_move = move_index
        effective_backup = backup_move
        if fighting and backup_move >= 0:
            primary_eff = _check_effectiveness(battlers, move_index)
            if primary_eff is not None and primary_eff <= 0.5:
                # Primary is ineffective — check backup
                backup_eff = _check_effectiveness(battlers, backup_move)
                backup_has_pp = True
                player = next((b for b in battlers if b.get("side") == "player"), None)
                if player and backup_move < len(player.get("moves", [])):
                    backup_has_pp = (player["moves"][backup_move].get("pp", 1) or 0) > 0
                if (backup_eff is None or backup_eff > 0.5) and backup_has_pp:
                    # Backup is effective — swap for this encounter
                    effective_move = backup_move
                    effective_backup = move_index
                elif flee_ineffective:
                    # Both ineffective — flee this encounter
                    _sr, _sd, battle_log, _ = _run_battle(emu)
                    battles.append({"turns": battle_log})
                    fled_ineffective.append(enemy_species)
                    if _sr:  # Faint while fleeing
                        stop_reason, stop_detail = _sr, _sd
                        break
                    first_loop = False
                    continue
        elif fighting and flee_ineffective:
            # No backup move, but flee_ineffective is set — check primary only
            primary_eff = _check_effectiveness(battlers, move_index)
            if primary_eff is not None and primary_eff <= 0.5:
                _sr, _sd, battle_log, _ = _run_battle(emu)
                battles.append({"turns": battle_log})
                fled_ineffective.append(enemy_species)
                if _sr:
                    stop_reason, stop_detail = _sr, _sd
                    break
                first_loop = False
                continue

        # We have a battle — fight or run
        with phase("ag_battle"):
            if fighting:
                stop_reason, stop_detail, battle_log, detected_level = _fight_battle(
                    emu, effective_move, backup_move=effective_backup,
                )
            else:
                stop_reason, stop_detail, battle_log, detected_level = _run_battle(emu)
        battles.append({"turns": battle_log})

        # ── Auto-heal on faint or PP depletion (mid-battle) ──
        if stop_reason in ("fainted", "pp_depleted") and heal_enabled:
            if heal_trips >= max_heal_trips:
                stop_reason = "max_heal_trips"
                stop_detail = f"Reached max heal trips ({max_heal_trips})."
                break
            is_fainted = stop_reason == "fainted"
            with phase("ag_heal_and_return"):
                if auto_heal:
                    heal_result = _auto_heal_and_return(
                        emu, in_battle=True, fainted=is_fainted,
                    )
                else:
                    heal_result = _heal_and_return(
                        emu, heal_x, heal_y, grind_x, grind_y,
                        in_battle=True, fainted=is_fainted,
                    )
            heal_trips += 1
            if heal_result.get("success"):
                stop_reason = ""
                stop_detail = ""
                first_loop = False
                continue
            else:
                stop_reason = "heal_failed"
                stop_detail = heal_result.get("error", "Auto-heal failed.")
                break

        if stop_reason:
            break

        # Check iterations limit
        if iterations > 0 and len(battles) >= iterations:
            stop_reason = "iterations"
            stop_detail = f"Completed {iterations} encounter(s) as requested."
            break

        # Battle ended normally — check level from battle log first (immune
        # to encryption-state issues), then fall back to read_party for PP.
        # Log-based detection only works for the lead (slot 0).
        if target_level > 0 and target_slot == 0 and detected_level is not None and detected_level >= target_level:
            stop_reason = "target_level"
            stop_detail = f"Slot 0 reached Lv{detected_level} (target: {target_level})."
            break

        # Fall back to read_party for level + PP check (always needed for non-lead target_slot)
        party = _read_party(emu)
        target_mon = party[target_slot] if len(party) > target_slot else None
        if target_level > 0 and target_mon and not target_mon.get("partial") and target_mon["level"] >= target_level:
            stop_reason = "target_level"
            stop_detail = f"Slot {target_slot} ({target_mon.get('name', '?')}) reached Lv{target_mon['level']} (target: {target_level})."
            break
        slot0 = party[0] if party else None
        if fighting and slot0 and not slot0.get("partial") and slot0["pp"][move_index] <= 0:
            if heal_enabled:
                if heal_trips >= max_heal_trips:
                    stop_reason = "max_heal_trips"
                    stop_detail = f"Reached max heal trips ({max_heal_trips})."
                    break
                if auto_heal:
                    heal_result = _auto_heal_and_return(
                        emu, in_battle=False, fainted=False,
                    )
                else:
                    heal_result = _heal_and_return(
                        emu, heal_x, heal_y, grind_x, grind_y,
                        in_battle=False, fainted=False,
                    )
                heal_trips += 1
                if heal_result.get("success"):
                    continue
                else:
                    stop_reason = "heal_failed"
                    stop_detail = heal_result.get("error", "Auto-heal failed.")
                    break
            else:
                stop_reason = "pp_depleted"
                stop_detail = (
                    f"Move slot {move_index} ({slot0['move_names'][move_index]}) "
                    f"has 0 PP. Pokemon is in the overworld — use an Ether or "
                    f"swap to a different spam move before continuing."
                )
                break

    # Gather final party state
    party = _read_party(emu)
    result = _finish(
        stop_reason, stop_detail, battles, party,
        encounters=encounters, heal_trips=heal_trips,
        fled_ineffective=fled_ineffective,
    )

    # If stopped for target_species or shiny, include trimmed battle state
    if stop_reason in ("target_species", "shiny"):
        from renegade_mcp.battle import battle_summary
        result["battle_state"] = battle_summary(_read_battle(emu))

    return result


def _fight_battle(
    emu: EmulatorClient,
    move_index: int,
    backup_move: int = -1,
    initial_result: dict[str, Any] | None = None,
    resuming: bool = False,
) -> tuple[str, str, list[dict[str, Any]], int | None]:
    """Fight a single wild battle by spamming move_index each turn.

    Returns (stop_reason, stop_detail, battle_log, detected_level).
    stop_reason is empty string if battle ended normally (BATTLE_ENDED).
    detected_level is parsed from 'grew to Lv. N' in the battle log, or None.
    """
    from renegade_mcp.turn import battle_turn as _battle_turn

    battle_log: list[dict[str, Any]] = []
    turn = 0
    use_backup = False  # Alternates with primary after MOVE_BLOCKED

    # If resuming mid-battle, the initial_result is the last battle_turn response
    if resuming and initial_result:
        battle_log.append({"turn": turn, "state": initial_result.get("final_state"), "log": _flatten_log(initial_result)})
        turn += 1

    max_turns = 10
    while True:
        if turn >= max_turns:
            return (
                "turn_limit",
                f"Battle exceeded {max_turns} turns without ending. "
                "Possible move-lock (Torment/Disable/Encore/Taunt) or unexpectedly tanky opponent.",
                battle_log,
                _extract_level_from_log(battle_log),
            )
        current_move = backup_move if use_backup else move_index
        emu.create_checkpoint(action=f"auto_grind:battle_turn(move={current_move}, turn={turn})")
        result = _battle_turn(emu, move_index=current_move)
        state = result.get("final_state", "")
        battle_log.append({"turn": turn, "state": state, "log": _flatten_log(result)})
        turn += 1

        if state in _BATTLE_OVER:
            if result.get("blackout"):
                return (
                    "fainted",
                    "Full party wipe — blacked out to Pokemon Center.",
                    battle_log,
                    _extract_level_from_log(battle_log),
                )
            # Normal end — no stop reason
            return "", "", battle_log, _extract_level_from_log(battle_log)

        if state == "MOVE_BLOCKED":
            if backup_move < 0:
                return (
                    "move_blocked",
                    f"Move slot {current_move} was blocked (Torment/Disable/Encore/Taunt). "
                    "Provide backup_move to auto-alternate, or handle manually.",
                    battle_log,
                    _extract_level_from_log(battle_log),
                )
            # battle_turn already pressed B to return to the main action menu
            # after MOVE_BLOCKED. Just call battle_turn with the alternate move.
            alt_move = move_index if use_backup else backup_move
            result2 = _battle_turn(emu, move_index=alt_move)
            state2 = result2.get("final_state", "")
            battle_log.append({"turn": turn, "state": state2, "log": _flatten_log(result2)})
            turn += 1
            if state2 in _BATTLE_OVER:
                if result2.get("blackout"):
                    return (
                        "fainted",
                        "Full party wipe — blacked out to Pokemon Center.",
                        battle_log,
                        _extract_level_from_log(battle_log),
                    )
                return "", "", battle_log, _extract_level_from_log(battle_log)
            if state2 == "MOVE_BLOCKED":
                # Both moves blocked — bail
                return (
                    "move_blocked",
                    f"Both move slot {move_index} and backup slot {backup_move} are blocked.",
                    battle_log,
                    _extract_level_from_log(battle_log),
                )
            # Successful turn with backup — toggle for next iteration
            use_backup = not use_backup
            continue

        if state == "WAIT_FOR_ACTION":
            # Successful turn — reset to primary move
            use_backup = False
            # Check PP for our spam move before next turn
            pp = _get_move_pp(result, move_index)
            if pp is not None and pp <= 0:
                return (
                    "pp_depleted",
                    f"Move slot {move_index} has 0 PP. Battle still active — "
                    "manual intervention needed (flee, use another move, or use an item).",
                    battle_log,
                    _extract_level_from_log(battle_log),
                )
            # Otherwise continue fighting
            continue

        if state == "SWITCH_PROMPT":
            # Wild battle — opponent shouldn't be sending in new Pokemon.
            # Just continue (battle_turn with no args = decline switch).
            emu.create_checkpoint(action="auto_grind:decline_switch")
            result2 = _battle_turn(emu)
            state2 = result2.get("final_state", "")
            battle_log.append({"turn": turn, "state": state2, "log": _flatten_log(result2)})
            turn += 1
            if state2 in _BATTLE_OVER:
                return "", "", battle_log, _extract_level_from_log(battle_log)
            # If still going, continue the fight loop
            continue

        if state in _FAINT:
            return (
                "fainted",
                f"Slot 0 Pokemon fainted. State: {state}. "
                "Return to a Pokemon Center or use revives before continuing.",
                battle_log,
                _extract_level_from_log(battle_log),
            )

        if state in _MOVE_LEARN:
            return (
                "move_learn",
                _move_learn_detail(result),
                battle_log,
                _extract_level_from_log(battle_log),
            )

        # Anything else is unexpected
        return (
            "unexpected",
            f"Unexpected battle state: {state}. Check game manually.",
            battle_log,
            _extract_level_from_log(battle_log),
        )


def _run_battle(
    emu: EmulatorClient,
) -> tuple[str, str, list[dict[str, Any]], int | None]:
    """Attempt to run from a wild battle. Retries on failure.

    Returns (stop_reason, stop_detail, battle_log, detected_level).
    stop_reason is empty string if we escaped successfully (BATTLE_ENDED).
    """
    from renegade_mcp.turn import battle_turn as _battle_turn

    battle_log: list[dict[str, Any]] = []
    turn = 0

    while True:
        emu.create_checkpoint(action=f"auto_grind:run(turn={turn})")
        result = _battle_turn(emu, run=True)
        state = result.get("final_state", "")
        battle_log.append({"turn": turn, "state": state, "log": _flatten_log(result)})
        turn += 1

        if state in _BATTLE_OVER:
            if result.get("blackout"):
                return (
                    "fainted",
                    "Full party wipe — blacked out to Pokemon Center.",
                    battle_log,
                    None,
                )
            return "", "", battle_log, None

        if state == "WAIT_FOR_ACTION":
            # Failed to escape — enemy got a free turn. Try running again.
            continue

        if state in _FAINT:
            return (
                "fainted",
                f"Slot 0 Pokemon fainted while trying to run. State: {state}. "
                "Return to a Pokemon Center or use revives before continuing.",
                battle_log,
                None,
            )

        # Anything else is unexpected
        return (
            "unexpected",
            f"Unexpected battle state while running: {state}. Check game manually.",
            battle_log,
            None,
        )


def _heal_and_return(
    emu: EmulatorClient,
    heal_x: int,
    heal_y: int,
    grind_x: int,
    grind_y: int,
    in_battle: bool = False,
    fainted: bool = False,
) -> dict[str, Any]:
    """Exit battle (if needed), navigate to town, heal, return to grind area.

    Args:
        emu: Emulator client.
        heal_x, heal_y: Town/city tile to navigate to before healing.
        grind_x, grind_y: Grind area tile to return to after healing.
        in_battle: True if still in a battle (faint or PP depletion mid-battle).
        fainted: True if at FAINT_SWITCH prompt (flee by declining switch).
                 False if at WAIT_FOR_ACTION (flee by running).

    Returns:
        {"success": True} or {"success": False, "error": "..."}.
    """
    from renegade_mcp.turn import battle_turn as _battle_turn
    from renegade_mcp.heal_party import heal_party as _heal_party
    from renegade_mcp.navigation import navigate_to as _navigate_to
    from renegade_mcp.map_state import read_player_state, read_warps_from_rom

    # ── Step 1: Exit battle if still in one ──
    if in_battle:
        if fainted:
            # At FAINT_SWITCH — decline switch to flee wild battle
            result = _battle_turn(emu)
            state = result.get("final_state", "")
            if state not in _BATTLE_OVER:
                return {"success": False, "error": f"Failed to exit battle after faint. State: {state}"}
        else:
            # At WAIT_FOR_ACTION — run away
            max_flee = 5
            for _ in range(max_flee):
                result = _battle_turn(emu, run=True)
                state = result.get("final_state", "")
                if state in _BATTLE_OVER:
                    break
                if state in _FAINT:
                    # Fainted while fleeing — try declining switch
                    result2 = _battle_turn(emu)
                    state2 = result2.get("final_state", "")
                    if state2 not in _BATTLE_OVER:
                        return {"success": False, "error": f"Fainted while fleeing and couldn't exit. State: {state2}"}
                    break
                if state not in ("WAIT_FOR_ACTION", "ACTION"):
                    return {"success": False, "error": f"Unexpected state while fleeing: {state}"}
            else:
                return {"success": False, "error": f"Failed to flee after {max_flee} attempts."}
        # Settle to overworld
        emu.advance_frames(120)

    # ── Step 2: Navigate to heal location (town/city tile) ──
    emu.create_checkpoint(action=f"auto_grind:heal_navigate(to={heal_x},{heal_y})")
    nav_result = _navigate_to(emu, heal_x, heal_y, flee_encounters=True)
    if nav_result.get("error"):
        return {"success": False, "error": f"Navigation to heal failed: {nav_result['error']}"}
    if nav_result.get("encounter") and nav_result["encounter"].get("dialogue"):
        # Trainer battle during navigation — can't auto-handle
        return {"success": False, "error": "Trainer battle during navigation to heal.", "encounter": nav_result["encounter"]}

    # ── Step 3: Heal at Pokemon Center ──
    heal_result = _heal_party(emu)
    if not heal_result.get("success"):
        return {"success": False, "error": f"Healing failed: {heal_result.get('error', heal_result.get('formatted', 'unknown'))}"}

    # ── Step 4: Exit the Pokemon Center ──
    # After healing, player is inside the PC in front of Nurse Joy.
    # Find the exit warp and walk to it.
    map_id, _, _, _ = read_player_state(emu)
    warps = read_warps_from_rom(emu, map_id)
    if not warps:
        return {"success": False, "error": "No warps found in Pokemon Center — can't exit."}
    # PC typically has one exit warp at the bottom (door mat).
    # Pick the warp with the highest Y coordinate (closest to door).
    exit_warp = max(warps, key=lambda w: w.get("y", 0))
    nav_result = _navigate_to(emu, exit_warp["x"], exit_warp["y"])
    if nav_result.get("error"):
        return {"success": False, "error": f"Failed to exit Pokemon Center: {nav_result['error']}"}
    # Wait for map transition to complete
    emu.advance_frames(120)

    # ── Step 5: Navigate back to grind area ──
    emu.create_checkpoint(action=f"auto_grind:heal_return(to={grind_x},{grind_y})")
    nav_result = _navigate_to(emu, grind_x, grind_y, flee_encounters=True)
    if nav_result.get("error"):
        return {"success": False, "error": f"Navigation back to grind area failed: {nav_result['error']}"}
    if nav_result.get("encounter") and nav_result["encounter"].get("dialogue"):
        return {"success": False, "error": "Trainer battle during navigation back to grind area.", "encounter": nav_result["encounter"]}

    return {"success": True}


# ── Cross-map auto-heal ──


def _find_nearest_pc(emu: EmulatorClient, player_map: int, px: int, py: int) -> dict[str, Any] | None:
    """Find the nearest Pokemon Center reachable from the player's position.

    Searches all cities/towns with PCs on the same overworld matrix.
    Returns {"city_map": int, "city_code": str, "pc_warp_x": int,
             "pc_warp_y": int, "chunk_dist": int} or None.
    """
    candidates = _find_all_pcs(emu, player_map, px, py)
    return candidates[0] if candidates else None


def _find_all_pcs(
    emu: EmulatorClient, player_map: int, px: int, py: int, max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find all Pokemon Centers on the same matrix, sorted by chunk distance.

    Returns up to max_results entries, each with:
    {"city_map", "city_code", "city_name", "pc_warp_x", "pc_warp_y", "chunk_dist"}.
    """
    import re as _re
    from renegade_mcp.data import map_table as _map_table
    from renegade_mcp.map_state import find_matrix_for_map, read_warps_from_rom

    table = _map_table()

    # Find the player's matrix
    player_matrix = find_matrix_for_map(player_map)
    if player_matrix is None:
        return []

    p_matrix_id = player_matrix[0]
    player_chunk_x = px // 32
    player_chunk_y = py // 32

    # Collect all city/town map IDs that have a Pokemon Center
    city_codes = {}  # code -> map_id
    for mid, entry in table.items():
        code = entry.get("code", "")
        if _re.match(r"^[CT]\d{2}$", code):
            city_codes[code] = mid

    # Filter to cities that actually have a PC (any map with code starting "{city}PC")
    pc_codes = set()
    for entry in table.values():
        code = entry.get("code", "")
        m = _re.match(r"^([CT]\d{2})PC", code)
        if m:
            pc_codes.add(m.group(1))

    cities_with_pc = {code: mid for code, mid in city_codes.items() if code in pc_codes}

    # For each city on the same matrix, compute distance
    results = []
    for code, city_mid in cities_with_pc.items():
        city_matrix = find_matrix_for_map(city_mid)
        if city_matrix is None:
            continue
        if city_matrix[0] != p_matrix_id:
            continue

        warps = read_warps_from_rom(emu, city_mid)
        pc_warp = None
        for w in warps:
            dest_entry = table.get(w["dest_map"], {})
            if dest_entry.get("code", "").startswith(f"{code}PC"):
                pc_warp = w
                break
        if pc_warp is None:
            continue

        warp_chunk_x = pc_warp["x"] // 32
        warp_chunk_y = pc_warp["y"] // 32
        chunk_dist = abs(warp_chunk_x - player_chunk_x) + abs(warp_chunk_y - player_chunk_y)

        results.append({
            "city_map": city_mid,
            "city_code": code,
            "city_name": table.get(city_mid, {}).get("name", code),
            "pc_warp_x": pc_warp["x"],
            "pc_warp_y": pc_warp["y"],
            "chunk_dist": chunk_dist,
        })

    results.sort(key=lambda r: r["chunk_dist"])
    return results[:max_results]


def _exit_to_overworld(emu: EmulatorClient) -> dict[str, Any] | None:
    """If on an interior map (not on the overworld matrix), follow warps outward.

    Returns {"success": True, "return_warps": [...]} with the warp chain
    needed to return, or None if already on the overworld (no action needed).
    Returns {"success": False, "error": "..."} on failure.
    """
    from renegade_mcp.map_state import find_matrix_for_map, read_player_state, read_warps_from_rom
    from renegade_mcp.navigation import navigate_to as _navigate_to
    from renegade_mcp.data import map_table as _map_table

    map_id, px, py, _ = read_player_state(emu)
    table = _map_table()

    # Check if already on the overworld matrix (matrix 0)
    matrix_info = find_matrix_for_map(map_id)
    if matrix_info is not None and matrix_info[0] == 0:
        return None  # Already on overworld

    # Interior map — find a warp leading outward
    return_warps = []
    max_hops = 5

    for _ in range(max_hops):
        warps = read_warps_from_rom(emu, map_id)
        if not warps:
            return {"success": False, "error": f"No warps on map {map_id} — stuck in interior."}

        # Prefer warps to overworld maps; otherwise take any warp leading outward
        best_warp = None
        for w in warps:
            dest_matrix = find_matrix_for_map(w["dest_map"])
            if dest_matrix is not None and dest_matrix[0] == 0:
                best_warp = w
                break  # Found a direct exit to overworld
        if best_warp is None:
            # Just take the first warp (heuristic: try to exit)
            best_warp = warps[0]

        # Record for return trip: on dest_map, warp at index dest_warp leads back
        return_warps.append({
            "source_map": map_id,
            "dest_map": best_warp["dest_map"],
            "dest_warp_idx": best_warp["dest_warp"],
        })

        # Navigate to the warp tile
        nav = _navigate_to(emu, best_warp["x"], best_warp["y"])
        if nav.get("error"):
            return {"success": False, "error": f"Can't reach exit warp: {nav['error']}"}

        # Wait for map transition
        emu.advance_frames(120)

        # Check new position
        map_id, px, py, _ = read_player_state(emu)
        matrix_info = find_matrix_for_map(map_id)
        if matrix_info is not None and matrix_info[0] == 0:
            return {"success": True, "return_warps": return_warps}

    return {"success": False, "error": f"Could not reach overworld after {max_hops} warp hops."}


def _return_to_interior(emu: EmulatorClient, return_warps: list[dict]) -> dict[str, Any]:
    """Reverse a warp chain recorded by _exit_to_overworld to get back inside."""
    from renegade_mcp.map_state import read_warps_from_rom, read_player_state
    from renegade_mcp.navigation import navigate_to as _navigate_to

    for step in reversed(return_warps):
        # We need to go from step["dest_map"] back to step["source_map"]
        # The warp at index step["dest_warp_idx"] on step["dest_map"] leads back
        map_id, _, _, _ = read_player_state(emu)
        warps = read_warps_from_rom(emu, map_id)

        if step["dest_warp_idx"] >= len(warps):
            return {"success": False, "error": f"Return warp index {step['dest_warp_idx']} out of range on map {map_id}."}

        return_warp = warps[step["dest_warp_idx"]]
        nav = _navigate_to(emu, return_warp["x"], return_warp["y"], flee_encounters=True)
        if nav.get("error"):
            return {"success": False, "error": f"Can't reach return warp: {nav['error']}"}

        emu.advance_frames(120)

    return {"success": True}


def _navigate_multi_hop(
    emu: EmulatorClient, target_x: int, target_y: int, max_hops: int = 20,
) -> dict[str, Any]:
    """Navigate to a distant target using multiple navigate_to calls.

    Breaks long paths into ~3-chunk segments to stay within the 5x5
    chunk terrain loading cap. Returns the final navigate_to result.
    """
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.navigation import navigate_to as _navigate_to

    for hop in range(max_hops):
        map_id, px, py, _ = read_player_state(emu)

        # Close enough — try a direct navigate_to
        chunk_dx = abs(target_x // 32 - px // 32)
        chunk_dy = abs(target_y // 32 - py // 32)

        if chunk_dx <= 3 and chunk_dy <= 3:
            # Within range for a single navigate_to
            return _navigate_to(emu, target_x, target_y, flee_encounters=True)

        # Too far — compute an intermediate waypoint ~3 chunks toward target
        dx = target_x - px
        dy = target_y - py
        dist = max(abs(dx), abs(dy), 1)
        step_tiles = 3 * 32  # ~3 chunks

        # Scale the direction vector to ~3 chunks
        if dist <= step_tiles:
            wp_x, wp_y = target_x, target_y
        else:
            wp_x = px + int(dx * step_tiles / dist)
            wp_y = py + int(dy * step_tiles / dist)

        nav = _navigate_to(emu, wp_x, wp_y, flee_encounters=True)

        # Check for blocking errors
        if nav.get("error"):
            # Path might be blocked at this waypoint — try adjusting
            # If we didn't move at all, this is a real block
            new_map, new_x, new_y, _ = read_player_state(emu)
            if new_x == px and new_y == py:
                return nav  # Truly stuck
            # We moved some — continue from new position

        if nav.get("encounter") and nav["encounter"].get("dialogue"):
            return nav  # Trainer battle — can't auto-handle

    return {"error": f"Could not reach ({target_x},{target_y}) after {max_hops} hops."}


def _auto_heal_and_return(
    emu: EmulatorClient,
    in_battle: bool = False,
    fainted: bool = False,
) -> dict[str, Any]:
    """Exit battle → navigate to nearest PC → heal → return to grind spot.

    Works across map boundaries. For overworld maps (routes, cities), navigates
    directly. For interior maps (cave sub-floors), exits via warps first.

    Returns {"success": True} or {"success": False, "error": "..."}.
    """
    from renegade_mcp.turn import battle_turn as _battle_turn
    from renegade_mcp.heal_party import heal_party as _heal_party
    from renegade_mcp.navigation import navigate_to as _navigate_to
    from renegade_mcp.map_state import read_player_state, read_warps_from_rom

    # ── Step 1: Exit battle if still in one ──
    if in_battle:
        if fainted:
            result = _battle_turn(emu)
            state = result.get("final_state", "")
            # Blackout — player already healed at a PC
            if result.get("blackout"):
                grind_map, grind_x, grind_y = 0, 0, 0
                # Can't return to grind spot without knowing where we were.
                # The blackout auto-warped us to a PC. This is a special case
                # that the caller handles (stop_reason="fainted" with blackout).
                pass
            if state not in _BATTLE_OVER:
                return {"success": False, "error": f"Failed to exit battle after faint. State: {state}"}
        else:
            max_flee = 5
            for _ in range(max_flee):
                result = _battle_turn(emu, run=True)
                state = result.get("final_state", "")
                if state in _BATTLE_OVER:
                    break
                if state in _FAINT:
                    result2 = _battle_turn(emu)
                    state2 = result2.get("final_state", "")
                    if state2 not in _BATTLE_OVER:
                        return {"success": False, "error": f"Fainted while fleeing and couldn't exit. State: {state2}"}
                    break
                if state not in ("WAIT_FOR_ACTION", "ACTION"):
                    return {"success": False, "error": f"Unexpected state while fleeing: {state}"}
            else:
                return {"success": False, "error": f"Failed to flee after {max_flee} attempts."}
        emu.advance_frames(120)

    # ── Step 2: Remember grind position ──
    grind_map, grind_x, grind_y, _ = read_player_state(emu)

    # ── Step 3: Exit interior maps if needed ──
    return_warps = None
    exit_result = _exit_to_overworld(emu)
    if exit_result is not None:
        if not exit_result.get("success"):
            return {"success": False, "error": exit_result.get("error", "Failed to exit interior.")}
        return_warps = exit_result.get("return_warps", [])

    # ── Step 4: Find nearest reachable PC ──
    map_id, px, py, _ = read_player_state(emu)
    pc_candidates = _find_all_pcs(emu, map_id, px, py)
    if not pc_candidates:
        return {"success": False, "error": "No Pokemon Center found on the overworld matrix."}

    # Save state before navigation attempts so we can retry with different cities
    retry_checkpoint = emu.create_checkpoint(action="auto_grind:auto_heal_pre_navigate")
    retry_cp_id = retry_checkpoint.get("checkpoint_id", "")

    # Try each candidate by distance until one is reachable
    nav = None
    pc_info = None
    for i, candidate in enumerate(pc_candidates):
        if candidate["chunk_dist"] <= 3:
            nav = _navigate_to(emu, candidate["pc_warp_x"], candidate["pc_warp_y"], flee_encounters=True)
        else:
            nav = _navigate_multi_hop(emu, candidate["pc_warp_x"], candidate["pc_warp_y"])

        if nav.get("encounter") and nav["encounter"].get("dialogue"):
            return {"success": False, "error": f"Trainer battle during navigation to {candidate['city_name']}.", "encounter": nav["encounter"]}

        if not nav.get("error"):
            pc_info = candidate
            break

        # Path blocked — revert to pre-navigation state and try next city
        if i < len(pc_candidates) - 1 and retry_cp_id:
            emu.revert_to_checkpoint(retry_cp_id)
            emu.advance_frames(60)

    if pc_info is None:
        tried = ", ".join(c["city_name"] for c in pc_candidates[:5])
        return {"success": False, "error": f"No walkable path to any Pokemon Center. Tried: {tried}."}

    # ── Step 6: Heal at Pokemon Center ──
    # After navigating to the PC warp tile, we should be at or inside the PC.
    # If navigate_to entered the door, we're inside. If not, heal_party handles it.
    heal_result = _heal_party(emu)
    if not heal_result.get("success"):
        return {"success": False, "error": f"Healing failed: {heal_result.get('error', 'unknown')}"}

    # ── Step 7: Exit the Pokemon Center ──
    map_id, _, _, _ = read_player_state(emu)
    warps = read_warps_from_rom(emu, map_id)
    if not warps:
        return {"success": False, "error": "No warps found in Pokemon Center — can't exit."}
    exit_warp = max(warps, key=lambda w: w.get("y", 0))
    nav = _navigate_to(emu, exit_warp["x"], exit_warp["y"])
    if nav.get("error"):
        return {"success": False, "error": f"Failed to exit Pokemon Center: {nav['error']}"}
    emu.advance_frames(120)

    # ── Step 8: Return to grind area ──
    # Re-enter interior if we exited one
    if return_warps:
        ret = _return_to_interior(emu, return_warps)
        if not ret.get("success"):
            return {"success": False, "error": f"Failed to return to interior: {ret.get('error', 'unknown')}"}

    # Navigate back to the grind position
    emu.create_checkpoint(action=f"auto_grind:auto_heal_return(to={grind_x},{grind_y})")
    map_id, px, py, _ = read_player_state(emu)
    chunk_dx = abs(grind_x // 32 - px // 32)
    chunk_dy = abs(grind_y // 32 - py // 32)
    if chunk_dx <= 3 and chunk_dy <= 3:
        nav = _navigate_to(emu, grind_x, grind_y, flee_encounters=True)
    else:
        nav = _navigate_multi_hop(emu, grind_x, grind_y)

    if nav.get("error"):
        return {"success": False, "error": f"Navigation back to grind area failed: {nav['error']}"}
    if nav.get("encounter") and nav["encounter"].get("dialogue"):
        return {"success": False, "error": "Trainer battle during return to grind area.", "encounter": nav["encounter"]}

    return {"success": True}


def _check_effectiveness(battlers: list[dict[str, Any]], move_index: int) -> float | None:
    """Check move type effectiveness against the first alive enemy.

    Returns the multiplier (0.0 = immune, 0.5 = NVE, 1.0 = neutral, 2.0 = SE),
    or None if the check can't be performed (Status move, missing data, etc.).
    """
    from renegade_mcp.type_chart import effectiveness

    player = next((b for b in battlers if b.get("side") == "player"), None)
    if player is None or move_index >= len(player.get("moves", [])):
        return None

    move = player["moves"][move_index]
    mv_type = move.get("type")
    if mv_type is None:
        return None
    if move.get("class") == "Status":
        return None  # Status moves don't use the type chart for damage

    enemy = next(
        (b for b in battlers if b.get("side") == "enemy" and b.get("hp", 0) > 0),
        None,
    )
    if enemy is None:
        return None

    def_type1 = enemy.get("type1")
    def_type2 = enemy.get("type2")
    if def_type1 is None:
        return None
    if def_type2 == def_type1:
        def_type2 = None

    return effectiveness(mv_type, def_type1, def_type2)


def _get_move_pp(battle_turn_result: dict[str, Any], move_index: int) -> int | None:
    """Extract PP for a specific move from battle_turn's battle_state."""
    battlers = battle_turn_result.get("battle_state", [])
    if not battlers:
        return None
    player = battlers[0] if battlers else None
    if not player:
        return None
    moves = player.get("moves", [])
    if move_index < len(moves):
        return moves[move_index].get("pp")
    return None


def _flatten_log(battle_turn_result: dict[str, Any]) -> str:
    """Flatten battle_turn's log entries into a single string for text scanning."""
    entries = battle_turn_result.get("log", [])
    return " / ".join(
        e["text"].replace("\n", " ") for e in entries if isinstance(e, dict) and "text" in e
    )


def _extract_level_from_log(battle_log: list[dict[str, Any]]) -> int | None:
    """Extract the highest 'grew to Lv. N' from a battle's turn logs."""
    level = None
    for turn in battle_log:
        text = turn.get("log", "")
        for m in re.finditer(r"grew to\s*/?\s*Lv\.\s*(\d+)", text):
            level = int(m.group(1))
    return level


def _move_learn_detail(result: dict[str, Any]) -> str:
    """Build a human-readable stop detail for MOVE_LEARN."""
    move_to_learn = result.get("move_to_learn", "unknown")
    current = result.get("current_moves", [])
    def _fmt_move(m: dict) -> str:
        s = f"[{m['slot']}] {m['name']}"
        if "pp" in m:
            s += f" (PP {m['pp']})"
        return s

    current_str = ", ".join(_fmt_move(m) for m in current) if current else "unknown"
    return (
        f"Pokemon wants to learn {move_to_learn}. "
        f"Current moves: {current_str}. "
        "Call auto_grind again with forget_move=0-3 to replace a move, "
        "or forget_move=-1 to skip learning."
    )


def _write_battle_log(battles: list[dict[str, Any]], stop_reason: str) -> str:
    """Write full battle logs to a timestamped file. Returns the file path."""
    log_dir = Path("/workspace/RenegadePlatinumPlaytest/logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"auto_grind_{timestamp}.log"

    lines: list[str] = []
    for i, battle in enumerate(battles):
        lines.append(f"=== Battle {i + 1} ===")
        for turn in battle.get("turns", []):
            lines.append(turn.get("log", ""))
        lines.append("")
    lines.append(f"Stop reason: {stop_reason}")

    log_path.write_text("\n".join(lines))
    return str(log_path)


def _finish(
    stop_reason: str,
    stop_detail: str,
    battles: list[dict[str, Any]],
    party: list[dict[str, Any]],
    move_learn: dict[str, Any] | None = None,
    encounters: list[dict[str, str]] | None = None,
    heal_trips: int = 0,
    fled_ineffective: list[str] | None = None,
) -> dict[str, Any]:
    """Build the final return dict."""
    # Write full logs to file, only return the last battle in response
    log_file = _write_battle_log(battles, stop_reason)

    enc_list = encounters or []

    slot0 = party[0] if party else None

    # Slot 0 summary only — caller can read_party for the full picture
    slot0_summary = None
    if slot0:
        slot0_summary = {
            "name": slot0.get("name", "?"),
            "level": slot0.get("level", "?"),
            "hp": f"{slot0.get('hp', '?')}/{slot0.get('max_hp', '?')}",
        }

    result: dict[str, Any] = {
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "battles_fought": len(battles),
        "encounters": enc_list,
        "slot0": slot0_summary,
        "log_file": log_file,
        "heal_trips": heal_trips,
    }
    if fled_ineffective:
        result["fled_ineffective"] = fled_ineffective
    if move_learn:
        result["move_to_learn"] = move_learn.get("move_to_learn")
        result["current_moves"] = move_learn.get("current_moves")
    return result
