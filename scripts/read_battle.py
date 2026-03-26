#!/usr/bin/env python3
"""Read battle state directly from emulator memory.

Reads the live battle Pokemon data for all active battlers (player and enemy).
Works during battle only — outside of battle, all slots will be empty.

Structure layout (0xC0 = 192 bytes per battler, 4 slots):
  Slot 0: Player active    Slot 1: Enemy active
  Slot 2: Player partner    Slot 3: Enemy partner (doubles only)

Usage:
    python3 scripts/read_battle.py           # print battle state
    python3 scripts/read_battle.py --json    # output as JSON
"""

import sys
import os
import json
import struct

sys.path.insert(0, "/workspace/DesmumeMCP")
from desmume_mcp.client import connect

# --- Constants ---
BATTLE_BASE = 0x022C5774   # Slot 0 (player active)
BATTLE_SLOT_SIZE = 0xC0    # 192 bytes per battler
BATTLE_MAX_SLOTS = 4

# Field offsets within battle Pokemon structure
OFF_SPECIES = 0x00    # u16
OFF_ATK     = 0x02    # u16 (effective stat, after nature)
OFF_DEF     = 0x04    # u16
OFF_SPE     = 0x06    # u16
OFF_SPA     = 0x08    # u16
OFF_SPD     = 0x0A    # u16
OFF_MOVES   = 0x0C    # u16 × 4 (move IDs)
OFF_STAGES  = 0x18    # u8 × 8 (Atk,Def,Spe,SpA,SpD,Acc,Eva,Crit; neutral=6)
OFF_WEIGHT  = 0x20    # u16 (in 0.1 kg units)
OFF_ITEM    = 0x22    # u16 (held item ID)
OFF_TYPES   = 0x24    # u8 × 2 (type1, type2)
OFF_ABILITY = 0x27    # u8 (ability ID)
OFF_STATUS  = 0x28    # u32 (primary status condition bitfield)
OFF_PP      = 0x2C    # u8 × 4 (current PP for each move)
OFF_LEVEL   = 0x34    # u8
OFF_NICK    = 0x36    # Gen 4 text, FFFF terminated
OFF_CUR_HP  = 0x4C    # u16
OFF_MAX_HP  = 0x50    # u16
OFF_OT_NAME = 0x54    # Gen 4 text, FFFF terminated

# Gen 4 internal type IDs
TYPE_NAMES = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison",
    4: "Ground", 5: "Rock", 6: "Bug", 7: "Ghost", 8: "Steel",
    9: "???",
    10: "Fire", 11: "Water", 12: "Grass", 13: "Electric",
    14: "Psychic", 15: "Ice", 16: "Dragon", 17: "Dark",
}

# Status condition bitfield (Gen 4)
STATUS_SLEEP_MASK = 0x07    # bits 0-2: sleep counter (1-7)
STATUS_POISON     = 0x08    # bit 3
STATUS_BURN       = 0x10    # bit 4
STATUS_FREEZE     = 0x20    # bit 5
STATUS_PARALYSIS  = 0x40    # bit 6
STATUS_TOXIC      = 0x80    # bit 7

STAGE_NAMES = ["Atk", "Def", "Spe", "SpA", "SpD", "Acc", "Eva", "Crit"]

# Load lookup tables
SCRIPT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'data')

def _load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}

SPECIES_NAMES = _load_json('species_names.json')
MOVE_NAMES = _load_json('move_names.json')
ITEM_NAMES = _load_json('item_names.json')
ABILITY_NAMES = _load_json('ability_names.json')


def decode_gen4_text(data, offset, max_len=20):
    """Decode Gen 4 16-bit text encoding into a string."""
    chars = []
    for i in range(max_len):
        val = struct.unpack_from('<H', data, offset + i * 2)[0]
        if val == 0xFFFF:
            break
        # Uppercase A-Z
        if 0x012B <= val <= 0x0144:
            chars.append(chr(ord('A') + val - 0x012B))
        # Lowercase a-z
        elif 0x0145 <= val <= 0x015E:
            chars.append(chr(ord('a') + val - 0x0145))
        # Digits 0-9
        elif 0x0161 <= val <= 0x016A:
            chars.append(chr(ord('0') + val - 0x0161))
        elif val == 0x01DE:
            chars.append(' ')
        elif val == 0x0188:
            chars.append('é')
        elif val == 0x01AB:
            chars.append('!')
        elif val == 0x01AC:
            chars.append('?')
        elif val == 0x01AD:
            chars.append(',')
        elif val == 0x01AE:
            chars.append('.')
        elif val == 0x01B3:
            chars.append("'")
        elif val == 0x01C4:
            chars.append(':')
        elif val == 0x2467:
            chars.append('♂')
        elif val == 0x2469:
            chars.append('♀')
        else:
            chars.append(f'[{val:04X}]')
    return ''.join(chars)


def decode_status(status_val):
    """Decode Gen 4 status condition bitfield into a readable string."""
    if status_val == 0:
        return None
    conditions = []
    sleep = status_val & STATUS_SLEEP_MASK
    if sleep > 0:
        conditions.append(f"Sleep({sleep})")
    if status_val & STATUS_POISON:
        conditions.append("Poison")
    if status_val & STATUS_BURN:
        conditions.append("Burn")
    if status_val & STATUS_FREEZE:
        conditions.append("Freeze")
    if status_val & STATUS_PARALYSIS:
        conditions.append("Paralysis")
    if status_val & STATUS_TOXIC:
        conditions.append("Toxic")
    return ", ".join(conditions) if conditions else f"0x{status_val:08X}"


def read_battle(emu):
    """Read all battle slots and return list of battler dicts.

    Returns list of dicts (one per active battler), or empty list if not in battle.
    """
    total_size = BATTLE_MAX_SLOTS * BATTLE_SLOT_SIZE
    raw = emu.read_memory_range(BATTLE_BASE, size="byte", count=total_size)
    raw_bytes = bytes(raw)

    battlers = []
    for slot in range(BATTLE_MAX_SLOTS):
        offset = slot * BATTLE_SLOT_SIZE
        data = raw_bytes[offset:offset + BATTLE_SLOT_SIZE]

        species = struct.unpack_from('<H', data, OFF_SPECIES)[0]
        if species == 0:
            continue

        # Validate: detect stale/garbage data when not in battle
        level = data[OFF_LEVEL]
        max_hp = struct.unpack_from('<H', data, OFF_MAX_HP)[0]
        if species > 493 or level == 0 or level > 100 or max_hp == 0:
            continue

        cur_hp = struct.unpack_from('<H', data, OFF_CUR_HP)[0]

        # Stats
        atk = struct.unpack_from('<H', data, OFF_ATK)[0]
        df = struct.unpack_from('<H', data, OFF_DEF)[0]
        spe = struct.unpack_from('<H', data, OFF_SPE)[0]
        spa = struct.unpack_from('<H', data, OFF_SPA)[0]
        spd = struct.unpack_from('<H', data, OFF_SPD)[0]

        # Moves and PP
        moves = [struct.unpack_from('<H', data, OFF_MOVES + i * 2)[0] for i in range(4)]
        pp = [data[OFF_PP + i] for i in range(4)]

        # Stat stages (neutral = 6, range 0-12)
        stages_raw = list(data[OFF_STAGES:OFF_STAGES + 8])
        stages = {STAGE_NAMES[i]: stages_raw[i] - 6 for i in range(len(STAGE_NAMES))}

        # Types and ability
        type1 = data[OFF_TYPES]
        type2 = data[OFF_TYPES + 1]
        ability_id = data[OFF_ABILITY]

        # Status condition
        status = struct.unpack_from('<I', data, OFF_STATUS)[0]

        # Held item
        item_id = struct.unpack_from('<H', data, OFF_ITEM)[0]

        # Weight
        weight = struct.unpack_from('<H', data, OFF_WEIGHT)[0]

        # Nickname
        nickname = decode_gen4_text(data, OFF_NICK)

        side = "player" if slot in (0, 2) else "enemy"

        battler = {
            'slot': slot,
            'side': side,
            'species_id': species,
            'species': SPECIES_NAMES.get(species, f"#{species}"),
            'nickname': nickname,
            'level': level,
            'hp': cur_hp,
            'max_hp': max_hp,
            'stats': {'atk': atk, 'def': df, 'spa': spa, 'spd': spd, 'spe': spe},
            'moves': [
                {
                    'id': m,
                    'name': MOVE_NAMES.get(m, f"#{m}") if m > 0 else None,
                    'pp': pp[i],
                }
                for i, m in enumerate(moves) if m > 0
            ],
            'stages': {k: v for k, v in stages.items() if v != 0},
            'type1': TYPE_NAMES.get(type1, f"#{type1}"),
            'type2': TYPE_NAMES.get(type2, f"#{type2}"),
            'ability_id': ability_id,
            'ability': ABILITY_NAMES.get(ability_id, f"#{ability_id}"),
            'status': decode_status(status),
            'item_id': item_id,
            'item': ITEM_NAMES.get(item_id, None) if item_id > 0 else None,
            'weight_kg': weight / 10.0,
        }
        battlers.append(battler)

    return battlers


def format_battle(battlers):
    """Format battle state as a readable string."""
    if not battlers:
        return "Not in battle (no active battlers)."

    lines = ["=== Battle State ==="]

    for b in battlers:
        side_label = "YOUR" if b['side'] == 'player' else "ENEMY"
        nick = b['nickname']
        name = b['species']
        name_str = nick if nick == name else f"{nick} ({name})"

        # HP bar
        hp_pct = b['hp'] / b['max_hp'] * 100 if b['max_hp'] > 0 else 0
        bar_len = 20
        filled = int(hp_pct / 100 * bar_len)
        bar = '█' * filled + '░' * (bar_len - filled)

        lines.append(f"\n  [{side_label}] {name_str} Lv{b['level']}")
        lines.append(f"    HP: {b['hp']}/{b['max_hp']} [{bar}] {hp_pct:.0f}%")

        # Type
        type_str = b['type1']
        if b['type2'] != b['type1']:
            type_str += f"/{b['type2']}"
        lines.append(f"    Type: {type_str}  Ability: {b['ability']}")

        # Stats
        s = b['stats']
        lines.append(f"    Stats: Atk={s['atk']} Def={s['def']} SpA={s['spa']} SpD={s['spd']} Spe={s['spe']}")

        # Status
        if b['status']:
            lines.append(f"    Status: {b['status']}")

        # Held item
        if b['item']:
            lines.append(f"    Item: {b['item']}")

        # Stat stage changes
        if b['stages']:
            stage_parts = []
            for stat, val in b['stages'].items():
                sign = '+' if val > 0 else ''
                stage_parts.append(f"{stat}{sign}{val}")
            lines.append(f"    Stages: {', '.join(stage_parts)}")

        # Moves
        for m in b['moves']:
            lines.append(f"    - {m['name']} (PP {m['pp']})")

    return '\n'.join(lines)


def main():
    output_json = '--json' in sys.argv

    emu = connect()
    try:
        battlers = read_battle(emu)

        if output_json:
            print(json.dumps(battlers, indent=2))
        else:
            print(format_battle(battlers))
    finally:
        emu.close()


if __name__ == '__main__':
    main()
