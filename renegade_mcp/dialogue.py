"""Read, decode, and auto-advance dialogue/battle text from emulator RAM.

Scans memory regions for D2EC B6F8 header markers, finds active text slots,
and decodes Gen 4 text encoding.  When advance mode is enabled, uses the
ScriptManager / ScriptContext / TextPrinter state machine (reverse-engineered
from the pret/pokeplatinum decompilation) to automatically press B through
dialogue, collecting the full conversation.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.text_encoding import CHAR_MAP, CTRL_END, CTRL_PAGE_BREAK, CTRL_NEWLINE, decode_char

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# Memory regions: start addresses resolved at runtime, sizes are constant
from renegade_mcp.addresses import OVERWORLD_SCAN_SIZE, BATTLE_SCAN_SIZE, SM_SCAN_SIZE


def _overworld_region() -> tuple[int, int, str]:
    from renegade_mcp.addresses import addr
    return (addr("OVERWORLD_SCAN_START"), OVERWORLD_SCAN_SIZE, "overworld")


def _battle_region() -> tuple[int, int, str]:
    from renegade_mcp.addresses import addr
    return (addr("BATTLE_SCAN_START"), BATTLE_SCAN_SIZE, "battle")

# ── Script engine constants (from pret/pokeplatinum decompilation) ──

# ScriptManager: heap-allocated, found by scanning for magic value.
SM_MAGIC = 0x0003643F
SM_OFF_MSG_ID = 0x05   # u8: active TextPrinter ID (0xFF = none)
SM_OFF_SUB_CTX = 0x07  # u8: 1 if sub-context is active
SM_OFF_MSGBOX = 0x08   # u8: 1 when dialogue box visible
SM_OFF_CTRL_UI = 0x24  # u32: Menu* ctrlUI (non-NULL when Yes/No menu active)
SM_OFF_CTX0 = 0x38     # u32: ScriptContext* ctx[0]
SM_OFF_CTX1 = 0x3C     # u32: ScriptContext* ctx[1]

# ScriptContext state enum
CTX_STOPPED = 0
CTX_RUNNING = 1   # executing commands (animation, movement — don't press buttons)
CTX_WAITING = 2   # paused on a callback

# ScriptContext struct offsets
CTX_OFF_STATE = 0x01   # u8: CTX_STOPPED / CTX_RUNNING / CTX_WAITING
CTX_OFF_SHOULD_RESUME = 0x04  # u32: ShouldResumeScriptFunc (callback ptr)

# TextPrinter struct — resolved at runtime via addr("TP_BASE")
TP_OFF_ACTIVE = 0x27   # u8: 1 while printer is running
TP_OFF_STATE = 0x28    # u8: 0=HANDLE_CHAR, 1=WAIT, 2=CLEAR, 3=START_SCROLL
TP_OFF_CURR_X = 0x0C   # u16: current X draw position (advances as chars render)
TP_OFF_CURR_Y = 0x0E   # u16: current Y draw position (advances on line wrap)

# Timing constants
ADVANCE_HOLD = 8       # frames to hold B button
SETTLE_FRAMES = 30     # frames to wait after B-press for state to update
RENDER_POLL = 15       # frames between polls while text renders
ANIM_POLL = 15         # frames between polls during animation
MAX_ITERATIONS = 200   # max main-loop iterations
MAX_ANIM_POLLS = 200   # max polls waiting for animation to finish
YES_NO_VERIFY_POLLS = 30  # max polls for Yes/No cursor-idle detection (30*15=450 frames)

# Scan range for ScriptManager magic search — start resolved at runtime

# Session-level cache
_script_mgr_addr: int | None = None
_yes_no_resume_addr: int | None = None  # shouldResume callback for WaitForYesNoResult

HEADER_MARKER = b"\xEC\xD2\xF8\xB6"
MAX_TEXT_CHARS = 512


def _find_active_slots(data: bytes, base_addr: int) -> list[tuple]:
    """Find D2EC B6F8 markers with active text. Returns list of (addr, values, known_count)."""
    results = []
    idx = 0

    while True:
        idx = data.find(HEADER_MARKER, idx)
        if idx < 0:
            break

        text_start = idx + 4
        if text_start + 1 >= len(data):
            idx += 2
            continue

        first_val = struct.unpack_from("<H", data, text_start)[0]
        if first_val == CTRL_END:
            idx += 2
            continue

        values = []
        known_count = 0
        pos = text_start

        while pos + 1 < len(data) and len(values) < MAX_TEXT_CHARS:
            val = struct.unpack_from("<H", data, pos)[0]
            values.append(val)
            pos += 2
            if val == CTRL_END:
                break
            if val in CHAR_MAP:
                known_count += 1

        if known_count >= 3:
            results.append((base_addr + text_start, values, known_count))

        idx += 2

    results.sort(key=lambda x: -x[2])
    return results


def _decode_values(values: list[int]) -> list[str]:
    """Decode 16-bit values into text lines."""
    lines = []
    current_line = ""

    for val in values:
        if val == CTRL_END:
            if current_line:
                lines.append(current_line)
                current_line = ""
            break
        elif val == CTRL_PAGE_BREAK:
            if current_line:
                lines.append(current_line)
            lines.append("---")
            current_line = ""
        elif val == CTRL_NEWLINE:
            lines.append(current_line)
            current_line = ""
        else:
            current_line += decode_char(val)

    if current_line:
        lines.append(current_line)

    return lines


def _scan_region(emu: EmulatorClient, region: tuple) -> dict[str, Any] | None:
    """Scan a memory region for active text. Returns result dict or None."""
    start_addr, size, label = region

    raw_bytes = emu.read_memory_range(start_addr, size="byte", count=size)
    if not raw_bytes:
        return None

    data = bytes(raw_bytes)
    slots = _find_active_slots(data, start_addr)

    if not slots:
        return None

    addr, values, _ = slots[0]
    lines = _decode_values(values)

    if not lines or all(not line.strip() or line == "---" for line in lines):
        return None

    return {
        "region": label,
        "address": f"0x{addr:08X}",
        "text": "\n".join(lines),
        "lines": lines,
        "slot_count": len(slots),
    }


def read_dialogue(emu: EmulatorClient, region: str = "auto") -> dict[str, Any]:
    """Read current dialogue or battle text from memory.

    Args:
        region: "auto" (try overworld then battle), "overworld", or "battle".

    Returns dict with text, region, address, and lines.
    """
    if region == "battle":
        result = _scan_region(emu, _battle_region())
    elif region == "overworld":
        result = _scan_region(emu, _overworld_region())
    else:
        result = _scan_region(emu, _overworld_region())
        if result is None:
            result = _scan_region(emu, _battle_region())

    if result is None:
        return {"text": "(no active text)", "region": "none", "lines": [], "slot_count": 0}

    return result


# ── Script engine state readers ──


def _find_script_manager(emu: EmulatorClient) -> int | None:
    """Find the ScriptManager in heap by scanning for its magic value.

    Caches the address for the session.  Re-validates on each call in case
    a save-state load changed the heap layout.
    """
    global _script_mgr_addr

    magic_bytes = struct.pack("<I", SM_MAGIC)

    # Fast path: validate cached address
    if _script_mgr_addr is not None:
        try:
            val = emu.read_memory(_script_mgr_addr, size="long")
            if val == SM_MAGIC:
                return _script_mgr_addr
        except Exception:
            pass
        _script_mgr_addr = None

    # Scan heap region
    from renegade_mcp.addresses import addr as resolve_addr
    sm_scan_start = resolve_addr("SM_SCAN_START")
    raw = emu.read_memory_range(sm_scan_start, size="byte", count=SM_SCAN_SIZE)
    if not raw:
        return None

    data = bytes(raw)
    idx = 0
    while True:
        idx = data.find(magic_bytes, idx)
        if idx < 0:
            return None
        if idx % 4 == 0:  # must be 4-byte aligned
            found_addr = sm_scan_start + idx
            check = emu.read_memory(found_addr + SM_OFF_MSGBOX, size="byte")
            if check in (0, 1):
                _script_mgr_addr = found_addr
                return found_addr
        idx += 4

    return None


def _read_script_state(emu: EmulatorClient, mgr: int) -> dict:
    """Read key ScriptManager fields."""
    raw = emu.read_memory_range(mgr + SM_OFF_MSG_ID, size="byte", count=5)
    # offsets relative to SM_OFF_MSG_ID (0x05):  msg_id, +1=movCount, +2=subCtx, +3=msgBox, +4=numCtx
    ctrl_ui = emu.read_memory(mgr + SM_OFF_CTRL_UI, size="long")
    ctx0 = emu.read_memory(mgr + SM_OFF_CTX0, size="long")
    ctx1 = emu.read_memory(mgr + SM_OFF_CTX1, size="long")
    return {
        "is_msg_box_open": raw[3] == 1,   # SM_OFF_MSGBOX - SM_OFF_MSG_ID = 3
        "message_id": raw[0],
        "sub_ctx_active": raw[2] == 1,     # SM_OFF_SUB_CTX - SM_OFF_MSG_ID = 2
        "has_choice_menu": ctrl_ui != 0,   # Yes/No or similar menu active
        "ctx0_ptr": ctx0,
        "ctx1_ptr": ctx1,
    }


def _read_context_state(emu: EmulatorClient, ctx_ptr: int) -> dict:
    """Read ScriptContext state."""
    state = emu.read_memory(ctx_ptr + CTX_OFF_STATE, size="byte")
    return {"state": state}


def _read_tp_state(emu: EmulatorClient) -> dict:
    """Read TextPrinter active flag and render state."""
    from renegade_mcp.addresses import addr as resolve_addr
    tp_base = resolve_addr("TP_BASE")
    raw = emu.read_memory_range(tp_base + TP_OFF_ACTIVE, size="byte", count=2)
    return {"active": raw[0] == 1, "state": raw[1]}


def advance_dialogue(emu: EmulatorClient) -> dict[str, Any]:
    """Auto-advance through overworld dialogue, collecting all text.

    Finds the ScriptManager in heap, reads the dialogue state machine, and
    presses B to advance through pages.  Stops at dialogue end, Yes/No
    prompts, or unknown states.

    Returns a dict with:
        status: "completed" | "yes_no_prompt" | "multi_choice_prompt" | "timeout" | "no_dialogue"
        conversation: list of unique text segments collected
        text: joined conversation text
        region: "overworld"
        frames_elapsed: total frames consumed
    """
    start_frame = emu.get_frame_count()

    # ── Find ScriptManager ──
    mgr = _find_script_manager(emu)
    if mgr is None:
        # No script running — fall back to passive read
        result = read_dialogue(emu, "overworld")
        result["status"] = "no_dialogue"
        result["conversation"] = result.get("lines", [])
        result["frames_elapsed"] = 0
        return result

    # ── Check initial state ──
    ss = _read_script_state(emu, mgr)
    if not ss["is_msg_box_open"]:
        result = read_dialogue(emu, "overworld")
        result["status"] = "no_dialogue"
        result["conversation"] = result.get("lines", [])
        result["frames_elapsed"] = 0
        return result

    # ── Collect initial text ──
    conversation: list[str] = []
    seen_texts: set[str] = set()
    last_text = ""
    loop_detected = False

    def _collect_text() -> None:
        nonlocal last_text, loop_detected
        d = read_dialogue(emu, "overworld")
        text = d.get("text", "")
        if text and text != "(no active text)" and text != last_text:
            if text in seen_texts:
                loop_detected = True
            seen_texts.add(text)
            conversation.append(text)
            last_text = text

    _collect_text()

    # Track ctrlUI to detect Yes/No transitions (0 → non-zero = new prompt).
    # ctrlUI is never cleared once set, so we can only detect NEW prompts.
    last_ctrl_ui: int = emu.read_memory(mgr + SM_OFF_CTRL_UI, size="long")

    def _script_still_alive() -> bool:
        """Check if the ScriptManager magic is still present (script hasn't ended)."""
        try:
            return emu.read_memory(mgr, size="long") == SM_MAGIC
        except Exception:
            return False

    def _wait_for_msgbox_or_script_end() -> str | None:
        """When isMsgBoxOpen==0, wait to see if text comes back or script ends.

        Returns "completed" if script truly ended, None if text came back.
        """
        for _ in range(MAX_ANIM_POLLS):
            emu.advance_frames(ANIM_POLL)
            if not _script_still_alive():
                return "completed"
            ss2 = _read_script_state(emu, mgr)
            if ss2["is_msg_box_open"]:
                return None  # text came back — continue advancing
        return "completed"  # script alive but no text after long wait

    # ── Main advance loop ──
    # Uses overlay-independent detection: TP.state for page turns,
    # SM.ctrlUI for Yes/No menus, ctx.state for animation waits.
    for _ in range(MAX_ITERATIONS):
        ss = _read_script_state(emu, mgr)

        # Message box closed — but script might still be running (NPC walk, etc.)
        if not ss["is_msg_box_open"]:
            if not _script_still_alive():
                return _result("completed", conversation, start_frame, emu)
            outcome = _wait_for_msgbox_or_script_end()
            if outcome == "completed":
                return _result("completed", conversation, start_frame, emu)
            # Text came back — re-read state and continue
            _collect_text()
            continue

        # Yes/No (or other choice) menu — detect via ctrlUI transition.
        # ctrlUI is never freed once set, so we track its value and only
        # report a prompt when it changes from 0 or to a NEW pointer value
        # (indicating a fresh ShowYesNoMenu call, not a stale leftover).
        current_ctrl_ui = emu.read_memory(mgr + SM_OFF_CTRL_UI, size="long")
        if current_ctrl_ui != 0 and current_ctrl_ui != last_ctrl_ui:
            # New ctrlUI value — wait for text to finish, then report.
            # Capture shouldResume so we can verify reused-pointer prompts later.
            global _yes_no_resume_addr
            if _yes_no_resume_addr is None:
                _yes_no_resume_addr = emu.read_memory(
                    ctx_ptr + CTX_OFF_SHOULD_RESUME, size="long"
                )
            emu.advance_frames(SETTLE_FRAMES)
            _collect_text()
            last_ctrl_ui = current_ctrl_ui
            return _result("yes_no_prompt", conversation, start_frame, emu)

        # Pick the active ScriptContext
        ctx_ptr = ss["ctx1_ptr"] if (ss["sub_ctx_active"] and ss["ctx1_ptr"]) else ss["ctx0_ptr"]
        if not ctx_ptr:
            return _result("completed", conversation, start_frame, emu)

        ctx = _read_context_state(emu, ctx_ptr)

        # ── RUNNING: animation/movement/fanfare — wait passively ──
        if ctx["state"] == CTX_RUNNING:
            for _ in range(MAX_ANIM_POLLS):
                emu.advance_frames(ANIM_POLL)
                if not _script_still_alive():
                    _collect_text()
                    return _result("completed", conversation, start_frame, emu)
                ss2 = _read_script_state(emu, mgr)
                if not ss2["is_msg_box_open"]:
                    # Msg box closed during animation — wait for it to come back
                    outcome = _wait_for_msgbox_or_script_end()
                    if outcome == "completed":
                        _collect_text()
                        return _result("completed", conversation, start_frame, emu)
                    break  # text came back
                ctx2 = _read_context_state(emu, ctx_ptr)
                if ctx2["state"] != CTX_RUNNING:
                    break
            _collect_text()
            continue

        # ── WAITING: text displaying or waiting for input ──
        if ctx["state"] == CTX_WAITING:
            tp = _read_tp_state(emu)

            if tp["active"] and tp["state"] >= 1:
                # Scroll arrow visible — press B to advance page
                emu.press_buttons(["b"], frames=ADVANCE_HOLD)
                emu.advance_frames(SETTLE_FRAMES)
                _collect_text()
                continue

            # TP.state == 0: text is rendering OR text finished (WAITABPRESS/etc)
            # Wait a beat to let the state settle, then re-check
            emu.advance_frames(RENDER_POLL)
            ss2 = _read_script_state(emu, mgr)

            if not ss2["is_msg_box_open"]:
                _collect_text()
                return _result("completed", conversation, start_frame, emu)

            # Re-check TP — if it transitioned to waiting, handle on next iteration
            tp2 = _read_tp_state(emu)
            if tp2["active"] and tp2["state"] >= 1:
                _collect_text()
                continue

            # Re-check ctx — if script resumed (RUNNING), handle on next iteration
            ctx2 = _read_context_state(emu, ctx_ptr)
            if ctx2["state"] != CTX_WAITING:
                _collect_text()
                continue

            # Still WAITING with TP.state=0: could be WAITABPRESS, text
            # finishing, or a Yes/No about to appear.  Re-check ctrlUI before
            # pressing B — the script may have just issued ShowYesNoMenu.
            current_ctrl_ui = emu.read_memory(mgr + SM_OFF_CTRL_UI, size="long")
            if current_ctrl_ui != 0 and current_ctrl_ui != last_ctrl_ui:
                # Capture shouldResume for reused-pointer verification
                if _yes_no_resume_addr is None:
                    _yes_no_resume_addr = emu.read_memory(
                        ctx_ptr + CTX_OFF_SHOULD_RESUME, size="long"
                    )
                last_ctrl_ui = current_ctrl_ui
                _collect_text()
                return _result("yes_no_prompt", conversation, start_frame, emu)

            # ctrlUI pointer can be reused across consecutive Yes/No prompts
            # (the game never clears it; the heap reuses the same address).
            # When ctrlUI is non-zero, distinguish normal text rendering
            # (TP.state transitions to >= 1 within ~100-200 frames) from
            # an active Yes/No menu (TP.state stays at 0 indefinitely).
            # Also guard against false positives at dialogue end (msg box
            # closing or script ending while TP.state is still 0).
            if current_ctrl_ui != 0:
                # Track TextPrinter cursor to distinguish rendering from Yes/No.
                # Active rendering: currX advances as chars are drawn → break.
                # Dialogue ending: isMsgBoxOpen/script/TP.active changes → break.
                # Yes/No prompt: nothing changes for all polls → exhausted.
                yes_no_detected = True  # Assume Yes/No; disproven by any break
                from renegade_mcp.addresses import addr as _resolve
                _tp = _resolve("TP_BASE")
                cursor_pos = emu.read_memory(_tp + TP_OFF_CURR_X, size="short")
                for _ in range(YES_NO_VERIFY_POLLS):
                    emu.advance_frames(RENDER_POLL)
                    if not _script_still_alive():
                        yes_no_detected = False
                        break  # Script ended
                    ss3 = _read_script_state(emu, mgr)
                    if not ss3["is_msg_box_open"]:
                        yes_no_detected = False
                        break  # Msg box closed
                    tp3 = _read_tp_state(emu)
                    if tp3["state"] >= 1:
                        yes_no_detected = False
                        break  # Scroll arrow — normal text
                    if not tp3["active"]:
                        yes_no_detected = False
                        break  # TextPrinter finished
                    ctx3 = _read_context_state(emu, ctx_ptr)
                    if ctx3["state"] != CTX_WAITING:
                        yes_no_detected = False
                        break  # Script resumed
                    new_pos = emu.read_memory(_tp + TP_OFF_CURR_X, size="short")
                    if new_pos != cursor_pos:
                        yes_no_detected = False
                        break  # Cursor moved — still rendering
                    cursor_pos = new_pos
                if yes_no_detected:
                    # Verify via shouldResume: if we captured the Yes/No callback
                    # from the first ctrlUI transition, confirm this is the same.
                    # This distinguishes Yes/No menus from WaitABPress without
                    # a scroll arrow (e.g. Nurse Joy "We hope to see you again!").
                    if _yes_no_resume_addr is not None:
                        current_resume = emu.read_memory(
                            ctx_ptr + CTX_OFF_SHOULD_RESUME, size="long"
                        )
                        if current_resume != _yes_no_resume_addr:
                            yes_no_detected = False  # Different wait — not Yes/No
                if yes_no_detected:
                    _collect_text()
                    return _result("yes_no_prompt", conversation, start_frame, emu)

            # Detect multi-choice prompt loop: if any text segment has
            # appeared before, the script is cycling (e.g. Roark's stone quiz).
            # Catch this BEFORE pressing B to avoid infinite looping.
            if loop_detected:
                return _result("multi_choice_prompt", conversation, start_frame, emu)

            # Safe to press B — dismiss WAITABPRESS or advance.
            emu.press_buttons(["b"], frames=ADVANCE_HOLD)
            emu.advance_frames(SETTLE_FRAMES)
            _collect_text()
            continue

        # ── STOPPED or unexpected state ──
        if ss["is_msg_box_open"]:
            emu.press_buttons(["b"], frames=ADVANCE_HOLD)
            emu.advance_frames(SETTLE_FRAMES)
            _collect_text()
        else:
            return _result("completed", conversation, start_frame, emu)

    return _result("timeout", conversation, start_frame, emu)


def _result(status: str, conversation: list[str], start_frame: int, emu: EmulatorClient) -> dict:
    """Build the advance_dialogue return dict."""
    return {
        "status": status,
        "conversation": conversation,
        "text": "\n---\n".join(conversation) if conversation else "(no dialogue)",
        "region": "overworld",
        "frames_elapsed": emu.get_frame_count() - start_frame,
    }
