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

    Returns:
        Dict with stop_reason, battles fought, encounters list (species + checkpoint),
        log of each battle, party state, and heal_trips count.
    """
    from renegade_mcp.battle import read_battle as _read_battle
    from renegade_mcp.navigation import seek_encounter as _seek_encounter
    from renegade_mcp.party import read_party as _read_party
    from renegade_mcp.turn import battle_turn as _battle_turn

    fighting = move_index >= 0
    battles: list[dict[str, Any]] = []
    encounters: list[dict[str, str]] = []
    stop_reason = ""
    stop_detail = ""
    heal_enabled = heal_x >= 0 and heal_y >= 0 and grind_x >= 0 and grind_y >= 0
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
