#!/usr/bin/env python3
"""Read party Pokemon data directly from emulator memory.

Uses TWO data sources:
1. Party summary structure at 0x022C0130 (44 bytes/slot) for species, HP, level
2. Encrypted Gen 4 party data at 0x0227E26C for moves, PP, nature, ability, etc.

The encrypted data uses the standard Gen 4 format: PID + checksum + 4 shuffled/encrypted
32-byte blocks. Decryption uses a PRNG seeded by the checksum, and blocks are unshuffled
using ((PID >> 13) & 0x1F) % 24 as the permutation index.

Usage:
    python3 scripts/read_party.py           # print party summary
    python3 scripts/read_party.py --json    # output as JSON
"""

import sys
import os
import json
import struct

# Add DesmumeMCP to path (same as other scripts)
sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect

# --- Constants ---
PARTY_SUMMARY_BASE = 0x022C0130
PARTY_SLOT_SIZE = 0x2C  # 44 bytes
PARTY_MAX_SLOTS = 6

# Encrypted party data addresses
ENCRYPTED_PARTY_COUNT = 0x0227E26C
ENCRYPTED_PARTY_BASE = 0x0227E270
ENCRYPTED_SLOT_SIZE = 236  # Standard Gen 4 party structure

# Field offsets within the 44-byte summary entry
OFF_SPECIES   = 0x04  # u16 - National Dex number
OFF_CUR_HP    = 0x06  # u16
OFF_MAX_HP    = 0x08  # u16
OFF_LEVEL     = 0x0A  # u8

# Block order table: all 24 permutations of ABCD in lexicographic order
BLOCK_ORDERS = [
    [0,1,2,3],[0,1,3,2],[0,2,1,3],[0,2,3,1],[0,3,1,2],[0,3,2,1],
    [1,0,2,3],[1,0,3,2],[1,2,0,3],[1,2,3,0],[1,3,0,2],[1,3,2,0],
    [2,0,1,3],[2,0,3,1],[2,1,0,3],[2,1,3,0],[2,3,0,1],[2,3,1,0],
    [3,0,1,2],[3,0,2,1],[3,1,0,2],[3,1,2,0],[3,2,0,1],[3,2,1,0],
]

NATURES = [
    "Hardy","Lonely","Brave","Adamant","Naughty",
    "Bold","Docile","Relaxed","Impish","Lax",
    "Timid","Hasty","Serious","Jolly","Naive",
    "Modest","Mild","Quiet","Bashful","Rash",
    "Calm","Gentle","Sassy","Careful","Quirky",
]

# Load lookup tables
SCRIPT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'data')

SPECIES_NAMES = {}
sp_file = os.path.join(DATA_DIR, 'species_names.json')
if os.path.exists(sp_file):
    with open(sp_file) as f:
        SPECIES_NAMES = {int(k): v for k, v in json.load(f).items()}

MOVE_NAMES = {}
mv_file = os.path.join(DATA_DIR, 'move_names.json')
if os.path.exists(mv_file):
    with open(mv_file) as f:
        MOVE_NAMES = {int(k): v for k, v in json.load(f).items()}


# --- Gen 4 Decryption ---

def decrypt_data(data_128, checksum):
    """Decrypt 128 bytes of Pokemon data using Gen 4 PRNG seeded with checksum."""
    result = bytearray(128)
    state = checksum
    for i in range(0, 128, 2):
        state = (state * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        key = (state >> 16) & 0xFFFF
        val = struct.unpack_from('<H', data_128, i)[0]
        struct.pack_into('<H', result, i, val ^ key)
    return bytes(result)


def unshuffle_blocks(data_128, pid):
    """Unshuffle 4x32-byte blocks into ABCD order based on PID."""
    order_idx = ((pid >> 13) & 0x1F) % 24
    order = BLOCK_ORDERS[order_idx]
    result = bytearray(128)
    for i, block in enumerate(order):
        result[block * 32:(block + 1) * 32] = data_128[i * 32:(i + 1) * 32]
    return bytes(result)


def decode_encrypted_pokemon(raw_236):
    """Decode a 236-byte encrypted Pokemon structure.

    Returns dict with species, moves, PP, nature, ability, exp, friendship, item,
    or None if the data appears invalid.
    """
    pid = struct.unpack_from('<I', raw_236, 0)[0]
    checksum = struct.unpack_from('<H', raw_236, 6)[0]
    encrypted = raw_236[8:136]

    if pid == 0:
        return None

    # Decrypt and unshuffle
    decrypted = decrypt_data(encrypted, checksum)
    blocks = unshuffle_blocks(decrypted, pid)

    # Validate checksum
    calc_checksum = sum(struct.unpack_from('<H', decrypted, i)[0] for i in range(0, 128, 2)) & 0xFFFF
    if calc_checksum != checksum:
        return None

    # Block A (Growth) - offset 0
    species = struct.unpack_from('<H', blocks, 0)[0]
    item = struct.unpack_from('<H', blocks, 2)[0]
    ot_id = struct.unpack_from('<I', blocks, 4)[0]
    exp = struct.unpack_from('<I', blocks, 8)[0]
    friendship = blocks[12]
    ability_idx = blocks[13]

    # Block B (Moves) - offset 32
    moves = [struct.unpack_from('<H', blocks, 32 + i * 2)[0] for i in range(4)]
    pp = [blocks[40 + i] for i in range(4)]
    pp_ups = [blocks[44 + i] for i in range(4)]

    # Nature from PID
    nature_idx = pid % 25
    nature = NATURES[nature_idx]

    return {
        'pid': pid,
        'species_id': species,
        'item_id': item,
        'ot_id': ot_id,
        'exp': exp,
        'friendship': friendship,
        'ability_idx': ability_idx,
        'moves': moves,
        'pp': pp,
        'pp_ups': pp_ups,
        'nature': nature,
        'nature_idx': nature_idx,
    }


# --- Party Reading ---

def read_party(emu):
    """Read all party slots and return list of Pokemon dicts.

    Combines data from:
    1. Encrypted Gen 4 party data (moves, nature, species, etc.) — always available
    2. Party summary structure (HP, level) — available in overworld only

    During battle, the summary structure is zeroed out. In that case,
    the encrypted data is used as the sole source.
    """
    # Read encrypted party data (primary source for moves/nature)
    enc_count_raw = emu.read_memory_range(ENCRYPTED_PARTY_COUNT, size="long", count=1)
    enc_party_count = min(enc_count_raw[0], PARTY_MAX_SLOTS)

    if enc_party_count == 0:
        return []

    enc_raw = emu.read_memory_range(ENCRYPTED_PARTY_BASE, size="byte",
                                     count=enc_party_count * ENCRYPTED_SLOT_SIZE)

    # Read party summary (secondary source for current HP/level)
    summary_raw = emu.read_memory_range(PARTY_SUMMARY_BASE, size="byte",
                                         count=PARTY_MAX_SLOTS * PARTY_SLOT_SIZE)

    party = []
    for i in range(enc_party_count):
        # Decode encrypted data
        enc_offset = i * ENCRYPTED_SLOT_SIZE
        enc_slot = bytes(enc_raw[enc_offset:enc_offset + ENCRYPTED_SLOT_SIZE])
        decoded = decode_encrypted_pokemon(enc_slot)

        if not decoded or decoded['species_id'] == 0:
            continue

        species = decoded['species_id']
        name = SPECIES_NAMES.get(species, f"Pokemon#{species}")

        # Try to read HP/level from summary (more reliable for current state)
        summary_offset = i * PARTY_SLOT_SIZE
        summary_slot = bytes(summary_raw[summary_offset:summary_offset + PARTY_SLOT_SIZE])
        summary_species = struct.unpack_from('<H', summary_slot, OFF_SPECIES)[0]

        if summary_species == species:
            # Summary is valid — use it for HP/level
            cur_hp = struct.unpack_from('<H', summary_slot, OFF_CUR_HP)[0]
            max_hp = struct.unpack_from('<H', summary_slot, OFF_MAX_HP)[0]
            level = summary_slot[OFF_LEVEL]
        else:
            # Summary unavailable (battle, menu, etc.) — leave HP/level unknown
            cur_hp = -1
            max_hp = -1
            level = -1

        pokemon = {
            'slot': i + 1,
            'species_id': species,
            'name': name,
            'level': level,
            'hp': cur_hp,
            'max_hp': max_hp,
            'moves': decoded['moves'],
            'move_names': [MOVE_NAMES.get(m, f"#{m}") if m > 0 else "-"
                           for m in decoded['moves']],
            'pp': decoded['pp'],
            'nature': decoded['nature'],
            'item_id': decoded.get('item_id', 0),
            'friendship': decoded.get('friendship', 0),
            'exp': decoded.get('exp', 0),
        }
        party.append(pokemon)

    return party


def format_party(party):
    """Format party data as a readable string."""
    if not party:
        return "Party is empty!"

    lines = [f"=== Party ({len(party)} Pokemon) ==="]
    for p in party:
        nature_str = f" ({p['nature']})" if p.get('nature', '?') != '?' else ""
        level_str = f"Lv{p['level']}" if p['level'] >= 0 else "Lv?"

        if p['hp'] >= 0 and p['max_hp'] > 0:
            hp_pct = p['hp'] / p['max_hp'] * 100
            hp_bar_len = 20
            filled = int(hp_pct / 100 * hp_bar_len)
            bar = '█' * filled + '░' * (hp_bar_len - filled)
            hp_str = f"HP {p['hp']}/{p['max_hp']} [{bar}]"
        else:
            hp_str = "HP ?/?"

        lines.append(
            f"  {p['slot']}. {p['name']} {level_str}{nature_str}  {hp_str}"
        )

        # Show moves
        if p.get('move_names'):
            for j, (mname, pp) in enumerate(zip(p['move_names'], p['pp'])):
                if mname == "-":
                    continue
                lines.append(f"     - {mname} (PP {pp})")
        else:
            lines.append(f"     (moves unavailable)")

    return '\n'.join(lines)


def main():
    output_json = '--json' in sys.argv

    emu = connect()
    try:
        party = read_party(emu)

        if output_json:
            print(json.dumps(party, indent=2))
        else:
            print(format_party(party))
    finally:
        emu.close()


if __name__ == '__main__':
    main()
