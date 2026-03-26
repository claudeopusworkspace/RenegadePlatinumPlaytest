#!/usr/bin/env python3
"""Search memory dump for consecutive move ID patterns.

Looks for known move sequences (as u16 LE) that would indicate
where the game stores move data for party Pokemon.
"""

import struct
import sys

DUMP_FILE = "/workspace/RenegadePlatinumPlaytest/dumps/party_tree_region.bin"
BASE_ADDR = 0x022A0000

# Known move sets (move IDs)
# Turtwig: Tackle(33), Withdraw(110), Absorb(71) + empty(0)
# Eevee: Tackle(33), Tail Whip(39), Bite(44), Covet(343)

TURTWIG_MOVES = [33, 110, 71]     # 3 moves, 4th slot likely 0
EEVEE_MOVES = [33, 39, 44, 343]   # 4 moves

def search_consecutive_u16(data, values, label, min_match=3):
    """Search for consecutive u16 values in data."""
    results = []
    for i in range(0, len(data) - len(values) * 2, 2):
        matches = 0
        for j, val in enumerate(values):
            offset = i + j * 2
            actual = struct.unpack_from('<H', data, offset)[0]
            if actual == val:
                matches += 1
        if matches >= min_match:
            addr = BASE_ADDR + i
            actual_vals = [struct.unpack_from('<H', data, i + j*2)[0] for j in range(len(values) + 2)]
            results.append((addr, actual_vals, matches))
    return results

def search_with_gaps(data, values, label, max_stride=16):
    """Search for move IDs that appear near each other but not necessarily consecutive.

    Tries different strides (bytes between each u16 value).
    """
    results = []
    for stride in [2, 4, 6, 8, 12, 14, 16]:  # bytes between each value start
        for i in range(0, len(data) - len(values) * stride, 2):
            matches = 0
            for j, val in enumerate(values):
                offset = i + j * stride
                if offset + 2 > len(data):
                    break
                actual = struct.unpack_from('<H', data, offset)[0]
                if actual == val:
                    matches += 1
            if matches >= len(values):  # all must match
                addr = BASE_ADDR + i
                actual_vals = []
                for j in range(len(values)):
                    offset = i + j * stride
                    actual_vals.append(struct.unpack_from('<H', data, offset)[0])
                results.append((addr, stride, actual_vals))
    return results

def search_any_two_adjacent(data, moves, label):
    """Find any place where two of the given move IDs appear as adjacent u16 values."""
    results = []
    move_set = set(moves)
    for i in range(0, len(data) - 4, 2):
        v1 = struct.unpack_from('<H', data, i)[0]
        v2 = struct.unpack_from('<H', data, i+2)[0]
        if v1 in move_set and v2 in move_set and v1 != v2:
            addr = BASE_ADDR + i
            # Show context: 4 u16 values before and 4 after
            ctx_start = max(0, i - 8)
            ctx_end = min(len(data), i + 12)
            ctx = [struct.unpack_from('<H', data, j)[0] for j in range(ctx_start, ctx_end, 2)]
            results.append((addr, v1, v2, ctx))
    return results


with open(DUMP_FILE, 'rb') as f:
    data = f.read()

print(f"Loaded {len(data)} bytes from {DUMP_FILE}")
print(f"Address range: 0x{BASE_ADDR:08X} - 0x{BASE_ADDR + len(data):08X}")
print()

# Search 1: Consecutive u16 matches
print("=" * 60)
print("SEARCH 1: Consecutive u16 move IDs")
print("=" * 60)

for label, moves in [("Turtwig", TURTWIG_MOVES), ("Eevee", EEVEE_MOVES)]:
    results = search_consecutive_u16(data, moves, label, min_match=len(moves))
    print(f"\n{label} ({[f'{m}(0x{m:04X})' for m in moves]}):")
    if results:
        for addr, vals, matches in results:
            print(f"  0x{addr:08X}: {matches}/{len(moves)} match - values: {[f'0x{v:04X}({v})' for v in vals]}")
    else:
        print(f"  No consecutive matches found")

# Search 2: With gaps/stride
print()
print("=" * 60)
print("SEARCH 2: Move IDs with regular stride")
print("=" * 60)

for label, moves in [("Turtwig", TURTWIG_MOVES), ("Eevee", EEVEE_MOVES)]:
    results = search_with_gaps(data, moves, label)
    print(f"\n{label}:")
    if results:
        for addr, stride, vals in results[:20]:  # limit output
            print(f"  0x{addr:08X}: stride={stride} bytes - values: {[f'0x{v:04X}({v})' for v in vals]}")
    else:
        print(f"  No strided matches found")

# Search 3: Any two adjacent from same Pokemon's moveset
print()
print("=" * 60)
print("SEARCH 3: Any two adjacent move IDs from same moveset")
print("=" * 60)

for label, moves in [("Turtwig", [33, 110, 71]), ("Eevee", [39, 44, 343])]:
    # For Eevee, exclude Tackle(33) since Turtwig also has it - use unique moves
    results = search_any_two_adjacent(data, moves, label)
    print(f"\n{label} unique moves {moves}:")
    if results:
        for addr, v1, v2, ctx in results[:20]:
            print(f"  0x{addr:08X}: {v1}+{v2} context: {[f'0x{v:04X}' for v in ctx]}")
    else:
        print(f"  No adjacent pairs found")
