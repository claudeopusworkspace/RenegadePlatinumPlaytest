#!/usr/bin/env python3
"""Map out the 240-byte Pokemon data structure found in battle RAM.

Known anchors:
- Turtwig moves at 0x022C0CCC (battle state)
- Eevee moves at 0x022C0DBC (battle state, +0xF0 from Turtwig)
- Structure size: 0xF0 = 240 bytes per Pokemon

This script reads the full structure from the emulator and annotates every field.
"""

import sys
import struct
import json
import os

sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect

# Load lookup tables
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

# Gen 4 text decoding
def decode_gen4_char(val):
    if val == 0xFFFF: return '[END]'
    if val == 0x01DE: return ' '
    if 0x012B <= val <= 0x0144: return chr(ord('A') + val - 0x012B)
    if 0x0145 <= val <= 0x015E: return chr(ord('a') + val - 0x0145)
    if 0x0161 <= val <= 0x016A: return chr(ord('0') + val - 0x0161)
    if 0x0121 <= val <= 0x012A: return chr(ord('0') + val - 0x0121)
    if val == 0x0188: return 'é'
    if val == 0x01AB: return '!'
    if val == 0x01AC: return '?'
    if val == 0x01AD: return ','
    if val == 0x01AE: return '.'
    if val == 0x01B3: return "'"
    return f'[0x{val:04X}]'

def decode_gen4_text(data, offset, max_chars=16):
    text = ""
    for i in range(max_chars):
        val = struct.unpack_from('<H', data, offset + i*2)[0]
        if val == 0xFFFF:
            break
        text += decode_gen4_char(val)
    return text

# Moves at known offsets within the 240-byte struct:
# - From dump analysis: moves start at offset 0x022C0CCC relative to structure base
# - Species at 0x022C0CB6
# - Need to find structure base

# Let's compute: if moves are at 0x022C0CCC and structure spacing is 0xF0,
# we need to find the base. Let's just read a big region and analyze both slots.

# Read starting well before the moves area
BASE_REGION = 0x022C0C00  # Start reading here
REGION_SIZE = 0x200       # 512 bytes covers both slots

emu = connect()
try:
    raw = emu.read_memory_range(BASE_REGION, size="byte", count=REGION_SIZE)
    data = bytes(raw)

    for slot in range(2):
        slot_name = "Turtwig" if slot == 0 else "Eevee"
        # Moves are at known addresses. Work backwards from moves.
        # Turtwig moves at 0x022C0CCC, Eevee at 0x022C0DBC
        moves_addr = 0x022C0CCC + slot * 0xF0
        moves_off = moves_addr - BASE_REGION

        print(f"\n{'=' * 70}")
        print(f"Slot {slot + 1}: {slot_name}")
        print(f"Moves at 0x{moves_addr:08X} (region offset 0x{moves_off:03X})")
        print(f"{'=' * 70}")

        # Read the full 240-byte structure around this
        # Moves are somewhere in the middle. Let's go back to find species.
        # Species is at moves_off - 0x16 = moves_off - 22
        species_off = moves_off - 22

        # Let's show the full area from species-32 to moves+48
        print(f"\n--- Bytes from species-64 to moves+64 ---")
        start = max(0, species_off - 64)
        end = min(len(data), moves_off + 64)

        for row in range(start, end, 16):
            hex_vals = []
            for col in range(16):
                idx = row + col
                if idx < len(data):
                    hex_vals.append(f"{data[idx]:02X}")
                else:
                    hex_vals.append("  ")
            addr = BASE_REGION + row
            hex_str = ' '.join(hex_vals[:8]) + '  ' + ' '.join(hex_vals[8:])
            print(f"  0x{addr:08X}: {hex_str}")

        # Annotate known fields
        print(f"\n--- Field annotations ---")

        # Species (u16 at moves_off - 22)
        if species_off >= 0 and species_off + 2 <= len(data):
            sp = struct.unpack_from('<H', data, species_off)[0]
            print(f"  [off -22] 0x{BASE_REGION + species_off:08X}: Species = {sp} ({SPECIES_NAMES.get(sp, '?')})")

        # What's at off -24 and -20?
        for doff in range(-32, 0, 2):
            off = moves_off + doff
            if 0 <= off + 2 <= len(data):
                v = struct.unpack_from('<H', data, off)[0]
                print(f"  [off {doff:+3d}] 0x{BASE_REGION + off:08X}: u16 = {v} (0x{v:04X})")

        # Moves (u16 × 4)
        for i in range(4):
            off = moves_off + i * 2
            if off + 2 <= len(data):
                mv = struct.unpack_from('<H', data, off)[0]
                name = MOVE_NAMES.get(mv, "empty" if mv == 0 else f"???")
                print(f"  [off +{i*2:2d}] 0x{BASE_REGION + off:08X}: Move{i+1} = {mv} ({name})")

        # Current PP (u16 × 4)
        for i in range(4):
            off = moves_off + 8 + i * 2
            if off + 2 <= len(data):
                pp = struct.unpack_from('<H', data, off)[0]
                print(f"  [off +{8+i*2:2d}] 0x{BASE_REGION + off:08X}: CurPP{i+1} = {pp}")

        # Max PP (u16 × 4)
        for i in range(4):
            off = moves_off + 16 + i * 2
            if off + 2 <= len(data):
                pp = struct.unpack_from('<H', data, off)[0]
                print(f"  [off +{16+i*2:2d}] 0x{BASE_REGION + off:08X}: MaxPP{i+1} = {pp}")

        # Nickname (after max PP, at offset +24)
        nick_off = moves_off + 24
        if nick_off + 20 <= len(data):
            name = decode_gen4_text(data, nick_off)
            chars = [struct.unpack_from('<H', data, nick_off + i*2)[0] for i in range(8)]
            print(f"  [off +24] 0x{BASE_REGION + nick_off:08X}: Nickname = \"{name}\" raw={[f'0x{c:04X}' for c in chars]}")

        # After nickname, look for more data
        for doff in range(40, 80, 2):
            off = moves_off + doff
            if off + 2 <= len(data):
                v = struct.unpack_from('<H', data, off)[0]
                note = ""
                if v in SPECIES_NAMES: note = f" (species: {SPECIES_NAMES[v]})"
                if v in MOVE_NAMES and v > 0: note = f" (move: {MOVE_NAMES[v]})"
                if v == 0xFFFF: note = " (END/unused)"
                print(f"  [off +{doff:2d}] 0x{BASE_REGION + off:08X}: u16 = {v} (0x{v:04X}){note}")

finally:
    emu.close()
