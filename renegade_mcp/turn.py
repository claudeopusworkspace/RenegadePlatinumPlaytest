"""Automated battle turn: action selection + poll + state detection.

Handles all battle states:
- Normal turns: FIGHT + move or POKEMON + switch
- Faint recovery: wild (flee or switch) and trainer (forced switch)
- Trainer switch prompts: swap Pokemon or keep battling
- Level-up, move learning, evolution, battle end detection
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.battle import battle_summary, read_battle
from renegade_mcp.party import read_party
from renegade_mcp.battle_tracker import (
    _tracker,
    _classify_stop,
    _scan_for_new_text,
    _scan_markers,
    POLL_FRAMES,
    SCAN_SIZE,
    SCAN_START,
)

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Battle action screen (bottom screen) ──
FIGHT_XY = (128, 90)
RUN_XY = (128, 170)      # Bottom-center of action screen (blue button)
POKEMON_XY = (210, 170)  # Bottom-right of action screen (green button)

# Double battle target selection screen (bottom screen, after move selection)
# Layout: two enemies on top row, ally/self on bottom.
# Coordinates calibrated from Route 203 double battle.
TARGET_XY = [
    (70, 50),    # 0: top-left enemy (left side of field from player's view)
    (190, 50),   # 1: top-right enemy (right side of field from player's view)
    (100, 130),  # 2: bottom — self or ally
]

# Move selection screen (bottom screen, after tapping FIGHT)
MOVE_XY = [
    (70, 50),    # Move 0 — top-left
    (190, 50),   # Move 1 — top-right
    (70, 110),   # Move 2 — bottom-left
    (190, 110),  # Move 3 — bottom-right
]

# ── Battle party screen (touch targets, 2-column grid) ──
# Layout:  0  1       Row y values estimated from 2-Pokemon test;
#          2  3       rows 1-2 need calibration with 4+ Pokemon.
#          4  5
PARTY_TOUCH_XY = [
    (65, 30),    # Slot 0 — top-left
    (190, 30),   # Slot 1 — top-right
    (65, 80),    # Slot 2 — mid-left
    (190, 80),   # Slot 3 — mid-right
    (65, 130),   # Slot 4 — bottom-left
    (190, 130),  # Slot 5 — bottom-right
]  # Calibrated via gameplay with 5-Pokemon party
SHIFT_XY = (128, 100)  # "SHIFT" confirmation button

# ── Faint/switch prompt buttons (bottom screen) ──
PROMPT_YES_XY = (128, 67)     # "Use next Pokemon" / "Switch Pokemon" (red)
PROMPT_NO_XY = (128, 127)     # "Flee" / "Keep battling" (blue)

# ── Move learn prompt buttons (bottom screen) ──
# Prompt 1: "Make it forget another move?" (appears first in battle flow)
FORGET_A_MOVE_XY = (128, 75)  # "Forget a move!" (red, top)
KEEP_OLD_MOVES_XY = (128, 145)  # "Keep old moves!" (blue, bottom) → goes to Prompt 2
# Prompt 2: "Should this Pokemon give up on learning this new move?"
GIVE_UP_XY = (128, 75)        # "Give up on [Move]!" (red, top)
DONT_GIVE_UP_XY = (128, 145)  # "Don't give up on [Move]!" (green, bottom) → back to Prompt 1
# Move detail view
FORGET_BTN_XY = (128, 178)    # "FORGET" button on move detail view

# Move forget screen grid (shifted down from battle MOVE_XY due to Pokemon info header)
FORGET_MOVE_XY = [
    (70, 75),    # Move 0 — top-left
    (190, 75),   # Move 1 — top-right
    (70, 125),   # Move 2 — bottom-left
    (190, 125),  # Move 3 — bottom-right
]

# Battle struct addresses
BATTLE_BASE = 0x022C5774
BATTLE_SLOT_SIZE = 0xC0
BATTLE_END_FLAG_ADDR = 0x022C5B53  # BattleContext.battleEndFlag — 0 during battle, non-zero when over

# Battle party order: maps UI position → persistent party slot (6 bytes per battler)
# BattleContext.partyOrder[0] — player's order array
PARTY_ORDER_ADDR = 0x022C5B60

# Move-learn identification: which party mon is currently in the learn flow
# BattleContext.levelUpMons (u8 bitmask, one bit per party slot)
LEVEL_UP_MONS_ADDR = 0x022C5B3D
# BattleContext.taskData pointer (non-null when EXP distribution task is active)
TASK_DATA_PTR_ADDR = 0x022C2BAC
# Offsets within heap-allocated BattleScriptTaskData.tmpData[]
TASK_DATA_MOVE_OFF = 0x40      # tmpData[4] = GET_EXP_MOVE (move ID being learned)
TASK_DATA_SLOT_OFF = 0x48      # tmpData[6] = GET_EXP_PARTY_SLOT (lower bound search index)

# Post-timeout recovery: press B to advance through stat screens / text
RECOVERY_PRESSES = 8
RECOVERY_WAIT = 300  # frames between B presses (~5 seconds per press)

# Evolution animation handling
EVOLUTION_ADVANCE = 60      # ~1 second per poll chunk
EVOLUTION_MAX_CHUNKS = 40   # 40 seconds max wait for animation

# Timing
ACTION_SETTLE = 120   # frames before first tap (covers send-out animations)
PROMPT_SETTLE = 300   # frames before tapping switch/faint prompts (game delays control handoff)
TAP_WAIT = 60         # frames between sequential taps
DPAD_WAIT = 30        # frames between D-pad presses
ACTION_PROMPT_MAX_POLLS = 120  # polls waiting for "What will X do?" (~30 sec)
TEXT_ADVANCE_WAIT = 120  # frames between B presses during text advancement


# ── Helpers ──

def _is_battle_over(emu: EmulatorClient) -> bool:
    """Check if the battle has ended.

    Two-tier check:
    1. BattleContext.battleEndFlag — set by the engine when the battle
       result is determined. This is the authoritative signal, but it
       may not be set yet during level-up/evolution processing.
    2. Battle struct garbage detection — if the battle struct contains
       garbage data, we've transitioned to the overworld. Catches the
       case where the flag hasn't been set but the struct is invalid.

    Together these cover both "battle just ended" (flag) and "overworld
    loaded" (garbage) reliably, without false positives during doubles
    exp cascades where the struct is still valid and flag is still 0.
    """
    flag = emu.read_memory(BATTLE_END_FLAG_ADDR, size="byte")
    if flag != 0:
        return True

    # Fallback: garbage-data check on battle slot 0
    raw = emu.read_memory_range(BATTLE_BASE, size="byte", count=BATTLE_SLOT_SIZE)
    data = bytes(raw)
    species = struct.unpack_from("<H", data, 0x00)[0]
    level = data[0x34]
    max_hp = struct.unpack_from("<H", data, 0x50)[0]
    cur_hp = struct.unpack_from("<H", data, 0x4C)[0]

    if species == 0 or species > 493:
        return True
    if level == 0 or level > 100:
        return True
    if max_hp == 0 or max_hp > 999:
        return True
    if cur_hp > max_hp:
        return True
    return False


def _get_player_hp(emu: EmulatorClient) -> int:
    """Read player's current HP from battle struct slot 0."""
    raw = emu.read_memory_range(BATTLE_BASE + 0x4C, size="long", count=1)
    return raw[0] if raw else -1


def _log_has(log: list[dict], text: str) -> bool:
    """Check if any log entry contains the given text."""
    return any(text in e.get("text", "") for e in log)


def _classify_prompt(text: str) -> str:
    """Classify a WAIT_FOR_ACTION prompt by its text content."""
    t = text.replace("\n", " ")
    if "Use next" in t:
        return "FAINT_SWITCH"
    if "Will you switch" in t:
        return "SWITCH_PROMPT"
    if "give up on" in t or "forget another move" in t or "Should a move be deleted" in t:
        return "MOVE_LEARN"
    return "ACTION"


def _handle_evolution_what(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any] | None:
    """Detect if WAIT_FOR_ACTION is actually the evolution 'What?' prompt.

    In Gen 4, evolution shows 'What?' with the WAIT_FOR_ACTION control code
    before the 'is evolving!' text.  If detected, press B to advance past
    'What?' and hand off to _wait_for_evolution.

    Returns updated result if evolution was handled, None otherwise.
    """
    log = result.get("log", [])
    if not _log_has(log, "grew to"):
        return None
    for entry in reversed(log):
        if entry.get("stop") == "WAIT_FOR_ACTION":
            text = entry.get("text", "").replace("\n", " ")
            if text.strip().startswith("What?"):
                emu.press_buttons(["b"], frames=8)
                emu.advance_frames(60)
                if _is_evolution_text_on_screen(emu):
                    return _wait_for_evolution(emu, result)
            break
    return None


def _scan_move_name_from_memory(emu: EmulatorClient) -> str | None:
    """Scan the full text region for a standalone move name marker.

    During move-learn prompts, the game writes the new move name as a
    standalone text marker (D2EC header + move name + END).  This marker
    lives in a different memory region (~0x02301XXX) than the battle
    narration text (~0x0229XXXX), so the narrow poll window never sees it.

    Doing a full-region scan and matching against known move names is the
    most reliable way to extract the pending move.
    """
    from renegade_mcp.data import move_names
    known_moves = set(move_names().values())

    raw_bytes = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
    if not raw_bytes:
        return None

    data = bytes(raw_bytes)
    results = _scan_for_new_text(data, SCAN_START, {})

    for _, text, _, _ in results:
        if text.strip() in known_moves:
            return text.strip()
    return None


def _advance_text(emu: EmulatorClient, presses: int = 1, wait: int = TEXT_ADVANCE_WAIT) -> None:
    """Press B to advance through dialogue text."""
    for _ in range(presses):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(wait)


def _is_evolution_text_on_screen(emu: EmulatorClient) -> bool:
    """Check if evolution text is currently displayed (e.g. 'is evolving!')."""
    raw = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
    data = bytes(raw)
    markers = _scan_markers(data, SCAN_START)
    for text in markers.values():
        if "is evolving" in text.replace("\n", " "):
            return True
    return False


def _wait_for_evolution(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any]:
    """Wait for evolution animation to complete without pressing B.

    Gen 4 evolution: 'is evolving!' text → ~10-15s animation → 'evolved into [Species]!'
    Pressing B during the animation cancels it. This function dismisses the
    evolution text (single B), then waits passively for completion.
    """
    # Dismiss "is evolving" text if still on screen
    if _is_evolution_text_on_screen(emu):
        # Capture the actual text for the log
        raw = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
        markers = _scan_markers(bytes(raw), SCAN_START)
        for text in markers.values():
            if "is evolving" in text.replace("\n", " "):
                result["log"].append({"text": text, "stop": "AUTO_ADVANCE"})
                break
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(60)

    # Wait passively for the animation to complete.
    # Scan periodically for "evolved into" text (appears after animation).
    for _ in range(EVOLUTION_MAX_CHUNKS):
        emu.advance_frames(EVOLUTION_ADVANCE)

        raw = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
        markers = _scan_markers(bytes(raw), SCAN_START)

        for text in markers.values():
            clean = text.replace("\n", " ")
            if "evolved into" in clean:
                result["log"].append({"text": text, "stop": "AUTO_ADVANCE"})
                # Press B through post-evolution text.  Check for the
                # move-learn prompt by TEXT CONTENT (not control codes)
                # because post-evolution text uses AUTO_ADVANCE markers
                # even for prompts that need player input.
                # Scan BEFORE pressing B each cycle to avoid accidentally
                # navigating through the YES/NO prompt.
                _advance_text(emu, presses=2, wait=180)
                emu.advance_frames(300)
                for _ in range(RECOVERY_PRESSES):
                    raw2 = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
                    if raw2:
                        markers2 = _scan_markers(bytes(raw2), SCAN_START)
                        for t2 in markers2.values():
                            if "Should a move be deleted" in t2.replace("\n", " "):
                                result["final_state"] = "MOVE_LEARN"
                                return result
                    emu.press_buttons(["b"], frames=8)
                    emu.advance_frames(180)
                result["final_state"] = "BATTLE_ENDED" if _is_battle_over(emu) else "TIMEOUT"
                return result

            if "stopped evolving" in clean:
                result["log"].append({"text": text, "stop": "AUTO_ADVANCE"})
                emu.advance_frames(300)
                result["final_state"] = "BATTLE_ENDED" if _is_battle_over(emu) else "TIMEOUT"
                return result

    # Timed out waiting — check if we ended up in overworld
    result["final_state"] = "BATTLE_ENDED" if _is_battle_over(emu) else "TIMEOUT"
    return result


# ── Double battle helpers ──

def _is_double_battle(emu: EmulatorClient) -> bool:
    """Check if current battle has 2 active Pokemon on the player's side."""
    battlers = read_battle(emu)
    player_active = sum(1 for b in battlers if b.get("side") == "player" and b.get("hp", 0) > 0)
    return player_active >= 2


def _alive_enemy_count(emu: EmulatorClient) -> int:
    """Count alive enemies in a double battle."""
    battlers = read_battle(emu)
    return sum(1 for b in battlers if b.get("side") == "enemy" and b.get("hp", 0) > 0)


def _target_flow_with_retry(emu: EmulatorClient, target: int) -> None:
    """Tap a target on the doubles target selection screen, with retry.

    In doubles, enemy positions on the target screen are static — a fainted
    enemy leaves a greyed-out slot that can't be tapped.  The mapping between
    battle struct slots and screen positions varies across battles, so we
    can't reliably predict which position (0=left, 1=right) an enemy is at.

    Strategy: tap the requested target.  If only one enemy is alive, check
    if the tap worked (new text appeared) — if not, retry on the other position.
    """
    idx = target if 0 <= target <= 1 else 0

    emu.advance_frames(count=TAP_WAIT)
    tx, ty = TARGET_XY[idx]
    emu.tap_touch_screen(tx, ty, frames=8)

    # If both enemies are alive, any target is valid — no retry needed
    n_alive = _alive_enemy_count(emu)
    if n_alive >= 2 or target == 2:
        return

    # Only one alive: check if the tap registered by looking for new text
    emu.advance_frames(TAP_WAIT)
    raw = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
    if raw:
        data = bytes(raw)
        markers = _scan_markers(data, SCAN_START)
        # If the action prompt ("What will X do?") is still the dominant text,
        # the target tap didn't work — retry on the other position.
        still_at_prompt = any("What will" in t and "do?" in t for t in markers.values())
        if still_at_prompt:
            other = 1 - idx
            tx2, ty2 = TARGET_XY[other]
            emu.tap_touch_screen(tx2, ty2, frames=8)


def _target_flow(emu: EmulatorClient, target: int) -> None:
    """Tap a target on the doubles target selection screen.

    Called after _fight_flow in double battles. Waits for the target screen
    to appear, then taps the requested position.

    Args:
        target: 0=top-left enemy, 1=top-right enemy, 2=self/ally.
                -1 defaults to 0 (first enemy).
    """
    emu.advance_frames(count=TAP_WAIT)  # Wait for target screen to render
    idx = target if 0 <= target <= 2 else 0
    tx, ty = TARGET_XY[idx]
    emu.tap_touch_screen(tx, ty, frames=8)


# ── Prompt detection ──

def _wait_for_action_prompt(emu: EmulatorClient) -> dict[str, Any]:
    """Wait for a battle prompt that requires player input.

    Detects and classifies the prompt type:
    - ACTION: normal "What will X do?" turn prompt
    - FAINT_SWITCH: wild battle faint, "Use next Pokemon?" (can flee)
    - SWITCH_PROMPT: trainer sending next Pokemon, "Will you switch?"
    - MOVE_LEARN: move learning prompt, "give up on learning?"
    - FAINT_FORCED: trainer battle faint, party grid shown (no text prompt)

    On turns 2+, the prompt is already in the text buffer and returns
    immediately. On turn 1, polls through send-out animations (~30 sec max).
    """
    log: list[dict] = []
    prev_text: str | None = None

    for _ in range(ACTION_PROMPT_MAX_POLLS):
        raw_bytes = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
        if raw_bytes:
            data = bytes(raw_bytes)
            results = _scan_for_new_text(data, SCAN_START, {})

            # Check every active marker for the action prompt stop type.
            # Multiple WAIT_FOR_ACTION texts may coexist (stale "What will X do?"
            # alongside new "Will you switch?" or "Use next Pokemon?").
            # Prefer specific prompts over generic ACTION.
            action_candidates: list[tuple[str, str]] = []
            for _, text, vals, _ in results:
                if _classify_stop(vals) == "WAIT_FOR_ACTION":
                    action_candidates.append((text, _classify_prompt(text)))

            if action_candidates:
                # Return the most specific prompt (non-ACTION first)
                for cand_text, cand_type in action_candidates:
                    if cand_type != "ACTION":
                        if cand_text != prev_text:
                            log.append({"text": cand_text, "stop": "WAIT_FOR_ACTION"})
                        return {"ready": True, "log": log, "prompt_type": cand_type}
                # All ACTION — return the first
                cand_text, cand_type = action_candidates[0]
                if cand_text != prev_text:
                    log.append({"text": cand_text, "stop": "WAIT_FOR_ACTION"})
                return {"ready": True, "log": log, "prompt_type": cand_type}

            # No WAIT_FOR_ACTION marker — check text content for prompts
            # that use different control codes (post-evolution move-learn
            # uses AUTO_ADVANCE despite being a player-input prompt).
            for _, text, vals, _ in results:
                clean = text.replace("\n", " ")
                if "Should a move be deleted" in clean:
                    if text != prev_text:
                        log.append({"text": text, "stop": _classify_stop(vals)})
                    return {"ready": True, "log": log, "prompt_type": "MOVE_LEARN"}

            # No action prompt yet — log the best result and advance
            if results:
                _, text, vals, _ = results[0]
                stop = _classify_stop(vals)

                if text != prev_text:
                    prev_text = text
                    log.append({"text": text, "stop": stop})

                # Dismiss text that waits for B (ability announcements, etc.)
                if stop == "WAIT_FOR_INPUT":
                    emu.press_buttons(["b"], frames=8)
                    emu.advance_frames(30)
                    continue

        emu.advance_frames(POLL_FRAMES)

    # Timed out — check for forced switch (trainer faint, party grid showing)
    if not _is_battle_over(emu) and _get_player_hp(emu) == 0:
        return {"ready": True, "log": log, "prompt_type": "FAINT_FORCED"}

    state = "BATTLE_ENDED" if _is_battle_over(emu) else "NO_ACTION_PROMPT"
    return {"ready": False, "log": log, "state": state}


# ── Action flows ──

def _fight_flow(emu: EmulatorClient, move_index: int) -> None:
    """Tap FIGHT, then tap the selected move."""
    emu.tap_touch_screen(FIGHT_XY[0], FIGHT_XY[1], frames=8)
    emu.advance_frames(TAP_WAIT)

    mx, my = MOVE_XY[move_index]
    emu.tap_touch_screen(mx, my, frames=8)


def _run_flow(emu: EmulatorClient) -> None:
    """Tap RUN on the action screen."""
    emu.tap_touch_screen(RUN_XY[0], RUN_XY[1], frames=8)


def _switch_flow(emu: EmulatorClient, switch_to: int) -> None:
    """Tap POKEMON, tap party slot, tap SHIFT to confirm (normal voluntary switch)."""
    emu.tap_touch_screen(POKEMON_XY[0], POKEMON_XY[1], frames=8)
    emu.advance_frames(ACTION_SETTLE)

    px, py = PARTY_TOUCH_XY[switch_to]
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    emu.tap_touch_screen(SHIFT_XY[0], SHIFT_XY[1], frames=8)


def _prompt_switch_flow(emu: EmulatorClient, switch_to: int) -> None:
    """Handle 'Use next Pokemon?' or 'Switch Pokemon?' — tap yes, select, SHIFT."""
    # Tap the "yes" button (Use next Pokemon / Switch Pokemon)
    emu.tap_touch_screen(PROMPT_YES_XY[0], PROMPT_YES_XY[1], frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # Tap party slot → opens detail view
    px, py = PARTY_TOUCH_XY[switch_to]
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # Tap SHIFT to confirm
    emu.tap_touch_screen(SHIFT_XY[0], SHIFT_XY[1], frames=8)


def _forced_switch_flow(emu: EmulatorClient, switch_to: int) -> None:
    """Handle trainer faint — already on party grid, select and SHIFT."""
    px, py = PARTY_TOUCH_XY[switch_to]
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    emu.tap_touch_screen(SHIFT_XY[0], SHIFT_XY[1], frames=8)


def _decline_flow(emu: EmulatorClient) -> None:
    """Tap 'Flee' (wild faint) or 'Keep battling' (switch prompt)."""
    emu.tap_touch_screen(PROMPT_NO_XY[0], PROMPT_NO_XY[1], frames=8)


def _skip_move_learn_flow(emu: EmulatorClient) -> bool:
    """Skip learning the new move from Prompt 1 ('Make it forget another move?').

    Flow: 'Keep old moves!' → Prompt 2 text scroll → 'Give up on [Move]!' → confirmation text.

    Returns True if evolution text was detected (caller must handle via _wait_for_evolution).
    """
    # Prompt 1: tap "Keep old moves!" (bottom) → triggers Prompt 2 text
    emu.tap_touch_screen(KEEP_OLD_MOVES_XY[0], KEEP_OLD_MOVES_XY[1], frames=8)
    # Prompt 2 text scrolls for ~600 frames; B presses speed it up
    _advance_text(emu, presses=2, wait=120)
    emu.advance_frames(300)  # Wait for touch buttons to appear

    # Prompt 2: tap "Give up on [Move]!" (top)
    emu.tap_touch_screen(GIVE_UP_XY[0], GIVE_UP_XY[1], frames=8)
    emu.advance_frames(TAP_WAIT)

    # Advance through "did not learn [Move]" text, stopping if evolution starts
    for _ in range(3):
        if _is_evolution_text_on_screen(emu):
            return True
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(180)
    return _is_evolution_text_on_screen(emu)


def _learn_move_flow(emu: EmulatorClient, forget_index: int) -> bool:
    """Forget a move and learn the new one from Prompt 1 ('Make it forget another move?').

    Steps: 'Forget a move!' → move grid (no B!) → tap slot → FORGET → confirmation text.

    Returns True if evolution text was detected (caller must handle via _wait_for_evolution).
    """
    # 1. Tap "Forget a move!" (red, top) on Prompt 1
    emu.tap_touch_screen(FORGET_A_MOVE_XY[0], FORGET_A_MOVE_XY[1], frames=8)
    emu.advance_frames(300)  # Wait for move grid to render (do NOT press B — it exits the screen)

    # 2. Tap the target move slot on the grid
    mx, my = FORGET_MOVE_XY[forget_index]
    emu.tap_touch_screen(mx, my, frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # 3. Tap FORGET on the detail view
    emu.tap_touch_screen(FORGET_BTN_XY[0], FORGET_BTN_XY[1], frames=8)
    emu.advance_frames(ACTION_SETTLE)

    # 4. Advance through "1, 2, and... Poof!" / "forgot [old]" / "learned [new]" text
    #    Stop pressing B if evolution text appears to avoid cancelling it.
    for _ in range(6):
        if _is_evolution_text_on_screen(emu):
            return True
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(180)
    return _is_evolution_text_on_screen(emu)


def _skip_move_learn_overworld(emu: EmulatorClient) -> None:
    """Skip learning in post-evolution UI (top-screen YES/NO with D-pad).

    Flow: 'Should a move be deleted?' → NO → 'Stop trying to teach [Move]?' → YES
          → '[Pokemon] did not learn [Move].' → dismiss.
    """
    # "Should a move be deleted?" → select NO
    emu.press_buttons(["down"], frames=8)
    emu.advance_frames(DPAD_WAIT)
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(PROMPT_SETTLE)
    # "Stop trying to teach [Move]?" → select YES
    emu.press_buttons(["up"], frames=8)
    emu.advance_frames(DPAD_WAIT)
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(PROMPT_SETTLE)
    # "[Pokemon] did not learn [Move]." → dismiss
    emu.press_buttons(["b"], frames=8)
    emu.advance_frames(PROMPT_SETTLE)


def _learn_move_overworld(emu: EmulatorClient, forget_index: int) -> None:
    """Learn a move in post-evolution UI (top-screen YES/NO + move list).

    Flow: 'Should a move be deleted?' → YES → move list (D-pad) → select move
          → confirmation text.
    """
    # "Should a move be deleted?" → select YES (cursor defaults to YES)
    emu.press_buttons(["up"], frames=8)
    emu.advance_frames(DPAD_WAIT)
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(PROMPT_SETTLE)
    # Navigate to the move to forget (list starts at move 0)
    for _ in range(forget_index):
        emu.press_buttons(["down"], frames=8)
        emu.advance_frames(DPAD_WAIT)
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(PROMPT_SETTLE)
    # Advance through confirmation text ("1, 2, and... Poof!" / learned)
    _advance_text(emu, presses=5, wait=180)


def _poll_after_action(emu: EmulatorClient, prompt_log: list[dict]) -> dict[str, Any]:
    """Re-init tracker and poll for the next battle state after an action."""
    _tracker.init(emu)
    result = _tracker.poll(emu, auto_press=True)
    # Classify on poll-only log first (avoids stale prompt text contamination)
    result["final_state"] = _classify_final_state(emu, result)

    # If NO_TEXT but still in battle, the action prompt may already be on screen
    # (captured in baseline). Fall back to a fresh prompt scan.
    if result["final_state"] == "NO_TEXT" and not _is_battle_over(emu):
        prompt = _wait_for_action_prompt(emu)
        if prompt["ready"]:
            result["log"].extend(prompt["log"])
            result["final_state"] = prompt["prompt_type"]

    # Level-up recovery: another Pokemon (e.g. Exp Share holder) may level up
    # after a move-learn, switch, or faint flow. The "grew to" text may have
    # scrolled by during the preceding flow's B presses (before the tracker was
    # re-initialized), so the poll log won't contain it. If we timed out and the
    # battle isn't over, try recovery regardless — pressing B through a stat
    # screen is safe even if it's not a level-up.
    if result["final_state"] == "TIMEOUT" and not _is_battle_over(emu):
        result = _recover_from_level_up(emu, result)

    # Then prepend prompt log for complete display
    result["log"] = prompt_log + result.get("log", [])
    return result


# ── Main entry point ──

def battle_turn(
    emu: EmulatorClient, move_index: int = -1, switch_to: int = -1,
    forget_move: int = -2, target: int = -1, run: bool = False,
) -> dict[str, Any]:
    """Execute a battle action: move, switch, run, flee, keep battling, or handle move learning.

    The tool detects the current game state and validates parameters:

    Normal turn (ACTION — "What will X do?"):
        move_index (0-3): Use FIGHT and select a move.
        switch_to (1-5): Use POKEMON to switch voluntarily.
        run=True: Attempt to flee (wild battles only). Returns BATTLE_ENDED on
            success, WAIT_FOR_ACTION on failure (enemy gets a free turn).
        target (doubles only): 0=left enemy, 1=right enemy, 2=self/ally. -1=auto (first enemy).

    Faint in wild battle (FAINT_SWITCH — "Use next Pokemon?"):
        switch_to (1-5): Send in a replacement.
        No args / switch_to=-1: Flee the battle.

    Faint in trainer battle (FAINT_FORCED — party grid shown):
        switch_to (1-5): Send in a replacement (required).

    Trainer switch prompt (SWITCH_PROMPT — "Will you switch?"):
        switch_to (1-5): Switch to a different Pokemon.
        No args / switch_to=-1: Keep battling with current Pokemon.

    Move learning (MOVE_LEARN — "give up on learning?"):
        forget_move (0-3): Forget that move slot and learn the new move.
        forget_move=-1: Skip learning the new move.
        No forget_move: Return MOVE_LEARN state with move info for decision.

    In double battles, returns WAIT_FOR_PARTNER_ACTION after the first Pokemon's
    action — call battle_turn again for the second Pokemon. After both actions are
    submitted, the turn executes and polling returns the result as normal.

    Returns dict with: log, final_state, battle_state (trimmed summary).
    """
    has_move = move_index >= 0
    has_switch = switch_to >= 0
    has_forget = forget_move >= -1  # -1 = skip, 0-3 = forget slot

    # 1. Detect current game state
    prompt = _wait_for_action_prompt(emu)

    if not prompt["ready"]:
        result: dict[str, Any] = {
            "log": prompt["log"],
            "final_state": prompt.get("state", "NO_ACTION_PROMPT"),
        }
        result["battle_state"] = battle_summary(read_battle(emu))
        return result

    pt = prompt["prompt_type"]

    # 2. Validate parameters for current state
    if pt == "ACTION":
        if has_forget:
            return {"error": "Not at a move learning prompt. Use move_index or switch_to."}
        if run:
            if has_move or has_switch:
                return {"error": "Specify run=True alone — cannot combine with move_index or switch_to."}
        elif has_move and has_switch:
            return {"error": "Specify move_index OR switch_to, not both."}
        elif not has_move and not has_switch:
            return {"error": "Must specify move_index (0-3), switch_to (1-5), or run=True."}
        if has_move and move_index > 3:
            return {"error": f"move_index must be 0-3, got {move_index}"}
        if has_switch and switch_to == 0:
            return {"error": "switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."}
        if has_switch and switch_to > 5:
            return {"error": f"switch_to must be 1-5, got {switch_to}"}
    elif pt in ("FAINT_SWITCH", "SWITCH_PROMPT"):
        if has_forget:
            return {"error": f"Not at a move learning prompt. Currently in {pt} state."}
        if has_move:
            return {"error": f"Can't use a move in {pt} state. Use switch_to (1-5), or omit to {'flee' if pt == 'FAINT_SWITCH' else 'keep battling'}."}
        if has_switch and switch_to == 0:
            return {"error": "switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."}
        if has_switch and switch_to > 5:
            return {"error": f"switch_to must be 1-5, got {switch_to}"}
    elif pt == "FAINT_FORCED":
        if has_forget:
            return {"error": "Not at a move learning prompt. Your Pokemon fainted — use switch_to."}
        if has_move:
            return {"error": "Can't use a move — your Pokemon fainted. Use switch_to (1-5) to send a replacement."}
        if not has_switch:
            return {"error": "Must switch in a trainer battle — specify switch_to (1-5)."}
        if has_switch and switch_to == 0:
            return {"error": "switch_to=0 is the active battler. Use 1-5 to switch to a different Pokemon."}
        if switch_to > 5:
            return {"error": f"switch_to must be 1-5, got {switch_to}"}
    elif pt == "MOVE_LEARN":
        if has_move or has_switch:
            return {"error": "At move learning prompt. Use forget_move (0-3) to forget a move, or forget_move=-1 to skip."}
        if has_forget and forget_move > 3:
            return {"error": f"forget_move must be -1 (skip) or 0-3, got {forget_move}"}

    # 3. Execute the appropriate flow
    if pt == "ACTION" and run:
        result = _execute_run(emu, prompt)
    elif pt == "ACTION":
        result = _execute_action(emu, prompt, move_index, switch_to, has_move, target)
    elif pt == "FAINT_SWITCH":
        result = _execute_faint_switch(emu, prompt, switch_to, has_switch)
    elif pt == "FAINT_FORCED":
        result = _execute_forced_switch(emu, prompt, switch_to)
    elif pt == "SWITCH_PROMPT":
        result = _execute_switch_prompt(emu, prompt, switch_to, has_switch)
    elif pt == "MOVE_LEARN":
        result = _execute_move_learn(emu, prompt, forget_move, has_forget)
    else:
        result = {"log": prompt["log"], "final_state": "NO_ACTION_PROMPT"}

    # 4. Enrich MOVE_LEARN results with move info
    if result["final_state"] == "MOVE_LEARN":
        _enrich_move_learn_result(result, emu)

    # 4.5. Add party order for switch states
    if result["final_state"] in ("SWITCH_PROMPT", "FAINT_SWITCH", "FAINT_FORCED"):
        _enrich_switch_result(result, emu)

    # 5. Auto-advance post-battle overworld dialogue (trainer defeat text, story triggers)
    if result["final_state"] in ("BATTLE_ENDED", "TIMEOUT"):
        from renegade_mcp.battle import read_battle as _rb
        if not _rb(emu):
            # We're in the overworld — check for pending dialogue
            emu.advance_frames(180)  # wait for overworld to settle
            from renegade_mcp.dialogue import advance_dialogue
            adv = advance_dialogue(emu)
            if adv["status"] != "no_dialogue" and adv.get("conversation"):
                result["post_battle_dialogue"] = adv["conversation"]
                if result["final_state"] == "TIMEOUT":
                    result["final_state"] = "BATTLE_ENDED"

    # 6. Append trimmed battle state
    result["battle_state"] = battle_summary(read_battle(emu))
    return result


# ── State-specific execution ──

def _execute_run(emu: EmulatorClient, prompt: dict) -> dict[str, Any]:
    """Attempt to flee: tap RUN, poll for result.

    Success → "Got away safely!" → BATTLE_ENDED.
    Failure → "Can't escape!" → enemy turn → WAIT_FOR_ACTION (or faint states).
    """
    _tracker.init(emu)
    emu.advance_frames(ACTION_SETTLE)
    _run_flow(emu)
    return _poll_after_action(emu, prompt["log"])


def _execute_action(
    emu: EmulatorClient, prompt: dict, move_index: int, switch_to: int,
    has_move: bool, target: int = -1,
) -> dict[str, Any]:
    """Normal turn: FIGHT + move (+ target in doubles) or POKEMON + switch."""
    _tracker.init(emu)
    emu.advance_frames(ACTION_SETTLE)

    is_double = _is_double_battle(emu)

    if has_move:
        _fight_flow(emu, move_index)
        if is_double:
            _target_flow_with_retry(emu, target)
    else:
        _switch_flow(emu, switch_to)

    result = _tracker.poll(emu, auto_press=True)
    # Classify on poll-only log (avoids stale prompt text contamination)
    result["final_state"] = _classify_final_state(emu, result)
    result["log"] = prompt["log"] + result.get("log", [])

    # In doubles, after first action the partner's prompt appears immediately
    # (no battle narration in between).  The poll often returns TIMEOUT or
    # NO_TEXT because no battle narration occurs — only the partner's prompt
    # text appears.  Detect this and try to find the partner's action prompt.
    if is_double and result["final_state"] in ("WAIT_FOR_ACTION", "TIMEOUT", "NO_TEXT"):
        poll_entries = [e for e in result.get("log", []) if e not in prompt["log"]]
        has_narration = any("used" in e.get("text", "") for e in poll_entries)

        if result["final_state"] in ("TIMEOUT", "NO_TEXT") and not _is_battle_over(emu):
            # Poll missed the partner prompt — do a fresh scan
            prompt2 = _wait_for_action_prompt(emu)
            if prompt2["ready"]:
                result["log"].extend(prompt2["log"])
                result["final_state"] = prompt2["prompt_type"]
                # Re-check for narration to classify correctly
                poll_entries = [e for e in result.get("log", []) if e not in prompt["log"]]
                has_narration = any("used" in e.get("text", "") for e in poll_entries)

        # "ACTION" is _classify_prompt's name for a normal action prompt;
        # "WAIT_FOR_ACTION" is the tracker's raw name. Both mean the same thing.
        if result["final_state"] in ("WAIT_FOR_ACTION", "ACTION") and not has_narration:
            result["final_state"] = "WAIT_FOR_PARTNER_ACTION"

    # Evolution "What?" detection: appears as WAIT_FOR_ACTION after level-up
    if result["final_state"] in ("WAIT_FOR_ACTION", "ACTION"):
        evo = _handle_evolution_what(emu, result)
        if evo is not None:
            result = evo

    # NO_TEXT / TIMEOUT recovery for non-doubles (doubles handled above)
    if result["final_state"] in ("NO_TEXT", "TIMEOUT") and not _is_battle_over(emu):
        if result["final_state"] == "NO_TEXT":
            # Fresh scan for any prompt the tracker missed
            prompt2 = _wait_for_action_prompt(emu)
            if prompt2["ready"]:
                result["log"].extend(prompt2["log"])
                result["final_state"] = prompt2["prompt_type"]
        if result["final_state"] == "TIMEOUT":
            result = _recover_from_level_up(emu, result)

    # After level-up recovery or BATTLE_ENDED, check for evolution
    if result["final_state"] == "BATTLE_ENDED":
        emu.advance_frames(120)
        if _is_evolution_text_on_screen(emu):
            result = _wait_for_evolution(emu, result)
        else:
            raw_scan = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
            if raw_scan:
                for t_scan in _scan_markers(bytes(raw_scan), SCAN_START).values():
                    if t_scan.strip().startswith("What?"):
                        emu.press_buttons(["b"], frames=8)
                        emu.advance_frames(60)
                        if _is_evolution_text_on_screen(emu):
                            result = _wait_for_evolution(emu, result)
                        break

    return result


def _execute_faint_switch(
    emu: EmulatorClient, prompt: dict, switch_to: int, has_switch: bool,
) -> dict[str, Any]:
    """Wild faint: send replacement or flee."""
    emu.advance_frames(PROMPT_SETTLE)
    if has_switch:
        _prompt_switch_flow(emu, switch_to)
        return _poll_after_action(emu, prompt["log"])
    else:
        # Flee
        _decline_flow(emu)
        emu.advance_frames(300)  # flee animation
        result: dict[str, Any] = {"log": prompt["log"]}
        if _is_battle_over(emu):
            result["final_state"] = "BATTLE_ENDED"
        else:
            # Flee might need more time or might have failed
            emu.advance_frames(300)
            result["final_state"] = "BATTLE_ENDED" if _is_battle_over(emu) else "WAIT_FOR_ACTION"
        return result


def _execute_forced_switch(
    emu: EmulatorClient, prompt: dict, switch_to: int,
) -> dict[str, Any]:
    """Trainer faint: must send replacement."""
    emu.advance_frames(PROMPT_SETTLE)
    _forced_switch_flow(emu, switch_to)
    return _poll_after_action(emu, prompt["log"])


def _execute_switch_prompt(
    emu: EmulatorClient, prompt: dict, switch_to: int, has_switch: bool,
) -> dict[str, Any]:
    """Trainer switch prompt: swap Pokemon or keep battling."""
    emu.advance_frames(PROMPT_SETTLE)
    if has_switch:
        _prompt_switch_flow(emu, switch_to)
    else:
        _decline_flow(emu)
    return _poll_after_action(emu, prompt["log"])


def _execute_move_learn(
    emu: EmulatorClient, prompt: dict, forget_move: int, has_forget: bool,
) -> dict[str, Any]:
    """Handle move learning prompt: skip, learn, or return info for decision."""
    if not has_forget:
        # No decision yet — return MOVE_LEARN state for the caller to decide
        return {"log": prompt["log"], "final_state": "MOVE_LEARN"}

    # Detect post-evolution overworld UI (top-screen YES/NO) vs mid-battle
    # (bottom-screen touch buttons).  The overworld prompt says
    # "Should a move be deleted?" instead of "forget another move".
    is_overworld = any(
        "Should a move be deleted" in e.get("text", "").replace("\n", " ")
        for e in prompt.get("log", [])
    )

    if is_overworld:
        if forget_move == -1:
            _skip_move_learn_overworld(emu)
        else:
            _learn_move_overworld(emu, forget_move)
        return _poll_after_action(emu, prompt["log"])

    if forget_move == -1:
        evolving = _skip_move_learn_flow(emu)
    else:
        evolving = _learn_move_flow(emu, forget_move)

    if evolving:
        result: dict[str, Any] = {"log": prompt["log"]}
        return _wait_for_evolution(emu, result)

    return _poll_after_action(emu, prompt["log"])


# ── Post-action processing ──

def _recover_from_level_up(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any]:
    """After level-up causes a timeout, press B to advance through stat screens."""
    for _ in range(RECOVERY_PRESSES):
        # Init baseline BEFORE dismissing, so text that appears after B
        # (like "learned Quick Attack!") is detected as new by the poll.
        _tracker.init(emu)

        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(RECOVERY_WAIT)

        # Check for evolution text BEFORE polling — the poll's auto_press
        # would dismiss it with B and subsequent B presses would cancel
        # the evolution animation.
        if _is_evolution_text_on_screen(emu):
            return _wait_for_evolution(emu, result)

        poll = _tracker.poll(emu, auto_press=True)

        if poll["final_state"] == "WAIT_FOR_ACTION":
            result["log"].extend(poll.get("log", []))
            # Check for evolution "What?" before classifying
            evo = _handle_evolution_what(emu, result)
            if evo is not None:
                return evo
            result["final_state"] = _classify_final_state(emu, poll)
            return result

        if poll["final_state"] != "NO_TEXT":
            result["log"].extend(poll.get("log", []))

        if _is_battle_over(emu):
            result["final_state"] = "BATTLE_ENDED"
            return result

    # Exhausted all recovery presses without finding an action prompt.
    # Check battleEndFlag — it's the authoritative signal.
    if _is_battle_over(emu):
        result["final_state"] = "BATTLE_ENDED"
    else:
        result["final_state"] = "LEVEL_UP"
    return result


def _enrich_switch_result(result: dict[str, Any], emu: EmulatorClient) -> None:
    """Add current party order to switch state results for informed slot selection.

    Reads BattleContext.partyOrder[0] to map UI positions to persistent party
    slots.  The ``switch_to`` parameter in ``battle_turn`` taps the bottom-screen
    grid by UI position, so the party list here is ordered to match — slot N in
    the returned list is what ``switch_to=N`` will select.

    Only includes slot index, species, and level — NOT HP, since party HP data
    is stale during battle (doesn't reflect in-battle damage).
    """
    party = read_party(emu)
    party_by_slot = {p["slot"]: p for p in party}

    # Read the 6-byte UI→party mapping from BattleContext.partyOrder[0]
    ui_order = emu.read_memory_range(PARTY_ORDER_ADDR, size="byte", count=6)

    ordered: list[dict[str, Any]] = []
    for ui_pos, party_slot in enumerate(ui_order):
        p = party_by_slot.get(party_slot)
        if p:
            ordered.append({
                "slot": ui_pos,
                "name": p["name"],
                "level": p["level"],
            })
    result["party"] = ordered


def _get_move_learn_info(emu: EmulatorClient) -> tuple[int, int] | None:
    """Identify which party slot is learning a move and which move.

    Reads BattleContext.taskData pointer → tmpData to get the move ID and
    the lower-bound party search index.  Combines with levelUpMons bitmask
    to find the exact party slot currently in the move-learn flow.

    Returns (party_slot, move_id) or None if the EXP task isn't active.
    """
    # Read taskData pointer (non-null when EXP distribution task is active)
    task_ptr = emu.read_memory(TASK_DATA_PTR_ADDR, size="long")
    if not task_ptr:
        return None

    # Dereference: read move ID and party slot lower bound
    move_id = emu.read_memory(task_ptr + TASK_DATA_MOVE_OFF, size="long")
    slot_lower = emu.read_memory(task_ptr + TASK_DATA_SLOT_OFF, size="long")

    # Read levelUpMons bitmask — must be nonzero (at least one mon leveled up)
    level_up_mask = emu.read_memory(LEVEL_UP_MONS_ADDR, size="byte")
    if not level_up_mask:
        return None

    # Validate: move ID must be in range (1-467) and slot in range (0-5)
    if not (1 <= move_id <= 467 and 0 <= slot_lower <= 5):
        return None

    # Find the lowest set bit >= slot_lower — that's the current mon
    for i in range(slot_lower, 6):
        if level_up_mask & (1 << i):
            return (i, move_id)

    # Fallback: if bitmask doesn't match (shouldn't happen), use slot_lower
    return (slot_lower, move_id)


def _enrich_move_learn_result(result: dict[str, Any], emu: EmulatorClient) -> None:
    """Add move_to_learn, current_moves, and learning_pokemon to a MOVE_LEARN result."""
    from renegade_mcp.data import move_names

    info = _get_move_learn_info(emu)
    if info:
        party_slot, move_id = info
        # Look up move name from ROM data
        all_moves = move_names()
        move_name = all_moves.get(move_id)
        if move_name:
            result["move_to_learn"] = move_name

        # Read the learning Pokemon's moves from party data (not battle slot 0)
        party = read_party(emu)
        for p in party:
            if p["slot"] == party_slot:
                result["learning_pokemon"] = {
                    "slot": party_slot,
                    "name": p["name"],
                    "level": p["level"],
                }
                result["current_moves"] = [
                    {"slot": i, "name": mn}
                    for i, mn in enumerate(p.get("move_names", []))
                ]
                break
    else:
        # Fallback: text scan for move name, battle slot 0 for moves
        move_name = _scan_move_name_from_memory(emu)
        if move_name:
            result["move_to_learn"] = move_name
        battlers = read_battle(emu)
        for b in battlers:
            if b.get("side") == "player":
                result["current_moves"] = [
                    {"slot": i, "name": m["name"], "pp": m["pp"]}
                    for i, m in enumerate(b.get("moves", []))
                ]
                break


def _classify_final_state(emu: EmulatorClient, result: dict[str, Any]) -> str:
    """Refine the raw poll state into a more specific battle state."""
    raw_state = result.get("final_state", "")

    if raw_state == "WAIT_FOR_ACTION":
        for entry in result.get("log", []):
            t = entry.get("text", "").replace("\n", " ")
            if "Use next" in t:
                return "FAINT_SWITCH"
            if "Will you switch" in t:
                return "SWITCH_PROMPT"
            if "give up on" in t or "forget another move" in t:
                return "MOVE_LEARN"
        return "WAIT_FOR_ACTION"

    if raw_state in ("TIMEOUT", "NO_TEXT"):
        if _is_battle_over(emu):
            return "BATTLE_ENDED"
        # Trainer faint: no text prompt, player HP = 0, battle still active
        if _log_has(result.get("log", []), "fainted") and _get_player_hp(emu) == 0:
            return "FAINT_FORCED"

    return raw_state


