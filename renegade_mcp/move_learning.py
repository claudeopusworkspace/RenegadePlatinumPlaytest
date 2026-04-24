"""Move-learning and evolution flows.

Gen 4 move-learn and evolution sequences are tightly coupled:
- `learn_move` / `skip_move_learn` must detect evolution mid-flow and
  stop pressing B so they don't cancel the animation.
- `wait_for_evolution` can emit a MOVE_LEARN final state when a post-
  evolution move-learn prompt appears.
- `clear_overworld_text` must distinguish "next sequential move-learn
  prompt" from "trailing text to dismiss".

Splitting evolution into a separate module would just re-introduce the
same bidirectional dependency. Keeping them together makes the flow
readable.

Callers in `turn.py` import everything here under the legacy `_`-
prefixed names via an alias block. External consumers (tests, use_item,
use_battle_item) keep working unchanged.

Module helpers from turn.py (`_scan_start`, `_is_battle_over`) are
lazy-imported inside function bodies to avoid the top-level import
cycle. `battle_tracker` dependencies (`_scan_markers`, `SCAN_SIZE`) are
safe to import at the top — battle_tracker never imports from here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.battle import read_battle
from renegade_mcp.battle_tracker import (
    _scan_for_new_text,
    _scan_markers,
    SCAN_SIZE,
)
from renegade_mcp.party import read_party

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Move-learn prompt buttons (bottom screen) ──
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

# Offsets within heap-allocated BattleScriptTaskData.tmpData[]
TASK_DATA_MOVE_OFF = 0x40      # tmpData[4] = GET_EXP_MOVE (move ID being learned)
TASK_DATA_SLOT_OFF = 0x48      # tmpData[6] = GET_EXP_PARTY_SLOT (lower bound search index)

# Evolution animation handling
EVOLUTION_ADVANCE = 60      # ~1 second per poll chunk
EVOLUTION_MAX_CHUNKS = 40   # 40 seconds max wait for animation

# Timing
TEXT_ADVANCE_WAIT = 120  # frames between B presses during text advancement

# Mirrors of battle-UI timing constants from turn.py.  Move-learn flows use
# these alongside the shared battle machinery, so duplicating them here (as
# opposed to importing) avoids the turn↔move_learning top-level cycle.  Keep
# in sync with the matching constants in turn.py.
TAP_WAIT = 60            # frames between sequential taps
ACTION_SETTLE = 120      # frames before first tap (covers send-out animations)
PROMPT_SETTLE = 600      # animation-bound waits: post-FORGET animation, overworld Yes/No text pages
DPAD_WAIT = 30           # frames between D-pad presses
RECOVERY_PRESSES = 8     # B-press budget for post-evolution text cleanup


def _advance_text(emu: EmulatorClient, presses: int = 1, wait: int = TEXT_ADVANCE_WAIT) -> None:
    """Press B to advance through dialogue text."""
    for _ in range(presses):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(wait)


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
    from renegade_mcp.turn import _scan_start

    known_moves = set(move_names().values())

    data = emu.read_memory_block(_scan_start(), SCAN_SIZE)
    if not data:
        return None

    results = _scan_for_new_text(data, _scan_start(), {})

    for _, text, _, _ in results:
        if text.strip() in known_moves:
            return text.strip()
    return None


def is_evolution_text_on_screen(emu: EmulatorClient) -> bool:
    """Check whether the post-move-learn flow is about to enter evolution.

    The evolution sequence in Gen 4 is:
        1. "What?"          (WAIT_FOR_ACTION prompt — [FFFE][0200])
        2. "<Pokemon> is evolving!"
        3. animation → "evolved into <Species>!"

    The "What?" prompt appears BEFORE "is evolving!" — if we only match on
    "is evolving" we'll press B right as that text renders, cancelling the
    evolution. Detect both markers so callers can stop pressing B as soon
    as the sequence begins. "What?" is prefixed-only (rather than a contains
    check) to avoid matching unrelated text containing the word.
    """
    from renegade_mcp.turn import _scan_start

    data = emu.read_memory_block(_scan_start(), SCAN_SIZE)
    markers = _scan_markers(data, _scan_start())
    for text in markers.values():
        clean = text.replace("\n", " ").strip()
        if "is evolving" in clean:
            return True
        if clean.startswith("What?"):
            return True
    return False


def wait_for_evolution(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any]:
    """Wait for evolution animation to complete without pressing B.

    Gen 4 evolution: 'is evolving!' text → ~10-15s animation → 'evolved into [Species]!'
    Pressing B during the animation cancels it. This function dismisses the
    evolution text (single B), then waits passively for completion.
    """
    from renegade_mcp.turn import _is_battle_over, _scan_start

    # Dismiss "is evolving" text if still on screen
    if is_evolution_text_on_screen(emu):
        # Capture the actual text for the log
        data = emu.read_memory_block(_scan_start(), SCAN_SIZE)
        markers = _scan_markers(data, _scan_start())
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

        data = emu.read_memory_block(_scan_start(), SCAN_SIZE)
        markers = _scan_markers(data, _scan_start())

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
                    data2 = emu.read_memory_block(_scan_start(), SCAN_SIZE)
                    if data2:
                        markers2 = _scan_markers(data2, _scan_start())
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


def handle_evolution_what(emu: EmulatorClient, result: dict[str, Any]) -> dict[str, Any] | None:
    """Detect if WAIT_FOR_ACTION is actually the evolution 'What?' prompt.

    In Gen 4, evolution shows 'What?' with the WAIT_FOR_ACTION control code
    before the 'is evolving!' text.  If detected, press B to advance past
    'What?' and hand off to wait_for_evolution.

    Returns updated result if evolution was handled, None otherwise.
    """
    from renegade_mcp.turn import _log_has

    log = result.get("log", [])
    if not _log_has(log, "grew to"):
        return None
    for entry in reversed(log):
        if entry.get("stop") == "WAIT_FOR_ACTION":
            text = entry.get("text", "").replace("\n", " ")
            if text.strip().startswith("What?"):
                emu.press_buttons(["b"], frames=8)
                emu.advance_frames(60)
                if is_evolution_text_on_screen(emu):
                    return wait_for_evolution(emu, result)
            break
    return None


def clear_overworld_text(emu: EmulatorClient, prompt_log: list[dict]) -> None:
    """Dismiss lingering overworld text after a post-evolution move learn/skip.

    The move-learn flow produces 4-6 text pages ("1, 2, and... Poof!",
    "forgot X", "And...", "learned Y!").  The fixed 5 B-presses in
    learn_move_overworld sometimes leave the final page on screen,
    especially during sequential learns.  This function checks the
    ScriptManager's is_msg_box_open flag and keeps pressing B until
    all text is dismissed.
    """
    from renegade_mcp.dialogue import _find_script_manager, _read_script_state
    from renegade_mcp.turn import _scan_start

    for _ in range(10):  # safety cap
        emu.advance_frames(60)
        mgr = _find_script_manager(emu)
        if mgr is None:
            break
        ss = _read_script_state(emu, mgr)
        if not ss["is_msg_box_open"]:
            break
        # Check for the next move-learn prompt — don't dismiss it
        data = emu.read_memory_block(_scan_start(), SCAN_SIZE)
        if data:
            markers = _scan_markers(data, _scan_start())
            for t in markers.values():
                if "Should a move be deleted" in t.replace("\n", " "):
                    return  # Next sequential learn prompt — stop clearing
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(180)


def skip_move_learn(emu: EmulatorClient, at_prompt2: bool = False) -> bool:
    """Skip learning the new move.

    When at_prompt2=False (default), starts from Prompt 1 ('Make it forget another move?').
    When at_prompt2=True, starts from Prompt 2 ('Should this Pokemon give up on learning?').

    Flow from Prompt 1: 'Keep old moves!' → Prompt 2 text scroll → 'Give up on [Move]!' → done.
    Flow from Prompt 2: 'Give up on [Move]!' → done.

    Returns True if evolution text was detected (caller must handle via wait_for_evolution).
    """
    if not at_prompt2:
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
        if is_evolution_text_on_screen(emu):
            return True
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(180)
    return is_evolution_text_on_screen(emu)


def learn_move(emu: EmulatorClient, forget_index: int) -> bool:
    """Forget a move and learn the new one from Prompt 1 ('Make it forget another move?').

    Steps: 'Forget a move!' → move grid (no B!) → tap slot → FORGET → confirmation text.

    Returns True if evolution text was detected (caller must handle via wait_for_evolution).
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

    # Wait for the "1, 2, and... Poof!" animation to complete and the game
    # to commit the move replacement before pressing B.  On melonDS the game
    # needs the full animation to process (~600 frames) before the move is
    # actually swapped in memory.
    emu.advance_frames(PROMPT_SETTLE)

    # 4. Advance through "forgot [old]" / "learned [new]" confirmation text.
    #    Stop pressing B if evolution text appears to avoid cancelling it.
    for _ in range(6):
        if is_evolution_text_on_screen(emu):
            return True
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(180)
    return is_evolution_text_on_screen(emu)


def skip_move_learn_overworld(emu: EmulatorClient) -> None:
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


def learn_move_overworld(emu: EmulatorClient, forget_index: int) -> None:
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


def get_move_learn_info(emu: EmulatorClient) -> tuple[int, int] | None:
    """Identify which party slot is learning a move and which move.

    Reads BattleContext.taskData pointer → tmpData to get the move ID being
    learned and the EXP task's lower-bound scan index.

    levelUpMons is a cumulative |= bitmask for the whole battle (decomp:
    battle_script.c line 10090, never cleared after a level-up). When an
    earlier party member leveled up in the same battle, its bit stays set
    even after it's been processed — so "lowest set bit >= slot_lower"
    incorrectly points to the earlier mon (BUG-018 repro: Monferno leveled
    to 31 early, Mothim fainted it, Mothim later hit Lv29 → Poison Powder
    prompt, both bits 0 and 2 set, scan returned 0).

    Fix: cross-reference each candidate slot's species learnset — only the
    mon whose learnset has (current_level, move_id) is actually in the
    move-learn flow. Fall back to the scan heuristic if no learnset match.

    Returns (party_slot, move_id) or None if the EXP task isn't active.
    """
    # Read taskData pointer (non-null when EXP distribution task is active)
    from renegade_mcp.addresses import addr
    from renegade_mcp.data import level_up_moves

    task_ptr = emu.read_memory(addr("TASK_DATA_PTR_ADDR"), size="long")
    if not task_ptr:
        return None

    # Dereference: read move ID and party slot lower bound
    move_id = emu.read_memory(task_ptr + TASK_DATA_MOVE_OFF, size="long")
    slot_lower = emu.read_memory(task_ptr + TASK_DATA_SLOT_OFF, size="long")

    # Read levelUpMons bitmask — must be nonzero (at least one mon leveled up)
    level_up_mask = emu.read_memory(addr("LEVEL_UP_MONS_ADDR"), size="byte")
    if not level_up_mask:
        return None

    # Validate: move ID must be in range (1-467) and slot in range (0-5)
    if not (1 <= move_id <= 467 and 0 <= slot_lower <= 5):
        return None

    # Learnset cross-reference: pick the slot whose species learns *this*
    # move at its *current* level. This disambiguates stale bits that
    # accumulated from earlier level-ups in the same battle.
    party = read_party(emu)
    party_by_slot = {p["slot"]: p for p in party}
    learnset_matches: list[int] = []
    for i in range(6):
        if not (level_up_mask & (1 << i)):
            continue
        mon = party_by_slot.get(i)
        if mon is None:
            continue
        pairs = level_up_moves(mon["species_id"])
        if any(lv == mon["level"] and mid == move_id for lv, mid in pairs):
            learnset_matches.append(i)

    if len(learnset_matches) == 1:
        return (learnset_matches[0], move_id)
    if len(learnset_matches) > 1:
        # Multiple species happen to learn the same move at the same level.
        # Prefer the first match at/after the scan index — that's the slot
        # the EXP task loop is currently visiting.
        for i in learnset_matches:
            if i >= slot_lower:
                return (i, move_id)
        return (learnset_matches[0], move_id)

    # No learnset match (unknown species, ROM data gap, custom movepool).
    # Fall back to the scan heuristic: lowest set bit >= slot_lower.
    for i in range(slot_lower, 6):
        if level_up_mask & (1 << i):
            return (i, move_id)

    # Final fallback: scan from 0 (stale slot_lower).
    for i in range(6):
        if level_up_mask & (1 << i):
            return (i, move_id)

    return (slot_lower, move_id)


def enrich_move_learn_result(result: dict[str, Any], emu: EmulatorClient) -> None:
    """Add move_to_learn, current_moves, and learning_pokemon to a MOVE_LEARN result."""
    from renegade_mcp.data import move_names

    info = get_move_learn_info(emu)
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
