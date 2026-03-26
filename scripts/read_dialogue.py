#!/usr/bin/env python3
"""Read and decode the current dialogue/battle text from the emulator's RAM.

Connects to the running MCP emulator via IPC bridge.
Scans memory regions for D2EC B6F8 header markers, finds the active text
slot (one where the first value after the marker is NOT 0xFFFF), and
decodes the Gen 4 text encoding.

Usage:
    python3 scripts/read_dialogue.py              # print current text
    python3 scripts/read_dialogue.py --raw        # also show raw hex values
    python3 scripts/read_dialogue.py --battle     # force read battle region only
    python3 scripts/read_dialogue.py --overworld  # force read overworld region only
"""

import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "DesmumeMCP"))

from desmume_mcp.client import connect

# Memory regions to scan. Each is (start_addr, size, label).
OVERWORLD_REGION = (0x022A7000, 0x2800, "overworld")  # 10KB
BATTLE_REGION = (0x0228A000, 0x180000, "battle")       # 1.5 MB broad scan

# The 4-byte header marker preceding each text slot (little-endian)
HEADER_MARKER = b"\xEC\xD2\xF8\xB6"

MAX_TEXT_CHARS = 512
SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"

# === Gen 4 Pokemon Text Encoding ===

CHAR_TABLE = {}

# Uppercase A-Z: 0x012B - 0x0144
for i in range(26):
    CHAR_TABLE[0x012B + i] = chr(ord('A') + i)

# Lowercase a-z: 0x0145 - 0x015E
for i in range(26):
    CHAR_TABLE[0x0145 + i] = chr(ord('a') + i)

# Digits 0-9: 0x0161 - 0x016A
for i in range(10):
    CHAR_TABLE[0x0161 + i] = chr(ord('0') + i)

# Special characters
CHAR_TABLE[0x0188] = '\u00e9'  # é (as in Pokémon)

# Punctuation and symbols
CHAR_TABLE[0x01AB] = '!'
CHAR_TABLE[0x01AC] = '?'
CHAR_TABLE[0x01AD] = ','
CHAR_TABLE[0x01AE] = '.'
CHAR_TABLE[0x01AF] = '\u2026'  # ellipsis
CHAR_TABLE[0x01B3] = "'"
CHAR_TABLE[0x01C4] = ':'
CHAR_TABLE[0x01DE] = ' '

# Control codes
TEXT_CONTROL = {
    0xFFFF: '[END]',
    0xFFFE: '[VAR]',
    0xE000: '\n',
    0x25BC: '\n---\n',
}


def decode_char(val):
    """Decode a single 16-bit value to a character."""
    if val in TEXT_CONTROL:
        return TEXT_CONTROL[val]
    if val in CHAR_TABLE:
        return CHAR_TABLE[val]
    return f'[{val:04X}]'


def find_active_slots(data, base_addr):
    """Find D2EC B6F8 markers with active text (first value != FFFF).

    Returns list of (text_addr, text_values, known_char_count)
    sorted by known_char_count descending.
    """
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

        # Check first value — if FFFF, slot is empty
        first_val = struct.unpack_from("<H", data, text_start)[0]
        if first_val == 0xFFFF:
            idx += 2
            continue

        # Read text values from this slot
        values = []
        known_count = 0
        pos = text_start

        while pos + 1 < len(data) and len(values) < MAX_TEXT_CHARS:
            val = struct.unpack_from("<H", data, pos)[0]
            values.append(val)
            pos += 2

            if val == 0xFFFF:
                break
            if val in CHAR_TABLE:
                known_count += 1

        text_addr = base_addr + text_start
        if known_count >= 3:
            results.append((text_addr, values, known_count))

        idx += 2

    results.sort(key=lambda x: -x[2])
    return results


def decode_values(values):
    """Decode 16-bit values into text lines. Returns (lines, raw_pairs)."""
    raw_pairs = []
    lines = []
    current_line = ""

    for val in values:
        char = decode_char(val)
        raw_pairs.append((val, char))

        if val == 0xFFFF:
            if current_line:
                lines.append(current_line)
                current_line = ""
            break
        elif val == 0x25BC:
            if current_line:
                lines.append(current_line)
            lines.append("---")
            current_line = ""
        elif val == 0xE000:
            lines.append(current_line)
            current_line = ""
        else:
            current_line += char

    if current_line:
        lines.append(current_line)

    return lines, raw_pairs


def scan_region(emu, region, show_raw=False):
    """Scan a memory region for active text slots. Returns True if found."""
    start_addr, size, label = region

    raw_bytes = emu.read_memory_range(start_addr, size="byte", count=size)
    if not raw_bytes:
        return False

    data = bytes(raw_bytes)
    slots = find_active_slots(data, start_addr)

    if not slots:
        return False

    # Use the slot with the most known characters
    addr, values, _ = slots[0]
    lines, raw_pairs = decode_values(values)

    if not lines or all(not line.strip() or line == "---" for line in lines):
        return False

    print(f"[{label} @ 0x{addr:08X}]")
    for line in lines:
        print(line)

    if show_raw:
        print(f"\n=== Raw values ({label}) ===")
        for i, (val, char) in enumerate(raw_pairs):
            if val == 0xFFFF:
                print(f"  [{i:3d}] 0x{val:04X} = [END]")
                break
            display = char if len(char) == 1 and char.isprintable() else repr(char)
            print(f"  [{i:3d}] 0x{val:04X} = {display}")

    return True


def main():
    show_raw = "--raw" in sys.argv
    force_battle = "--battle" in sys.argv
    force_overworld = "--overworld" in sys.argv

    emu = connect(SOCKET_PATH)

    found = False

    if force_battle:
        found = scan_region(emu, BATTLE_REGION, show_raw)
    elif force_overworld:
        found = scan_region(emu, OVERWORLD_REGION, show_raw)
    else:
        found = scan_region(emu, OVERWORLD_REGION, show_raw)
        if not found:
            found = scan_region(emu, BATTLE_REGION, show_raw)

    if not found:
        print("(no active text)")

    emu.close()


if __name__ == "__main__":
    main()
