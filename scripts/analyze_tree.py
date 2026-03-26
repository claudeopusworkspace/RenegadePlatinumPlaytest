#!/usr/bin/env python3
"""Analyze PokePara tree structure from memory dumps.

Reads the tree root and tries to follow pointer-based nodes,
printing each node's contents to reverse-engineer the format.
"""

import struct
import sys
import json
import os

# Load move names for identification
MOVE_NAMES = {}
move_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'move_names.json')
if os.path.exists(move_file):
    with open(move_file) as f:
        MOVE_NAMES = {int(k): v for k, v in json.load(f).items()}

SPECIES_NAMES = {}
sp_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'species_names.json')
if os.path.exists(sp_file):
    with open(sp_file) as f:
        SPECIES_NAMES = {int(k): v for k, v in json.load(f).items()}

# Full RAM dumps for pointer following
DUMPS = [
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02000000.bin", 0x02000000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02100000.bin", 0x02100000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02200000.bin", 0x02200000),
    ("/workspace/RenegadePlatinumPlaytest/dumps/ram_0x02300000.bin", 0x02300000),
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

def read_u8(addr):
    off = addr - RAM_BASE
    if 0 <= off < len(ram):
        return ram[off]
    return None

def read_u16(addr):
    off = addr - RAM_BASE
    if 0 <= off + 2 <= len(ram):
        return struct.unpack_from('<H', ram, off)[0]
    return None

def read_u32(addr):
    off = addr - RAM_BASE
    if 0 <= off + 4 <= len(ram):
        return struct.unpack_from('<I', ram, off)[0]
    return None

def is_ptr(val):
    """Check if a u32 value looks like a valid RAM pointer."""
    return 0x02000000 <= val < 0x02400000

def hexdump(addr, size=64):
    """Print hexdump of memory region."""
    off = addr - RAM_BASE
    for row in range(0, size, 16):
        if off + row >= len(ram):
            break
        hex_vals = []
        ascii_vals = []
        for col in range(16):
            idx = off + row + col
            if idx < len(ram):
                b = ram[idx]
                hex_vals.append(f"{b:02X}")
                ascii_vals.append(chr(b) if 32 <= b < 127 else '.')
            else:
                hex_vals.append("  ")
                ascii_vals.append(' ')
        hex_str = ' '.join(hex_vals[:8]) + '  ' + ' '.join(hex_vals[8:])
        print(f"  0x{addr + row:08X}: {hex_str}  |{''.join(ascii_vals)}|")

def annotate_u32_row(addr, count=8):
    """Print u32 values with pointer annotations."""
    for i in range(count):
        v = read_u32(addr + i * 4)
        if v is None:
            break
        annotation = ""
        if is_ptr(v):
            annotation = " -> PTR"
        elif v < 1000 and v > 0:
            if v in MOVE_NAMES:
                annotation = f" (move: {MOVE_NAMES[v]})"
            elif v in SPECIES_NAMES:
                annotation = f" (species: {SPECIES_NAMES[v]})"
        # Check u16 halves
        lo = v & 0xFFFF
        hi = (v >> 16) & 0xFFFF
        u16_note = ""
        if lo in MOVE_NAMES and lo > 0:
            u16_note += f" lo=move:{MOVE_NAMES[lo]}"
        if hi in MOVE_NAMES and hi > 0:
            u16_note += f" hi=move:{MOVE_NAMES[hi]}"
        if lo in SPECIES_NAMES and lo > 0:
            u16_note += f" lo=species:{SPECIES_NAMES[lo]}"
        print(f"    +{i*4:02X}: 0x{v:08X} ({v:>10d}){annotation}{u16_note}")

# Tree roots from summary structure
TURTWIG_ROOT = 0x022C33E4
EEVEE_ROOT = 0x022C3424

print("=" * 70)
print("PokePara Tree Analysis")
print("=" * 70)

for label, root in [("Turtwig", TURTWIG_ROOT), ("Eevee", EEVEE_ROOT)]:
    print(f"\n{'─' * 70}")
    print(f"{label} tree root: 0x{root:08X}")
    print(f"{'─' * 70}")

    # What's at the root pointer? It could be:
    # 1. A vtable pointer (C++ object)
    # 2. A node structure directly
    # Let's read the first 256 bytes
    print(f"\nRaw hexdump (256 bytes from root):")
    hexdump(root, 256)

    print(f"\nAs u32 values:")
    annotate_u32_row(root, 64)

    # Check if root starts with a vtable pointer
    vtable = read_u32(root)
    if vtable and is_ptr(vtable):
        print(f"\n  Root appears to start with pointer: 0x{vtable:08X}")
        print(f"  This might be a vtable or parent/root node pointer")

    # Look for the tree structure: scan for internal pointers
    print(f"\n  Pointer scan (addresses that look like RAM pointers):")
    for i in range(0, 256, 4):
        v = read_u32(root + i)
        if v and is_ptr(v):
            # Read what the pointer points to
            target_v = read_u32(v)
            target_str = f"-> 0x{target_v:08X}" if target_v is not None else "-> ???"
            print(f"    root+0x{i:02X}: 0x{v:08X} {target_str}")

print("\n" + "=" * 70)
print("Searching for move IDs near tree roots")
print("=" * 70)

# Search within 2KB of each root for known move IDs
for label, root, moves in [
    ("Turtwig", TURTWIG_ROOT, {33: "Tackle", 110: "Withdraw", 71: "Absorb"}),
    ("Eevee", EEVEE_ROOT, {33: "Tackle", 39: "Tail Whip", 44: "Bite", 343: "Covet"}),
]:
    print(f"\n{label} (root=0x{root:08X}):")
    off_base = root - RAM_BASE
    for i in range(0, 2048, 2):
        idx = off_base + i
        if idx + 2 > len(ram):
            break
        v = struct.unpack_from('<H', ram, idx)[0]
        if v in moves:
            addr = root + i
            # Show context
            ctx = []
            for j in range(-8, 12, 2):
                ci = idx + j
                if 0 <= ci + 2 <= len(ram):
                    cv = struct.unpack_from('<H', ram, ci)[0]
                    marker = "**" if j == 0 else "  "
                    ctx.append(f"{marker}0x{cv:04X}({cv})")
            print(f"  root+0x{i:04X} (0x{addr:08X}): {moves[v]} ({v})")
            print(f"    context: {' '.join(ctx)}")
