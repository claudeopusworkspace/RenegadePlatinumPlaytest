#!/usr/bin/env python3
"""Read and decode the current dialogue/battle text from the emulator's RAM.

Connects to the running MCP emulator via IPC bridge.
Checks both the overworld dialogue buffer and the battle text buffer,
returning whichever has valid text.

Usage:
    python3 scripts/read_dialogue.py              # print current text
    python3 scripts/read_dialogue.py --raw        # also show raw hex values
    python3 scripts/read_dialogue.py --full       # show full buffer (past terminator)
    python3 scripts/read_dialogue.py --battle     # force read battle buffer only
    python3 scripts/read_dialogue.py --overworld  # force read overworld buffer only
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "DesmumeMCP"))

from desmume_mcp.client import connect

# Buffer addresses (each preceded by D2EC B6F8 header marker)
OVERWORLD_BUFFER = 0x022A73BC   # NPC dialogue, signs, cutscene text
BATTLE_BUFFER = 0x02301BD0      # Battle narration ("X used Y!", "It's super effective!", etc.)

MAX_CHARS = 256  # max 16-bit values to read per buffer
SOCKET_PATH = "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock"

# === Gen 4 Pokemon Text Encoding ===
# Derived from memory analysis of Pokemon Renegade Platinum

CHAR_TABLE = {}

# Uppercase A-Z: 0x012B - 0x0144
for i in range(26):
    CHAR_TABLE[0x012B + i] = chr(ord('A') + i)

# Lowercase a-z: 0x0145 - 0x015E
for i in range(26):
    CHAR_TABLE[0x0145 + i] = chr(ord('a') + i)

# Digits 0-9: 0x0161 - 0x016A (assumed position, needs verification)
for i in range(10):
    CHAR_TABLE[0x0161 + i] = chr(ord('0') + i)

# Special characters
CHAR_TABLE[0x0188] = '\u00e9'  # é (as in Pokémon)

# Punctuation and symbols
CHAR_TABLE[0x01AB] = '!'       # confirmed
CHAR_TABLE[0x01AC] = '?'       # needs verification
CHAR_TABLE[0x01AD] = ','       # confirmed
CHAR_TABLE[0x01AE] = '.'       # confirmed
CHAR_TABLE[0x01AF] = '\u2026'  # ellipsis, needs verification
CHAR_TABLE[0x01B3] = "'"       # apostrophe (confirmed: "It's")
CHAR_TABLE[0x01DE] = ' '       # confirmed

# Control codes
CONTROL_CODES = {
    0xFFFF: '[END]',
    0xFFFE: '[VAR]',       # variable substitution (followed by args)
    0xE000: '\n',           # newline within text box
    0x25BC: '\n---\n',      # new text box / page break
}


def decode_char(val):
    """Decode a single 16-bit value to a character."""
    if val in CONTROL_CODES:
        return CONTROL_CODES[val]
    if val in CHAR_TABLE:
        return CHAR_TABLE[val]
    return f'[{val:04X}]'


def decode_buffer(values, show_full=False):
    """Decode a list of 16-bit values into text lines. Returns (lines, raw_pairs, has_text)."""
    decoded_chars = []
    raw_pairs = []
    text_char_count = 0

    for val in values:
        char = decode_char(val)
        raw_pairs.append((val, char))
        decoded_chars.append((val, char))

        # Count actual text characters (not control codes or unknowns)
        if val in CHAR_TABLE:
            text_char_count += 1

        if val == 0xFFFF and not show_full:
            break

    # Build output lines
    lines = []
    current_line = ""

    for val, char in decoded_chars:
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

    return lines, raw_pairs, text_char_count


def read_text(emu, address, label, show_raw=False, show_full=False):
    """Read and decode text from a specific buffer address."""
    values = emu.read_memory_range(address, size="short", count=MAX_CHARS)
    if not values:
        return False

    lines, raw_pairs, text_count = decode_buffer(values, show_full)

    # Only consider it valid text if we found enough actual characters
    if text_count < 3:
        return False

    print(f"[{label}]")
    for line in lines:
        print(line)

    if show_raw:
        print(f"\n=== Raw values ({label}) ===")
        for i, (val, char) in enumerate(raw_pairs):
            if val == 0xFFFF and not show_full:
                print(f"  [{i:3d}] 0x{val:04X} = [END]")
                break
            display = char if len(char) == 1 and char.isprintable() else repr(char)
            print(f"  [{i:3d}] 0x{val:04X} = {display}")

    return True


def main():
    show_raw = "--raw" in sys.argv
    show_full = "--full" in sys.argv
    force_battle = "--battle" in sys.argv
    force_overworld = "--overworld" in sys.argv

    emu = connect(SOCKET_PATH)

    found = False

    if force_battle:
        found = read_text(emu, BATTLE_BUFFER, "battle", show_raw, show_full)
    elif force_overworld:
        found = read_text(emu, OVERWORLD_BUFFER, "overworld", show_raw, show_full)
    else:
        # Try both buffers, print whichever has valid text
        # Check overworld first (more common), then battle
        found = read_text(emu, OVERWORLD_BUFFER, "overworld", show_raw, show_full)
        if not found:
            found = read_text(emu, BATTLE_BUFFER, "battle", show_raw, show_full)

    if not found:
        print("(no active text)")

    emu.close()


if __name__ == "__main__":
    main()
