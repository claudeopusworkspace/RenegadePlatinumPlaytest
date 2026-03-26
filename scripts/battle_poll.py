#!/usr/bin/env python3
"""Poll the battle text buffer and build a turn log.

After selecting a move/action, run this script to capture all battle
narration until the game reaches a stopping point (waiting for input
or waiting for next action selection).

Advances ~15 frames at a time, reading the battle text buffer each time.
When a new message appears, it's added to the log. Once a "wait" indicator
is detected, waits ~120 frames for it to finish loading, then returns
the full log and the current game state.

Usage:
    python3 scripts/battle_poll.py          # poll until next stopping point
    python3 scripts/battle_poll.py --press  # also press B to dismiss input-wait messages

Exit states:
    WAIT_FOR_ACTION  — game is at move/item/switch selection
    WAIT_FOR_INPUT   — game is waiting for B press to dismiss dialogue
    AUTO_ADVANCE     — still auto-advancing (hit max poll limit)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "DesmumeMCP"))

from desmume_mcp.client import connect

BATTLE_BUFFER = 0x02301BD0
MAX_CHARS = 80
MAX_POLLS = 300       # ~75 seconds at 15 frames/poll (safety limit)
POLL_FRAMES = 15      # frames to advance between reads
SETTLE_FRAMES = 120   # frames to wait after detecting a stop indicator
SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"

# === Text Encoding ===

CHAR_TABLE = {}
for i in range(26):
    CHAR_TABLE[0x012B + i] = chr(ord('A') + i)
for i in range(26):
    CHAR_TABLE[0x0145 + i] = chr(ord('a') + i)
for i in range(10):
    CHAR_TABLE[0x0161 + i] = chr(ord('0') + i)
CHAR_TABLE[0x0188] = '\u00e9'  # é
CHAR_TABLE[0x01AB] = '!'
CHAR_TABLE[0x01AC] = '?'
CHAR_TABLE[0x01AD] = ','
CHAR_TABLE[0x01AE] = '.'
CHAR_TABLE[0x01B3] = "'"
CHAR_TABLE[0x01DE] = ' '


def decode_text(vals):
    """Decode 16-bit values up to END marker. Returns (text, raw_vals_up_to_end)."""
    out = ""
    for i, v in enumerate(vals):
        if v == 0xFFFF:
            return out, vals[:i]
        elif v == 0xE000:
            out += "\n"
        elif v == 0x25BC:
            out += "\n"
        elif v in CHAR_TABLE:
            out += CHAR_TABLE[v]
        else:
            out += f"[{v:04X}]"
    return out, vals


def classify_stop(vals):
    """Classify the message based on trailing bytes before END.

    Returns one of:
        'WAIT_FOR_ACTION'  — FFFE sequence before END (move selection, etc.)
        'WAIT_FOR_INPUT'   — E000 before END (press B to dismiss)
        'AUTO_ADVANCE'     — anything else (will auto-progress)
    """
    end_idx = None
    for i, v in enumerate(vals):
        if v == 0xFFFF:
            end_idx = i
            break
    if end_idx is None or end_idx == 0:
        return "AUTO_ADVANCE"

    pre_end = vals[end_idx - 1]
    if pre_end == 0xE000:
        return "WAIT_FOR_INPUT"

    # Check for FFFE anywhere in the last few values before END
    for j in range(max(0, end_idx - 5), end_idx):
        if vals[j] == 0xFFFE:
            return "WAIT_FOR_ACTION"

    return "AUTO_ADVANCE"


def poll_battle(auto_press=False):
    """Poll the battle buffer, building a log until a stop point is reached.

    Skips the initial stale message (from the previous action prompt) by
    requiring at least one auto-advancing message before accepting a stop.
    """
    emu = connect(SOCKET_PATH)

    log = []
    prev_text = None
    seen_auto = False  # must see an auto-advance message before accepting stops

    for poll in range(MAX_POLLS):
        emu.advance_frames(POLL_FRAMES)

        vals = emu.read_memory_range(BATTLE_BUFFER, size="short", count=MAX_CHARS)
        text, raw = decode_text(vals)
        stop = classify_stop(vals)

        # New message?
        if text and text != prev_text:
            prev_text = text

            if stop == "AUTO_ADVANCE":
                seen_auto = True
                log.append({"text": text, "stop": stop})
            elif seen_auto:
                # We've seen real narration, so this stop is meaningful
                log.append({"text": text, "stop": stop})

                # Let it fully settle
                emu.advance_frames(SETTLE_FRAMES)

                if stop == "WAIT_FOR_INPUT" and auto_press:
                    emu.press_buttons(["b"], frames=8)
                    emu.advance_frames(30)
                    # Keep polling for more messages after dismissing
                    continue

                # We've hit a stopping point — return the log
                _print_log(log, stop)
                emu.close()
                return log, stop
            # else: stale message from before our action — skip it

    # Reached max polls without a stop point
    _print_log(log, "TIMEOUT")
    emu.close()
    return log, "TIMEOUT"


def _print_log(log, final_state):
    """Print the battle log and final state."""
    print("=== Battle Log ===")
    for i, entry in enumerate(log):
        text = entry["text"]
        # Clean up: collapse newlines, strip action prompts from display
        text = text.replace("\n", " / ")
        # Remove trailing VAR sequences for display
        while "[FFFE]" in text:
            text = text[:text.index("[FFFE]")].rstrip()
        marker = ""
        if entry["stop"] == "WAIT_FOR_INPUT":
            marker = "  [waits for B]"
        elif entry["stop"] == "WAIT_FOR_ACTION":
            marker = "  [action prompt]"
        print(f"  {text}{marker}")
    print(f"\nState: {final_state}")


if __name__ == "__main__":
    auto_press = "--press" in sys.argv
    poll_battle(auto_press=auto_press)
