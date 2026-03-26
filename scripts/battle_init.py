#!/usr/bin/env python3
"""Snapshot the current text markers in memory at battle start.

Run this once at the beginning of each battle (after the battle screen has
loaded). It scans a broad heap region for D2EC B6F8 text markers and saves
their addresses and content as a baseline. battle_poll.py then uses this
baseline to distinguish pre-existing text (overworld dialogue, etc.) from
new battle narration.

Usage:
    python3 scripts/battle_init.py

Output:
    Writes .battle_init.json to the project root.
"""

import json
import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "DesmumeMCP"))

from desmume_mcp.client import connect

# Same broad scan range as battle_poll.py discovery
SCAN_START = 0x0228A000
SCAN_SIZE = 0x180000  # 1.5 MB

HEADER_MARKER = b"\xEC\xD2\xF8\xB6"
MAX_TEXT_CHARS = 120
SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"
INIT_FILE = "/workspace/RenegadePlatinumPlaytest/.battle_init.json"

# Text encoding (same as battle_poll.py / read_dialogue.py)
CHAR_TABLE = {}
for i in range(26):
    CHAR_TABLE[0x012B + i] = chr(ord('A') + i)
for i in range(26):
    CHAR_TABLE[0x0145 + i] = chr(ord('a') + i)
for i in range(10):
    CHAR_TABLE[0x0161 + i] = chr(ord('0') + i)
CHAR_TABLE[0x0188] = '\u00e9'
CHAR_TABLE[0x01AB] = '!'
CHAR_TABLE[0x01AC] = '?'
CHAR_TABLE[0x01AD] = ','
CHAR_TABLE[0x01AE] = '.'
CHAR_TABLE[0x01B3] = "'"
CHAR_TABLE[0x01DE] = ' '


def decode_text(vals):
    """Decode 16-bit values up to END marker."""
    out = ""
    for v in vals:
        if v == 0xFFFF:
            break
        elif v == 0xE000:
            out += "\n"
        elif v == 0x25BC:
            out += "\n"
        elif v in CHAR_TABLE:
            out += CHAR_TABLE[v]
        else:
            out += f"[{v:04X}]"
    return out


def scan_markers(data, base_addr):
    """Find all D2EC B6F8 markers with active text (>= 3 known chars).

    Returns dict of {hex_addr_str: decoded_text}.
    """
    markers = {}
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
        if first_val == 0xFFFF:
            idx += 2
            continue

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
            text = decode_text(vals)
            if text.strip():
                addr = base_addr + idx
                markers[f"0x{addr:08X}"] = text

        idx += 2

    return markers


def main():
    emu = connect(SOCKET_PATH)

    frame = emu.get_frame_count()

    raw_bytes = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
    emu.close()

    if not raw_bytes:
        print("Error: could not read memory.")
        sys.exit(1)

    data = bytes(raw_bytes)
    markers = scan_markers(data, SCAN_START)

    init_data = {
        "frame": frame,
        "scan_start": f"0x{SCAN_START:08X}",
        "scan_size": SCAN_SIZE,
        "markers": markers,
    }

    with open(INIT_FILE, "w") as f:
        json.dump(init_data, f, indent=2)

    print(f"Battle init saved at frame {frame}")
    print(f"Found {len(markers)} existing text marker(s):")
    for addr, text in markers.items():
        preview = text.replace("\n", " / ")[:60]
        print(f"  {addr}: {preview}...")
    print(f"\nSaved to {INIT_FILE}")


if __name__ == "__main__":
    main()
