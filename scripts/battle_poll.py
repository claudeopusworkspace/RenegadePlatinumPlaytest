#!/usr/bin/env python3
"""Poll the battle text buffer and build a turn log.

After selecting a move/action, run this script to capture all battle
narration until the game reaches a stopping point (waiting for input
or waiting for next action selection).

Requires battle_init.py to have been run at the start of the battle.
The init snapshot tells us which text markers were already in memory
(overworld dialogue, etc.) so we can ignore them and only track new
battle narration.

Usage:
    python3 scripts/battle_poll.py          # poll until next stopping point
    python3 scripts/battle_poll.py --press  # also press B to dismiss input-wait messages

Exit states:
    WAIT_FOR_ACTION  — game is at move/item/switch selection
    WAIT_FOR_INPUT   — game is waiting for B press to dismiss dialogue
    TIMEOUT          — still auto-advancing (hit max poll limit)
"""

import json
import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "DesmumeMCP"))

from desmume_mcp.client import connect

# Discovery scan: broad sweep of heap to find where battle text landed.
# Only done once at startup; subsequent polls use a narrow window.
DISCOVERY_START = 0x0228A000
DISCOVERY_SIZE = 0x180000   # 1.5 MB

HEADER_MARKER = b"\xEC\xD2\xF8\xB6"  # D2EC B6F8 in little-endian
MAX_TEXT_CHARS = 120
POLL_REGION_PADDING = 0x1000  # 4 KB padding around discovered markers
MAX_POLLS = 300       # ~75 seconds at 15 frames/poll (safety limit)
DISCOVERY_POLLS = 30  # polls during discovery before giving up
POLL_FRAMES = 15      # frames to advance between reads
SETTLE_FRAMES = 120   # frames to wait after detecting a stop indicator
SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"
INIT_FILE = "/workspace/RenegadePlatinumPlaytest/.battle_init.json"

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


def load_init_baseline():
    """Load the battle init baseline. Returns (frame, {addr: text}) or exits."""
    if not os.path.exists(INIT_FILE):
        print("Error: no battle init found. Run battle_init.py at the start of the battle.")
        sys.exit(1)

    with open(INIT_FILE) as f:
        data = json.load(f)

    baseline = data.get("markers", {})
    baseline_frame = data.get("frame", 0)
    return baseline_frame, baseline


def validate_baseline(emu, baseline_frame):
    """Check that the init baseline is from this session (not stale)."""
    current_frame = emu.get_frame_count()
    if current_frame < baseline_frame:
        print(f"Warning: current frame ({current_frame}) < init frame ({baseline_frame}).")
        print("A save state may have been loaded after battle_init.py ran.")
        print("Re-run battle_init.py for this battle.")
        sys.exit(1)


def scan_for_text(data, base_addr, baseline=None):
    """Scan raw bytes for D2EC B6F8 markers with active text.

    Args:
        baseline: dict of {hex_addr_str: text_content} from battle_init.
                  Markers at a baseline address are only included if their
                  text has changed (i.e., the game wrote new content to the slot).

    Returns list of (abs_addr, text, vals, known_count) sorted by known_count desc.
    """
    if baseline is None:
        baseline = {}

    results = []
    idx = 0
    while True:
        idx = data.find(HEADER_MARKER, idx)
        if idx < 0:
            break

        abs_addr = base_addr + idx
        addr_str = f"0x{abs_addr:08X}"

        text_start = idx + 4
        if text_start + 1 >= len(data):
            idx += 2
            continue

        first_val = struct.unpack_from("<H", data, text_start)[0]
        if first_val == 0xFFFF:
            idx += 2
            continue

        # Read values from this slot
        vals = []
        known_count = 0
        pos = text_start
        while pos + 1 < len(data) and len(vals) < MAX_TEXT_CHARS:
            v = struct.unpack_from("<H", data, pos)[0]
            vals.append(v)
            pos += 2
            if v == 0xFFFF:
                break
            if v in CHAR_TABLE:
                known_count += 1

        if known_count >= 3:
            text, _ = decode_text(vals)
            if text.strip():
                # Skip if this slot still has the same content as the baseline
                if addr_str in baseline and baseline[addr_str] == text:
                    idx += 2
                    continue
                results.append((abs_addr, text, vals, known_count))

        idx += 2

    results.sort(key=lambda x: -x[3])
    return results


def scan_battle_text(emu, scan_start, scan_size, baseline=None):
    """Scan a memory region for the best active text slot (filtering baseline).

    Returns (text, vals_including_end) or (None, []) if no text found.
    """
    raw_bytes = emu.read_memory_range(scan_start, size="byte", count=scan_size)
    if not raw_bytes:
        return None, []

    data = bytes(raw_bytes)
    results = scan_for_text(data, scan_start, baseline)
    if results:
        _, text, vals, _ = results[0]
        return text, vals
    return None, []


def discover_battle_region(emu, baseline):
    """Broad scan to find where NEW battle text lives (filtering baseline).

    Returns (region_start, region_size) or None if not found.
    """
    for attempt in range(DISCOVERY_POLLS):
        emu.advance_frames(POLL_FRAMES)

        raw_bytes = emu.read_memory_range(DISCOVERY_START, size="byte", count=DISCOVERY_SIZE)
        if not raw_bytes:
            continue

        data = bytes(raw_bytes)
        results = scan_for_text(data, DISCOVERY_START, baseline)
        if results:
            # Build a narrow region around the new markers only
            addrs = [r[0] for r in results]
            nearest = min(addrs)
            furthest = max(addrs)
            region_start = max(DISCOVERY_START, nearest - POLL_REGION_PADDING)
            region_end = furthest + POLL_REGION_PADDING
            region_size = region_end - region_start

            addr = results[0][0]
            print(f"[discovered battle text at 0x{addr:08X}, polling 0x{region_start:08X} +{region_size} bytes]")
            return region_start, region_size

    return None


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

    Phase 1: load baseline from battle_init.py, validate it's current.
    Phase 2 (discovery): broad scan, find NEW markers not in baseline.
    Phase 3 (polling): narrow scan of discovered region for fast updates.

    Skips the initial stale message (from the previous action prompt) by
    requiring at least one auto-advancing message before accepting a stop.
    """
    baseline_frame, baseline = load_init_baseline()

    emu = connect(SOCKET_PATH)
    validate_baseline(emu, baseline_frame)

    if baseline:
        print(f"[baseline: {len(baseline)} pre-existing marker(s) loaded]")

    # Phase 2: discover where NEW battle text is
    result = discover_battle_region(emu, baseline)
    if result is None:
        print("=== Battle Log ===")
        print("  (no new battle text found after discovery scan)")
        print("\nState: NO_TEXT")
        emu.close()
        return [], "NO_TEXT"

    scan_start, scan_size = result

    # Phase 3: poll the narrow region
    # During polling, only filter baseline until we've seen real narration.
    # Once we've seen auto-advancing text, stop filtering so recurring
    # prompts like "What will Turtwig do?" are detected.
    log = []
    prev_text = None
    seen_auto = False

    for poll in range(MAX_POLLS):
        emu.advance_frames(POLL_FRAMES)

        active_baseline = baseline if not seen_auto else None
        text, vals = scan_battle_text(emu, scan_start, scan_size, active_baseline)
        if text is None:
            continue
        stop = classify_stop(vals)

        # New message?
        if text and text != prev_text:
            prev_text = text

            if stop == "AUTO_ADVANCE":
                seen_auto = True
                log.append({"text": text, "stop": stop})
            elif seen_auto:
                log.append({"text": text, "stop": stop})

                # Let it fully settle
                emu.advance_frames(SETTLE_FRAMES)

                if stop == "WAIT_FOR_INPUT" and auto_press:
                    emu.press_buttons(["b"], frames=8)
                    emu.advance_frames(30)
                    continue

                _print_log(log, stop)
                emu.close()
                return log, stop

    _print_log(log, "TIMEOUT")
    emu.close()
    return log, "TIMEOUT"


def _print_log(log, final_state):
    """Print the battle log and final state."""
    print("=== Battle Log ===")
    for i, entry in enumerate(log):
        text = entry["text"]
        text = text.replace("\n", " / ")
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
