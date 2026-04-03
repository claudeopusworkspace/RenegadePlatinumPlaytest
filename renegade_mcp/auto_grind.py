"""Auto-grind tool — seek encounters and battle automatically until a stop condition."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

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
        target_level: Stop when slot-0 Pokemon reaches this level. 0 = no limit.
        iterations: Stop after this many wild encounters. 0 = no limit.
        forget_move: If resuming from a MOVE_LEARN stop, pass the choice here
                     (0-3 = forget that slot, -1 = skip learning). -2 = not resuming.
        target_species: Stop when this species appears. Case-insensitive.
                        Empty = no species filter.

    Returns:
        Dict with stop_reason, battles fought, encounters list (species + checkpoint),
        log of each battle, and party state.
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

    # ── If resuming from a MOVE_LEARN, handle that first ──
    if forget_move >= -1:
        emu.create_checkpoint(action=f"auto_grind:resume(forget_move={forget_move})")
        result = _battle_turn(emu, forget_move=forget_move)
        state = result.get("final_state", "")

        if state in _BATTLE_OVER:
            # Move learn resolved, battle ended — check level then continue grinding
            party = _read_party(emu)
            slot0 = party[0] if party else None
            if target_level > 0 and slot0 and slot0["level"] >= target_level:
                return _finish(
                    "target_level",
                    f"Slot 0 reached Lv{slot0['level']} (target: {target_level}).",
                    battles, party,
                )
            # Fall through to the main grind loop
        elif state == "WAIT_FOR_ACTION":
            # Move learn resolved mid-battle — continue this battle
            if fighting:
                stop_reason, stop_detail, battle_log, detected_level = _fight_battle(
                    emu, move_index, result, resuming=True,
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
            slot0 = party[0] if party else None
            if target_level > 0 and slot0 and not slot0.get("partial") and slot0["level"] >= target_level:
                return _finish(
                    "target_level",
                    f"Slot 0 reached Lv{slot0['level']} (target: {target_level}).",
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

        # Check target_species before fighting/running
        if target_species and enemy_species.lower() == target_species.lower():
            stop_reason = "target_species"
            stop_detail = (
                f"Found {enemy_species}! At action prompt — ready to fight or catch."
            )
            break

        # We have a battle — fight or run
        if fighting:
            stop_reason, stop_detail, battle_log, detected_level = _fight_battle(emu, move_index)
        else:
            stop_reason, stop_detail, battle_log, detected_level = _run_battle(emu)
        battles.append({"turns": battle_log})

        if stop_reason:
            break

        # Check iterations limit
        if iterations > 0 and len(battles) >= iterations:
            stop_reason = "iterations"
            stop_detail = f"Completed {iterations} encounter(s) as requested."
            break

        # Battle ended normally — check level from battle log first (immune
        # to encryption-state issues), then fall back to read_party for PP.
        if target_level > 0 and detected_level is not None and detected_level >= target_level:
            stop_reason = "target_level"
            stop_detail = f"Slot 0 reached Lv{detected_level} (target: {target_level})."
            break

        # Fall back to read_party for PP check and level (if log didn't have a level-up)
        party = _read_party(emu)
        slot0 = party[0] if party else None
        if target_level > 0 and slot0 and not slot0.get("partial") and slot0["level"] >= target_level:
            stop_reason = "target_level"
            stop_detail = f"Slot 0 reached Lv{slot0['level']} (target: {target_level})."
            break
        if fighting and slot0 and not slot0.get("partial") and slot0["pp"][move_index] <= 0:
            stop_reason = "pp_depleted"
            stop_detail = (
                f"Move slot {move_index} ({slot0['move_names'][move_index]}) "
                f"has 0 PP. Pokemon is in the overworld — use an Ether or "
                f"swap to a different spam move before continuing."
            )
            break

    # Gather final party state
    party = _read_party(emu)
    result = _finish(stop_reason, stop_detail, battles, party, encounters=encounters)

    # If stopped for target_species, include trimmed battle state for the caller
    if stop_reason == "target_species":
        from renegade_mcp.battle import battle_summary
        result["battle_state"] = battle_summary(_read_battle(emu))

    return result


def _fight_battle(
    emu: EmulatorClient,
    move_index: int,
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

    # If resuming mid-battle, the initial_result is the last battle_turn response
    if resuming and initial_result:
        battle_log.append({"turn": turn, "state": initial_result.get("final_state"), "log": _flatten_log(initial_result)})
        turn += 1

    while True:
        emu.create_checkpoint(action=f"auto_grind:battle_turn(move={move_index}, turn={turn})")
        result = _battle_turn(emu, move_index=move_index)
        state = result.get("final_state", "")
        battle_log.append({"turn": turn, "state": state, "log": _flatten_log(result)})
        turn += 1

        if state in _BATTLE_OVER:
            # Normal end — no stop reason
            return "", "", battle_log, _extract_level_from_log(battle_log)

        if state == "WAIT_FOR_ACTION":
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
    }
    if move_learn:
        result["move_to_learn"] = move_learn.get("move_to_learn")
        result["current_moves"] = move_learn.get("current_moves")
    return result
