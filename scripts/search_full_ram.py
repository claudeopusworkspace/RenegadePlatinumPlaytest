#!/usr/bin/env python3
"""Search full 4MB RAM for move ID occurrences.

Focus on unique move IDs that are unlikely false positives:
- Covet = 343 (0x0157) - very unique
- Withdraw = 110 (0x006E) - moderately unique
- Absorb = 71 (0x0047) - could be noise

Strategy: find all Covet(343) occurrences, then check nearby memory
for other Eevee moves (Tackle=33, Tail Whip=39, Bite=44).
"""

import struct
import os

DUMPS = [
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02000000.bin", 0x02000000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02100000.bin", 0x02100000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02200000.bin", 0x02200000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02300000.bin", 0x02300000),
]

# Combine all dumps into one buffer
full_ram = bytearray()
ram_base = 0x02000000
for path, base in DUMPS:
    with open(path, 'rb') as f:
        chunk = f.read()
        expected_offset = base - ram_base
        if len(full_ram) < expected_offset:
            full_ram.extend(b'\x00' * (expected_offset - len(full_ram)))
        full_ram.extend(chunk)

print(f"Total RAM loaded: {len(full_ram)} bytes (0x{ram_base:08X} - 0x{ram_base + len(full_ram):08X})")

def find_u16(data, value):
    """Find all offsets where u16 LE == value."""
    results = []
    needle = struct.pack('<H', value)
    pos = 0
    while True:
        pos = data.find(needle, pos)
        if pos == -1:
            break
        results.append(pos)
        pos += 2
    return results

def context_u16(data, offset, before=8, after=8):
    """Get surrounding u16 values for context."""
    start = max(0, offset - before * 2)
    end = min(len(data), offset + after * 2 + 2)
    vals = []
    for i in range(start, end, 2):
        v = struct.unpack_from('<H', data, i)[0]
        marker = " <<" if i == offset else ""
        vals.append(f"0x{v:04X}({v}){marker}")
    return vals

def context_u32(data, offset, before=4, after=4):
    """Get surrounding u32 values for context."""
    start = max(0, offset - before * 4)
    end = min(len(data), offset + after * 4 + 4)
    vals = []
    for i in range(start, end, 4):
        if i + 4 <= len(data):
            v = struct.unpack_from('<I', data, i)[0]
            marker = " <<" if i == offset or i == offset - 2 else ""
            vals.append(f"0x{v:08X}{marker}")
    return vals

# Search for Covet (343 = 0x0157) - most unique move ID
print("\n" + "=" * 70)
print("ALL occurrences of Covet (343 = 0x0157) as u16 in RAM")
print("=" * 70)

covet_offsets = find_u16(full_ram, 343)
print(f"Found {len(covet_offsets)} occurrences")
for off in covet_offsets:
    addr = ram_base + off
    ctx = context_u16(full_ram, off)
    print(f"\n  0x{addr:08X}:")
    print(f"    u16 context: {' | '.join(ctx)}")
    ctx32 = context_u32(full_ram, off)
    print(f"    u32 context: {' '.join(ctx32)}")

# For each Covet location, check if other Eevee moves are nearby (within 256 bytes)
EEVEE_MOVES = {33: "Tackle", 39: "Tail Whip", 44: "Bite", 343: "Covet"}
print("\n" + "=" * 70)
print("Checking near each Covet hit for other Eevee moves (within 256 bytes)")
print("=" * 70)

for off in covet_offsets:
    nearby = []
    for check_off in range(max(0, off - 256), min(len(full_ram) - 1, off + 256), 2):
        v = struct.unpack_from('<H', full_ram, check_off)[0]
        if v in EEVEE_MOVES and check_off != off:
            nearby.append((ram_base + check_off, v, EEVEE_MOVES[v]))
    if nearby:
        print(f"\n  Near Covet @ 0x{ram_base + off:08X}:")
        for a, v, name in nearby:
            print(f"    0x{a:08X}: {name} ({v})")

# Also search for Withdraw (110) - Turtwig-specific
print("\n" + "=" * 70)
print("ALL occurrences of Withdraw (110 = 0x006E) as u16")
print("=" * 70)

withdraw_offsets = find_u16(full_ram, 110)
print(f"Found {len(withdraw_offsets)} occurrences")

# Check which Withdraw locations have other Turtwig moves nearby
TURTWIG_MOVES = {33: "Tackle", 110: "Withdraw", 71: "Absorb"}
print("\nChecking near each Withdraw for other Turtwig moves (within 256 bytes)")

for off in withdraw_offsets:
    nearby = []
    for check_off in range(max(0, off - 256), min(len(full_ram) - 1, off + 256), 2):
        v = struct.unpack_from('<H', full_ram, check_off)[0]
        if v in TURTWIG_MOVES and check_off != off:
            nearby.append((ram_base + check_off, v, TURTWIG_MOVES[v]))
    if nearby:
        print(f"\n  Near Withdraw @ 0x{ram_base + off:08X}:")
        for a, v, name in nearby:
            print(f"    0x{a:08X}: {name} ({v})")
