#!/usr/bin/env python3
"""Scan memory dumps for known text using various Gen 4 Pokemon encoding hypotheses."""

import sys
import struct

def scan_for_text(filepath, target_text):
    with open(filepath, "rb") as f:
        data = f.read()

    print(f"Dump size: {len(data)} bytes")
    print(f"Looking for: '{target_text}'")
    print()

    # === Method 1: Plain ASCII / UTF-8 ===
    ascii_bytes = target_text.encode("ascii")
    idx = data.find(ascii_bytes)
    if idx >= 0:
        print(f"[ASCII] Found at offset 0x{idx:04X}!")

    # === Method 2: UTF-16 LE (each char as 16-bit) ===
    utf16_bytes = target_text.encode("utf-16-le")
    idx = data.find(utf16_bytes)
    if idx >= 0:
        print(f"[UTF-16 LE] Found at offset 0x{idx:04X}!")

    # === Method 3: Try to derive encoding from first char ===
    # Look for 16-bit sequences where the pattern of repeating chars matches
    # "Technology just blows me away!" has repeated chars:
    # o appears at positions 5,7,14 (0-indexed: t=0)
    # Wait, let me just check: T(0) e(1) c(2) h(3) n(4) o(5) l(6) o(7) g(8) y(9)
    # ' '(10) j(11) u(12) s(13) t(14) ' '(15) b(16) l(17) o(18) w(19) s(20)
    # ' '(21) m(22) e(23) ' '(24) a(25) w(26) a(27) y(28) !(29)

    # Build character constraints from the text
    # Characters that repeat give us relationships
    target = target_text
    char_positions = {}
    for i, c in enumerate(target):
        char_positions.setdefault(c, []).append(i)

    print("=== Character frequency in target text ===")
    for c, positions in sorted(char_positions.items(), key=lambda x: -len(x[1])):
        if len(positions) > 1:
            print(f"  '{c}' appears {len(positions)} times at positions {positions}")
    print()

    # === Method 4: Brute-force 16-bit encoding search ===
    # Scan through data as 16-bit values, looking for sequences where
    # the pattern of equal/different values matches our target text
    print("=== Scanning for 16-bit encoded text (pattern matching) ===")
    target_len = len(target)

    found_candidates = []

    for start in range(0, len(data) - target_len * 2, 2):
        values = []
        for i in range(target_len):
            val = struct.unpack_from("<H", data, start + i * 2)[0]
            values.append(val)

        # Check if the pattern of equal/different values matches
        # Build a mapping from char -> value
        mapping = {}
        reverse_mapping = {}
        valid = True

        for i, c in enumerate(target):
            v = values[i]
            if c in mapping:
                if mapping[c] != v:
                    valid = False
                    break
            else:
                if v in reverse_mapping and reverse_mapping[v] != c:
                    valid = False
                    break
                mapping[c] = v
                reverse_mapping[v] = c

        if valid:
            # Additional sanity check: values should be in a reasonable range
            # and the mapping should be consistent
            min_val = min(mapping.values())
            max_val = max(mapping.values())

            # Filter out obviously wrong matches (all same value, too spread out, etc.)
            if len(set(values)) >= len(set(target)) and max_val - min_val < 0x200:
                found_candidates.append((start, mapping, values))

    if found_candidates:
        print(f"Found {len(found_candidates)} candidate(s)!")
        for start, mapping, values in found_candidates[:5]:  # Show first 5
            print(f"\n  Offset 0x{start:04X}:")
            # Show the derived character table
            sorted_chars = sorted(mapping.items(), key=lambda x: x[1])
            print(f"  Derived encoding (char -> 16-bit value):")
            for c, v in sorted_chars:
                print(f"    '{c}' = 0x{v:04X} ({v})")
            # Show raw values
            print(f"  Raw 16-bit values: {' '.join(f'{v:04X}' for v in values[:20])}...")
    else:
        print("No 16-bit pattern matches found.")

    # === Method 5: Scan for individual byte patterns ===
    # Maybe it's single-byte encoded with an offset
    print("\n=== Scanning for single-byte offset encoding ===")
    for start in range(len(data) - target_len):
        byte_vals = [data[start + i] for i in range(target_len)]

        mapping = {}
        reverse_mapping = {}
        valid = True

        for i, c in enumerate(target):
            v = byte_vals[i]
            if c in mapping:
                if mapping[c] != v:
                    valid = False
                    break
            else:
                if v in reverse_mapping and reverse_mapping[v] != c:
                    valid = False
                    break
                mapping[c] = v
                reverse_mapping[v] = c

        if valid and len(set(byte_vals)) >= len(set(target)):
            min_val = min(mapping.values())
            max_val = max(mapping.values())
            if max_val - min_val < 128:  # Reasonable range for text
                print(f"  Found at offset 0x{start:04X}!")
                sorted_chars = sorted(mapping.items(), key=lambda x: x[1])
                print(f"  Encoding (char -> byte):")
                for c, v in sorted_chars:
                    print(f"    '{c}' = 0x{v:02X} ({v})")
                print()
                break
    else:
        print("  No single-byte pattern matches found.")


if __name__ == "__main__":
    dump_path = sys.argv[1] if len(sys.argv) > 1 else "dumps/dialogue_hotspot.bin"
    target = sys.argv[2] if len(sys.argv) > 2 else "Technology just blows me away!"
    scan_for_text(dump_path, target)
