#!/usr/bin/env python3
"""Decode Pokemon Platinum message NARC files (Gen 4 text format).

Usage:
    python3 scripts/decode_msg.py 382          # Decode and print all strings in file 0382.bin
    python3 scripts/decode_msg.py 382 --dump 5 # Dump raw hex of string 5 in file 0382
    python3 scripts/decode_msg.py --search Turtwig   # Search ALL files for strings containing "Turtwig"
    python3 scripts/decode_msg.py --search "Route 20" # Search with spaces (use quotes)
"""

import argparse
import os
import signal
import struct
import sys

# Handle broken pipe gracefully (e.g., when piped to head)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

MSG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "romdata", "pl_msg")

# ---------------------------------------------------------------------------
# Gen 4 character table
# ---------------------------------------------------------------------------
CHAR_MAP = {}

# A-Z: 0x012B - 0x0144
for _i in range(26):
    CHAR_MAP[0x012B + _i] = chr(ord('A') + _i)

# a-z: 0x0145 - 0x015E
for _i in range(26):
    CHAR_MAP[0x0145 + _i] = chr(ord('a') + _i)

# 0-9 (standard): 0x0161 - 0x016A
for _i in range(10):
    CHAR_MAP[0x0161 + _i] = chr(ord('0') + _i)

# 0-9 (alternate/small font): 0x0121 - 0x012A
for _i in range(10):
    CHAR_MAP[0x0121 + _i] = chr(ord('0') + _i)

# Punctuation and special characters
CHAR_MAP[0x01DE] = ' '
CHAR_MAP[0x0188] = '\u00e9'  # e with acute accent (for Pokemon)
CHAR_MAP[0x01AB] = '!'
CHAR_MAP[0x01AC] = '?'
CHAR_MAP[0x01AD] = ','
CHAR_MAP[0x01AE] = '.'
CHAR_MAP[0x01B3] = "'"
CHAR_MAP[0x01C4] = ':'
CHAR_MAP[0x01BA] = '/'
CHAR_MAP[0x01B2] = '-'
CHAR_MAP[0x01A9] = '('
CHAR_MAP[0x01AA] = ')'
CHAR_MAP[0x0189] = '\u2642'  # male symbol
CHAR_MAP[0x018A] = '\u2640'  # female symbol
CHAR_MAP[0x01B0] = '+'
CHAR_MAP[0x01AF] = '\u2026'  # ellipsis (...)
CHAR_MAP[0x01B1] = '='
CHAR_MAP[0x01B4] = '"'       # opening double quote (mapped to plain ")
CHAR_MAP[0x01B5] = '"'       # closing double quote (mapped to plain ")
CHAR_MAP[0x01B6] = '~'
CHAR_MAP[0x01B7] = '&'
CHAR_MAP[0x01BB] = '@'
CHAR_MAP[0x01BC] = '*'
CHAR_MAP[0x01BD] = '#'
CHAR_MAP[0x01BE] = '-'       # en-dash / line-break hyphen
CHAR_MAP[0x01C0] = ';'
CHAR_MAP[0x01C3] = '%'

# Control characters
CHAR_MAP[0xE000] = '\n'       # newline
CHAR_MAP[0x25BC] = '\n---\n'  # page break / new text box


# ---------------------------------------------------------------------------
# Decryption helpers
# ---------------------------------------------------------------------------

def decrypt_entry_table(data: bytes, num_entries: int, seed: int):
    """Decrypt the offset/length table. Returns list of (offset, char_count)."""
    entries = []
    for i in range(num_entries):
        raw_off = struct.unpack_from('<I', data, 4 + i * 8)[0]
        raw_len = struct.unpack_from('<I', data, 4 + i * 8 + 4)[0]
        ekey = (seed * 0x2FD * (i + 1)) & 0xFFFF
        xk = (ekey | (ekey << 16)) & 0xFFFFFFFF
        off = raw_off ^ xk
        ln = raw_len ^ xk
        entries.append((off, ln))
    return entries


def decrypt_string_raw(data: bytes, offset: int, char_count: int, string_index: int):
    """Decrypt a string and return the list of raw u16 character values."""
    key = (0x91BD3 * (string_index + 1)) & 0xFFFF
    chars = []
    for j in range(char_count):
        pos = offset + j * 2
        if pos + 1 >= len(data):
            break
        enc = struct.unpack_from('<H', data, pos)[0]
        dec = (enc ^ key) & 0xFFFF
        key = (key + 0x493D) & 0xFFFF
        chars.append(dec)
    return chars


def decode_chars(chars: list) -> str:
    """Convert a list of raw u16 values to a readable string."""
    text = ''
    j = 0
    while j < len(chars):
        c = chars[j]
        if c == 0xFFFF:
            break
        elif c == 0xFFFE:
            # Variable placeholder: type (u16), arg_count (u16), then args
            j += 1
            if j < len(chars):
                vtype = chars[j]
                j += 1
                if j < len(chars):
                    vcount = chars[j]
                    j += 1
                    args = []
                    for _ in range(vcount):
                        if j < len(chars):
                            args.append(chars[j])
                            j += 1
                    parts = [f'0x{vtype:04X}'] + [f'0x{a:04X}' for a in args]
                    text += '{' + ','.join(parts) + '}'
                    continue
                else:
                    text += '{VAR}'
                    continue
            else:
                text += '{VAR}'
                continue
        elif c in CHAR_MAP:
            text += CHAR_MAP[c]
        else:
            text += f'[0x{c:04X}]'
        j += 1
    return text


# ---------------------------------------------------------------------------
# File-level operations
# ---------------------------------------------------------------------------

def decode_file(file_index: int) -> list:
    """Decode all strings in a message file. Returns list of (index, text, raw_chars)."""
    path = os.path.join(MSG_DIR, f"{file_index:04d}.bin")
    if not os.path.isfile(path):
        print(f"Error: {path} not found", file=sys.stderr)
        return []

    data = open(path, 'rb').read()
    if len(data) < 4:
        return []

    num_entries = struct.unpack_from('<H', data, 0)[0]
    seed = struct.unpack_from('<H', data, 2)[0]

    # Validate: header + table should fit in file
    table_end = 4 + num_entries * 8
    if table_end > len(data):
        print(f"Error: file too small for {num_entries} entries", file=sys.stderr)
        return []

    entries = decrypt_entry_table(data, num_entries, seed)
    results = []

    for i, (offset, char_count) in enumerate(entries):
        # Sanity check
        if offset + char_count * 2 > len(data) + 2 or char_count > 10000:
            results.append((i, f"<invalid: offset={offset}, len={char_count}>", []))
            continue

        raw_chars = decrypt_string_raw(data, offset, char_count, i)
        text = decode_chars(raw_chars)
        results.append((i, text, raw_chars))

    return results


def print_file(file_index: int, dump_index: int = None):
    """Print all strings in a file, or dump raw hex of a specific string."""
    results = decode_file(file_index)
    if not results:
        return

    if dump_index is not None:
        # Dump mode: show raw hex of one string
        for idx, text, raw_chars in results:
            if idx == dump_index:
                print(f"File {file_index:04d}, String {idx}:")
                print(f"  Text: {text}")
                print(f"  Chars ({len(raw_chars)}):")
                hex_line = ' '.join(f'{c:04X}' for c in raw_chars)
                # Wrap at ~80 chars
                words = hex_line.split()
                line = '    '
                for w in words:
                    if len(line) + len(w) + 1 > 80:
                        print(line)
                        line = '    '
                    line += w + ' '
                if line.strip():
                    print(line)
                return
        print(f"String index {dump_index} not found (file has {len(results)} strings)")
        return

    # Print all strings
    print(f"=== File {file_index:04d} ({len(results)} strings) ===")
    max_idx = max(r[0] for r in results) if results else 0
    idx_width = len(str(max_idx))
    for idx, text, raw_chars in results:
        # For multi-line strings, indent continuation lines
        lines = text.split('\n')
        first = lines[0]
        print(f"{idx:>{idx_width}}: {first}")
        for line in lines[1:]:
            print(f"{' ' * (idx_width + 2)}{line}")


def search_all(query: str, case_sensitive: bool = False):
    """Search all message files for strings containing query text."""
    if not case_sensitive:
        query_lower = query.lower()

    # Find all .bin files
    files = sorted(f for f in os.listdir(MSG_DIR) if f.endswith('.bin'))
    total_matches = 0

    for fname in files:
        file_index = int(fname.replace('.bin', ''))
        results = decode_file(file_index)

        for idx, text, raw_chars in results:
            if case_sensitive:
                match = query in text
            else:
                match = query_lower in text.lower()

            if match:
                total_matches += 1
                # Truncate very long strings for display
                display = text.replace('\n', ' | ')
                if len(display) > 120:
                    display = display[:120] + '...'
                print(f"File {file_index:04d} [{idx:>4d}]: {display}")

    if total_matches == 0:
        print(f"No matches found for '{query}'")
    else:
        print(f"\n--- {total_matches} match(es) found ---")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Decode Pokemon Platinum message files (Gen 4 text format)")
    parser.add_argument('file_index', nargs='?', type=int,
                        help='File index to decode (e.g., 382)')
    parser.add_argument('--search', '-s', type=str,
                        help='Search all files for strings containing TEXT')
    parser.add_argument('--dump', '-d', type=int, default=None,
                        help='Dump raw hex of a specific string index')
    parser.add_argument('--case-sensitive', '-c', action='store_true',
                        help='Case-sensitive search')
    args = parser.parse_args()

    if args.search:
        search_all(args.search, case_sensitive=args.case_sensitive)
    elif args.file_index is not None:
        print_file(args.file_index, dump_index=args.dump)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
