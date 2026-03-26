#!/usr/bin/env python3
"""Read party Pokemon data directly from emulator memory.

Reads the party summary structure in RAM at 0x022C0130.
Each slot is 44 bytes (0x2C), up to 6 party members.

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

# Field offsets within each 44-byte summary entry
OFF_DATA_PTR  = 0x00  # pointer to full Pokemon data tree (4 bytes)
OFF_SPECIES   = 0x04  # u16 - National Dex number
OFF_CUR_HP    = 0x06  # u16
OFF_MAX_HP    = 0x08  # u16
OFF_LEVEL     = 0x0A  # u8
OFF_STATUS    = 0x0B  # u8 (tentative - need to confirm)
OFF_ITEM      = 0x0C  # u16 (tentative)
OFF_UNKNOWN_E = 0x0E  # u8 (same for all Pokemon - 0x07)
OFF_UNKNOWN_F = 0x0F  # u8 (varies)
OFF_EXTRA_PTR = 0x24  # pointer to display/sprite data (4 bytes)
OFF_FLAGS     = 0x28  # u32 (0x00000100 for occupied slots)

# Species name table (hardcoded essentials, will be replaced by NARC lookup)
SPECIES_NAMES = {
    1: "Bulbasaur", 4: "Charmander", 7: "Squirtle",
    25: "Pikachu", 133: "Eevee", 134: "Vaporeon", 135: "Jolteon",
    136: "Flareon", 196: "Espeon", 197: "Umbreon", 470: "Leafeon",
    471: "Glaceon",
    152: "Chikorita", 155: "Cyndaquil", 158: "Totodile",
    252: "Treecko", 255: "Torchic", 258: "Mudkip",
    387: "Turtwig", 388: "Grotle", 389: "Torterra",
    390: "Chimchar", 391: "Monferno", 392: "Infernape",
    393: "Piplup", 394: "Prinplup", 395: "Empoleon",
    396: "Starly", 397: "Staravia", 398: "Staraptor",
    399: "Bidoof", 400: "Bibarel",
    403: "Shinx", 404: "Luxio", 405: "Luxray",
    41: "Zubat", 63: "Abra", 66: "Machop",
    # Add more as needed
}

# Try to load full species names from decoded message data
SPECIES_NAMES_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'species_names.json')
if os.path.exists(SPECIES_NAMES_FILE):
    with open(SPECIES_NAMES_FILE) as f:
        _loaded = json.load(f)
        # Convert string keys to int
        SPECIES_NAMES = {int(k): v for k, v in _loaded.items()}


def read_party(emu):
    """Read all party slots and return list of Pokemon dicts."""
    # Read entire party summary block (6 slots × 44 bytes = 264 bytes)
    total_bytes = PARTY_MAX_SLOTS * PARTY_SLOT_SIZE
    raw = emu.read_memory_range(PARTY_SUMMARY_BASE, size="byte", count=total_bytes)

    party = []
    for i in range(PARTY_MAX_SLOTS):
        offset = i * PARTY_SLOT_SIZE
        slot_bytes = bytes(raw[offset:offset + PARTY_SLOT_SIZE])

        species = struct.unpack_from('<H', slot_bytes, OFF_SPECIES)[0]
        if species == 0:
            break  # Empty slot = end of party

        cur_hp = struct.unpack_from('<H', slot_bytes, OFF_CUR_HP)[0]
        max_hp = struct.unpack_from('<H', slot_bytes, OFF_MAX_HP)[0]
        level = slot_bytes[OFF_LEVEL]
        status_byte = slot_bytes[OFF_STATUS]
        item_id = struct.unpack_from('<H', slot_bytes, OFF_ITEM)[0]

        name = SPECIES_NAMES.get(species, f"Pokemon#{species}")

        pokemon = {
            'slot': i + 1,
            'species_id': species,
            'name': name,
            'level': level,
            'hp': cur_hp,
            'max_hp': max_hp,
            'status': status_byte,
            'item_id': item_id,
        }
        party.append(pokemon)

    return party


def format_party(party):
    """Format party data as a readable string."""
    if not party:
        return "Party is empty!"

    lines = [f"=== Party ({len(party)} Pokemon) ==="]
    for p in party:
        hp_pct = (p['hp'] / p['max_hp'] * 100) if p['max_hp'] > 0 else 0
        hp_bar_len = 20
        filled = int(hp_pct / 100 * hp_bar_len)
        bar = '█' * filled + '░' * (hp_bar_len - filled)

        status_str = ""
        if p['status'] != 0:
            status_str = f" [STATUS:{p['status']}]"

        item_str = ""
        if p['item_id'] != 0:
            item_str = f" @ Item#{p['item_id']}"

        lines.append(
            f"  {p['slot']}. {p['name']} Lv{p['level']}  "
            f"HP {p['hp']}/{p['max_hp']} [{bar}]{status_str}{item_str}"
        )

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
