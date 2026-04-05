"""Read live battle state from emulator memory.

Reads 4 battle slots (player active, enemy active, player partner, enemy partner)
from 0x022C5774. Each slot is 0xC0 (192) bytes.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import ability_names, item_names, move_data, move_names, species_names
from renegade_mcp.text_encoding import decode_gen4_text

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Memory layout ──
BATTLE_BASE = 0x022C5774
BATTLE_SLOT_SIZE = 0xC0  # 192 bytes
BATTLE_MAX_SLOTS = 4

# battleEndFlag lives in BattleContext, after battleMons + move/damage arrays.
# Offset from BATTLE_BASE (start of battleMons): 4*0xC0 + 0xDF = 0x3DF.
# Source: pret/pokeplatinum BattleContext struct — set to 1 when battle ends,
# 0 when battle is active. Stale battle RAM persists after battle (especially
# tag battles with partner data in slot 2), so this flag gates read_battle.
BATTLE_END_FLAG = BATTLE_BASE + 0x3DF  # 0x022C5B53

# Field offsets within BattleMon struct (from pret/pokeplatinum decomp)
OFF_SPECIES = 0x00
OFF_ATK = 0x02
OFF_DEF = 0x04
OFF_SPE = 0x06
OFF_SPA = 0x08
OFF_SPD = 0x0A
OFF_MOVES = 0x0C
OFF_STAGES = 0x18
OFF_WEIGHT = 0x20
OFF_TYPES = 0x24
OFF_ABILITY = 0x27
OFF_ABILITY_FLAGS = 0x28  # ability announcement bitfield (intimidate, trace, etc.)
OFF_PP = 0x2C
OFF_LEVEL = 0x34
OFF_NICK = 0x36
OFF_CUR_HP = 0x4C
OFF_MAX_HP = 0x50
OFF_STATUS = 0x6C  # non-volatile status (sleep/poison/burn/freeze/paralysis/toxic)
OFF_ITEM = 0x78

# Gen 4 internal type IDs
TYPE_NAMES = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison",
    4: "Ground", 5: "Rock", 6: "Bug", 7: "Ghost", 8: "Steel",
    9: "Fairy",
    10: "Fire", 11: "Water", 12: "Grass", 13: "Electric",
    14: "Psychic", 15: "Ice", 16: "Dragon", 17: "Dark",
}

# Status condition bitfield
STATUS_SLEEP_MASK = 0x07
STATUS_POISON = 0x08
STATUS_BURN = 0x10
STATUS_FREEZE = 0x20
STATUS_PARALYSIS = 0x40
STATUS_TOXIC = 0x80

STAGE_NAMES = ["Atk", "Def", "Spe", "SpA", "SpD", "Acc", "Eva"]


def _decode_status(status_val: int) -> str | None:
    """Decode Gen 4 status condition bitfield."""
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


def read_battle(emu: EmulatorClient) -> list[dict[str, Any]]:
    """Read all battle slots. Returns list of battler dicts, or empty if not in battle."""
    # Check battleEndFlag first — if nonzero, battle RAM is stale
    end_flag = emu.read_memory_range(BATTLE_END_FLAG, size="byte", count=1)
    if end_flag[0] != 0:
        return []

    sp_names = species_names()
    mv_names = move_names()
    mv_data = move_data()
    it_names = item_names()
    ab_names = ability_names()

    total_size = BATTLE_MAX_SLOTS * BATTLE_SLOT_SIZE
    raw = emu.read_memory_range(BATTLE_BASE, size="byte", count=total_size)
    raw_bytes = bytes(raw)

    battlers = []
    for slot in range(BATTLE_MAX_SLOTS):
        offset = slot * BATTLE_SLOT_SIZE
        data = raw_bytes[offset : offset + BATTLE_SLOT_SIZE]

        species = struct.unpack_from("<H", data, OFF_SPECIES)[0]
        if species == 0:
            continue

        level = data[OFF_LEVEL]
        max_hp = struct.unpack_from("<H", data, OFF_MAX_HP)[0]
        cur_hp = struct.unpack_from("<H", data, OFF_CUR_HP)[0]
        if species > 493 or level == 0 or level > 100 or max_hp == 0 or cur_hp > max_hp:
            continue

        atk = struct.unpack_from("<H", data, OFF_ATK)[0]
        df = struct.unpack_from("<H", data, OFF_DEF)[0]
        spe = struct.unpack_from("<H", data, OFF_SPE)[0]
        spa = struct.unpack_from("<H", data, OFF_SPA)[0]
        spd = struct.unpack_from("<H", data, OFF_SPD)[0]

        moves = [struct.unpack_from("<H", data, OFF_MOVES + i * 2)[0] for i in range(4)]
        pp = [data[OFF_PP + i] for i in range(4)]

        # statBoosts[0] is HP (unused in battle), so skip it — Atk starts at +1
        stages_raw = list(data[OFF_STAGES + 1 : OFF_STAGES + 1 + len(STAGE_NAMES)])
        stages = {STAGE_NAMES[i]: stages_raw[i] - 6 for i in range(len(STAGE_NAMES))}

        type1 = data[OFF_TYPES]
        type2 = data[OFF_TYPES + 1]
        ability_id = data[OFF_ABILITY]
        status = struct.unpack_from("<I", data, OFF_STATUS)[0]
        item_id = struct.unpack_from("<H", data, OFF_ITEM)[0]
        weight = struct.unpack_from("<H", data, OFF_WEIGHT)[0]
        nickname = decode_gen4_text(data, OFF_NICK)

        side = "player" if slot in (0, 2) else "enemy"

        battler = {
            "slot": slot,
            "side": side,
            "species": sp_names.get(species, f"#{species}"),
            "nickname": nickname,
            "level": level,
            "hp": cur_hp,
            "max_hp": max_hp,
            "stats": {"atk": atk, "def": df, "spa": spa, "spd": spd, "spe": spe},
            "moves": [
                {
                    "id": m,
                    "name": mv_names.get(m, f"#{m}") if m > 0 else None,
                    "pp": pp[i],
                    "type": mv_data[m]["type"] if m in mv_data else None,
                    "power": mv_data[m]["power"] if m in mv_data else None,
                    "accuracy": mv_data[m]["accuracy"] if m in mv_data else None,
                    "class": mv_data[m]["class"] if m in mv_data else None,
                }
                for i, m in enumerate(moves)
                if m > 0
            ],
            "stages": {k: v for k, v in stages.items() if v != 0},
            "type1": TYPE_NAMES.get(type1, f"#{type1}"),
            "type2": TYPE_NAMES.get(type2, f"#{type2}"),
            "ability": ab_names.get(ability_id, f"#{ability_id}"),
            "status": _decode_status(status),
            "item": it_names.get(item_id, None) if item_id > 0 else None,
        }
        battlers.append(battler)

    return battlers


def _format_move_detail(m: dict) -> str:
    """Format move type/class/power/accuracy as a bracketed tag."""
    mtype = m.get("type")
    if not mtype:
        return ""
    parts = [mtype, m.get("class", "???")]
    power = m.get("power")
    if power:
        parts.append(f"{power} pwr")
    acc = m.get("accuracy")
    if acc:
        parts.append(f"{acc}% acc")
    return f" [{' · '.join(parts)}]"


def battle_summary(battlers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a trimmed battle state with only strategically relevant fields.

    Designed for embedding in battle_turn responses — enough info for turn-to-turn
    decisions without the full read_battle bloat.

    Includes: species, level, hp, types, status, stat stages, moves (name+pp).
    Enemy side also gets ability and item.
    Drops: all IDs, weight, nickname (when same as species), move metadata
    (type/power/accuracy/class), full stats dict.
    """
    summary = []
    for b in battlers:
        entry: dict[str, Any] = {
            "slot": b["slot"],
            "side": b["side"],
            "species": b["species"],
            "level": b["level"],
            "hp": f"{b['hp']}/{b['max_hp']}",
            "types": b["type1"] if b["type1"] == b["type2"] else f"{b['type1']}/{b['type2']}",
        }

        # Nickname only when different from species
        if b.get("nickname") and b["nickname"] != b["species"]:
            entry["nickname"] = b["nickname"]

        if b.get("status"):
            entry["status"] = b["status"]

        # Non-zero stat stages only
        if b.get("stages"):
            entry["stages"] = b["stages"]

        # Moves: name + PP only
        entry["moves"] = [
            {"name": m["name"], "pp": m["pp"]}
            for m in b.get("moves", [])
            if m.get("name")
        ]

        # Enemy gets ability + item (critical for strategy)
        if b["side"] == "enemy":
            if b.get("ability"):
                entry["ability"] = b["ability"]
            if b.get("item"):
                entry["item"] = b["item"]

        summary.append(entry)
    return summary


def format_battle(battlers: list[dict[str, Any]]) -> str:
    """Format battle state as a readable string."""
    if not battlers:
        return "Not in battle (no active battlers)."

    lines = ["=== Battle State ==="]

    for b in battlers:
        side_label = "YOUR" if b["side"] == "player" else "ENEMY"
        nick = b["nickname"]
        name = b["species"]
        name_str = nick if nick == name else f"{nick} ({name})"

        hp_pct = b["hp"] / b["max_hp"] * 100 if b["max_hp"] > 0 else 0
        filled = int(hp_pct / 100 * 20)
        bar = "\u2588" * filled + "\u2591" * (20 - filled)

        lines.append(f"\n  [{side_label}] {name_str} Lv{b['level']}")
        lines.append(f"    HP: {b['hp']}/{b['max_hp']} [{bar}] {hp_pct:.0f}%")

        type_str = b["type1"]
        if b["type2"] != b["type1"]:
            type_str += f"/{b['type2']}"
        lines.append(f"    Type: {type_str}  Ability: {b['ability']}")

        s = b["stats"]
        lines.append(f"    Stats: Atk={s['atk']} Def={s['def']} SpA={s['spa']} SpD={s['spd']} Spe={s['spe']}")

        if b["status"]:
            lines.append(f"    Status: {b['status']}")

        if b["item"]:
            lines.append(f"    Item: {b['item']}")

        if b["stages"]:
            stage_parts = []
            for stat, val in b["stages"].items():
                sign = "+" if val > 0 else ""
                stage_parts.append(f"{stat}{sign}{val}")
            lines.append(f"    Stages: {', '.join(stage_parts)}")

        for m in b["moves"]:
            detail = _format_move_detail(m)
            lines.append(f"    - {m['name']}{detail} (PP {m['pp']})")

    return "\n".join(lines)
