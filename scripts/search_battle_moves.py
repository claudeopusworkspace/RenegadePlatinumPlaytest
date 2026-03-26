#!/usr/bin/env python3
"""Search battle RAM for move ID clusters.

Battle state: Turtwig Lv7 with Tackle(33), Withdraw(110), Absorb(71)
Wild Starly Lv4 with Tackle(33), Growl(45)

In battle, the game must have moves in a flat structure somewhere.
"""

import struct
import os

DUMPS = [
    ("/workspace/RenegadePlatinumPlaytest/dumps/battle_ram_0x02000000.bin", 0x02000000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/battle_ram_0x02100000.bin", 0x02100000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/battle_ram_0x02200000.bin", 0x02200000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/battle_ram_0x02300000.bin", 0x02300000),
]

RAM_BASE = 0x02000000
ram = bytearray()
for path, base in DUMPS:
    with open(path, 'rb') as f:
        chunk = f.read()
        expected = base - RAM_BASE
        if len(ram) < expected:
            ram.extend(b'\x00' * (expected - len(ram)))
        ram.extend(chunk)

print(f"Loaded {len(ram)} bytes")

# Strategy: Find all Withdraw(110) occurrences,
# then check if Tackle(33) and Absorb(71) are within 16 bytes
WITHDRAW = 110  # 0x006E
TACKLE = 33     # 0x0021
ABSORB = 71     # 0x0047

print("\n=== Locations where Withdraw(110), Tackle(33), and Absorb(71) all appear within 16 bytes ===\n")

needle = struct.pack('<H', WITHDRAW)
pos = 0
hits = []
while True:
    pos = ram.find(needle, pos)
    if pos == -1:
        break

    # Check 32-byte window centered on this Withdraw
    window_start = max(0, pos - 16)
    window_end = min(len(ram), pos + 18)

    found_tackle = False
    found_absorb = False
    tackle_pos = None
    absorb_pos = None

    for i in range(window_start, window_end - 1, 2):
        v = struct.unpack_from('<H', ram, i)[0]
        if v == TACKLE and i != pos:
            found_tackle = True
            tackle_pos = i
        if v == ABSORB and i != pos:
            found_absorb = True
            absorb_pos = i

    if found_tackle and found_absorb:
        addr = RAM_BASE + pos
        t_addr = RAM_BASE + tackle_pos
        a_addr = RAM_BASE + absorb_pos

        # Show context: 16 u16 values around this area
        ctx_start = max(0, min(pos, tackle_pos, absorb_pos) - 8)
        ctx_end = min(len(ram), max(pos, tackle_pos, absorb_pos) + 10)

        print(f"  MATCH! Withdraw @ 0x{addr:08X}, Tackle @ 0x{t_addr:08X}, Absorb @ 0x{a_addr:08X}")

        # Show wider context (32 u16 values)
        wide_start = max(0, ctx_start - 16)
        wide_end = min(len(ram), ctx_end + 32)
        print(f"  Context (0x{RAM_BASE + wide_start:08X}):")
        for row_off in range(wide_start, wide_end, 16):
            vals = []
            for col in range(0, 16, 2):
                idx = row_off + col
                if idx + 2 <= len(ram):
                    v = struct.unpack_from('<H', ram, idx)[0]
                    a = RAM_BASE + idx
                    marker = ""
                    if idx == pos: marker = "*W"
                    elif idx == tackle_pos: marker = "*T"
                    elif idx == absorb_pos: marker = "*A"
                    vals.append(f"{'  ' if not marker else marker}{v:5d}(0x{v:04X})")
            print(f"    0x{RAM_BASE + row_off:08X}: {' '.join(vals)}")
        print()
        hits.append((addr, t_addr, a_addr))

    pos += 2

print(f"Total clusters found: {len(hits)}")

# Also check: search for the exact byte pattern 21 00 6E 00 47 00
# (Tackle, Withdraw, Absorb as consecutive u16 LE)
print("\n=== Exact consecutive pattern: Tackle(33), Withdraw(110), Absorb(71) ===")
pattern1 = struct.pack('<HHH', 33, 110, 71)
pos = ram.find(pattern1)
while pos != -1:
    print(f"  Found at 0x{RAM_BASE + pos:08X}")
    pos = ram.find(pattern1, pos + 2)

# Try all permutations
import itertools
print("\n=== Any permutation of {33, 110, 71} as consecutive u16 ===")
for perm in itertools.permutations([33, 110, 71]):
    pattern = struct.pack('<HHH', *perm)
    pos = ram.find(pattern)
    while pos != -1:
        print(f"  {perm} at 0x{RAM_BASE + pos:08X}")
        pos = ram.find(pattern, pos + 2)

# Try with an empty 4th move: pattern 33, 110, 71, 0
print("\n=== Pattern with empty 4th slot: Tackle, Withdraw, Absorb, 0 ===")
for perm in itertools.permutations([33, 110, 71]):
    pattern = struct.pack('<HHHH', *perm, 0)
    pos = ram.find(pattern)
    while pos != -1:
        print(f"  {perm}+0 at 0x{RAM_BASE + pos:08X}")
        pos = ram.find(pattern, pos + 2)
