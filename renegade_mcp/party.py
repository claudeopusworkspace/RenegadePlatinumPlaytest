"""Read party Pokemon data from emulator memory.

Uses TWO data sources:
1. Encrypted Gen 4 party data at 0x0227E270 (always available) — species, moves, PP, nature, etc.
2. Party summary structure at 0x022C0130 (overworld only) — current HP, max HP, level.

When the checksum-encrypted blocks are stale (mid-update), falls back to:
- PID-encrypted extension for level, HP, and stats
- Unencrypted species array at 0x0227F3E8 for species (by elimination)
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import move_names, species_names

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Memory addresses ──
ENCRYPTED_PARTY_COUNT = 0x0227E26C
ENCRYPTED_PARTY_BASE = 0x0227E270
ENCRYPTED_SLOT_SIZE = 236
PARTY_SUMMARY_BASE = 0x022C0130
PARTY_SLOT_SIZE = 0x2C  # 44 bytes
PARTY_MAX_SLOTS = 6

# Unencrypted species array (catch-order, 8 bytes per entry, u16 species at offset 0)
SPECIES_ARRAY_BASE = 0x0227F3E8
SPECIES_ARRAY_STRIDE = 8

# Pause menu (for refresh sync)
PAUSE_CURSOR_ADDR = 0x0229FA28
POKEMON_MENU_INDEX = 1
PAUSE_MENU_SIZE = 7
MENU_WAIT = 300  # frames after major menu transitions
NAV_WAIT = 60    # frames after D-pad

# Summary field offsets
OFF_SPECIES = 0x04
OFF_CUR_HP = 0x06
OFF_MAX_HP = 0x08
OFF_LEVEL = 0x0A

# All 24 permutations of ABCD (block unshuffle table)
BLOCK_ORDERS = [
    [0, 1, 2, 3], [0, 1, 3, 2], [0, 2, 1, 3], [0, 2, 3, 1], [0, 3, 1, 2], [0, 3, 2, 1],
    [1, 0, 2, 3], [1, 0, 3, 2], [1, 2, 0, 3], [1, 2, 3, 0], [1, 3, 0, 2], [1, 3, 2, 0],
    [2, 0, 1, 3], [2, 0, 3, 1], [2, 1, 0, 3], [2, 1, 3, 0], [2, 3, 0, 1], [2, 3, 1, 0],
    [3, 0, 1, 2], [3, 0, 2, 1], [3, 1, 0, 2], [3, 1, 2, 0], [3, 2, 0, 1], [3, 2, 1, 0],
]

NATURES = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
]


# ── Gen 4 Decryption ──

def _prng_decrypt(data: bytes, seed: int) -> bytes:
    """Decrypt data using Gen 4 PRNG. Works for both checksum-seeded blocks and PID-seeded battle stats."""
    result = bytearray(len(data))
    state = seed
    for i in range(0, len(data), 2):
        state = (state * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        key = (state >> 16) & 0xFFFF
        val = struct.unpack_from("<H", data, i)[0]
        struct.pack_into("<H", result, i, val ^ key)
    return bytes(result)


def _unshuffle_blocks(data_128: bytes, pid: int) -> bytes:
    """Unshuffle 4x32-byte blocks into ABCD order based on PID."""
    order_idx = ((pid >> 13) & 0x1F) % 24
    order = BLOCK_ORDERS[order_idx]
    result = bytearray(128)
    for i, block in enumerate(order):
        result[block * 32 : (block + 1) * 32] = data_128[i * 32 : (i + 1) * 32]
    return bytes(result)


def _decode_encrypted_pokemon(raw_236: bytes) -> dict[str, Any] | None:
    """Decode a 236-byte encrypted Pokemon structure.

    Returns None if the slot is empty (PID=0).
    Returns partial data with "partial": True if checksum fails (stale blocks).
    """
    pid = struct.unpack_from("<I", raw_236, 0)[0]
    checksum = struct.unpack_from("<H", raw_236, 6)[0]
    encrypted = raw_236[8:136]

    if pid == 0:
        return None

    # Always decrypt the PID-encrypted extension (it's always valid)
    battle_ext = _prng_decrypt(raw_236[136:236], pid)
    ext_level = battle_ext[4]
    ext_cur_hp = struct.unpack_from("<H", battle_ext, 6)[0]
    ext_max_hp = struct.unpack_from("<H", battle_ext, 8)[0]

    nature_idx = pid % 25
    nature = NATURES[nature_idx]

    # Try to decrypt the checksum-encrypted blocks
    decrypted = _prng_decrypt(encrypted, checksum)

    calc_checksum = sum(
        struct.unpack_from("<H", decrypted, i)[0] for i in range(0, 128, 2)
    ) & 0xFFFF

    if calc_checksum != checksum:
        # Checksum mismatch — encrypted blocks are stale/mid-update.
        # Return what we can from the PID-encrypted extension.
        return {
            "pid": pid,
            "partial": True,
            "species_id": 0,  # will be deduced by elimination in read_party
            "item_id": 0,
            "exp": 0,
            "friendship": 0,
            "ability_idx": 0,
            "moves": [0, 0, 0, 0],
            "pp": [0, 0, 0, 0],
            "pp_ups": [0, 0, 0, 0],
            "nature": nature,
            "nature_idx": nature_idx,
            "ivs": {},
            "evs": {},
            "ext_level": ext_level,
            "ext_cur_hp": ext_cur_hp,
            "ext_max_hp": ext_max_hp,
        }

    blocks = _unshuffle_blocks(decrypted, pid)

    # Block A (Growth)
    species = struct.unpack_from("<H", blocks, 0)[0]
    item = struct.unpack_from("<H", blocks, 2)[0]
    exp = struct.unpack_from("<I", blocks, 8)[0]
    friendship = blocks[12]
    ability_idx = blocks[13]
    evs = {
        "hp": blocks[16], "atk": blocks[17], "def": blocks[18],
        "spe": blocks[19], "spa": blocks[20], "spd": blocks[21],
    }

    # Block B (Moves)
    moves = [struct.unpack_from("<H", blocks, 32 + i * 2)[0] for i in range(4)]
    pp = [blocks[40 + i] for i in range(4)]
    pp_ups = [blocks[44 + i] for i in range(4)]

    # Block B — IVs packed in u32 at offset 48
    iv_raw = struct.unpack_from("<I", blocks, 48)[0]
    ivs = {
        "hp": (iv_raw >> 0) & 0x1F,
        "atk": (iv_raw >> 5) & 0x1F,
        "def": (iv_raw >> 10) & 0x1F,
        "spe": (iv_raw >> 15) & 0x1F,
        "spa": (iv_raw >> 20) & 0x1F,
        "spd": (iv_raw >> 25) & 0x1F,
    }

    return {
        "pid": pid,
        "species_id": species,
        "item_id": item,
        "exp": exp,
        "friendship": friendship,
        "ability_idx": ability_idx,
        "moves": moves,
        "pp": pp,
        "pp_ups": pp_ups,
        "nature": nature,
        "nature_idx": nature_idx,
        "ivs": ivs,
        "evs": evs,
        "ext_level": ext_level,
        "ext_cur_hp": ext_cur_hp,
        "ext_max_hp": ext_max_hp,
    }


def _read_species_array(emu: EmulatorClient) -> list[int]:
    """Read the unencrypted species array (catch-order, not party-order)."""
    raw = emu.read_memory_range(
        SPECIES_ARRAY_BASE, size="byte", count=PARTY_MAX_SLOTS * SPECIES_ARRAY_STRIDE
    )
    data = bytes(raw)
    species = []
    for i in range(PARTY_MAX_SLOTS):
        sp = struct.unpack_from("<H", data, i * SPECIES_ARRAY_STRIDE)[0]
        if sp > 0 and sp <= 493:
            species.append(sp)
    return species


# ── Party Sync ──

def _refresh_party_data(emu: EmulatorClient) -> None:
    """Open and close the party screen to force re-encryption of party data.

    Must be called from the overworld with player control. Navigates:
    X (pause) → Pokemon → B (close party) → B (close pause).
    """
    # Open pause menu
    emu.press_buttons(["x"], frames=8)
    emu.advance_frames(MENU_WAIT)

    # Navigate to Pokemon
    cursor = emu.read_memory(PAUSE_CURSOR_ADDR, size="byte")
    diff = POKEMON_MENU_INDEX - cursor
    direction = "down" if diff > 0 else "up"
    for _ in range(abs(diff)):
        emu.press_buttons([direction], frames=8)
        emu.advance_frames(NAV_WAIT)

    # Open party screen (triggers re-encryption)
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(MENU_WAIT)

    # Close party screen
    emu.press_buttons(["b"], frames=8)
    emu.advance_frames(MENU_WAIT)

    # Close pause menu
    emu.press_buttons(["b"], frames=8)
    emu.advance_frames(MENU_WAIT)


# ── Party Reading ──

def read_party(emu: EmulatorClient, refresh: bool = False) -> list[dict[str, Any]]:
    """Read all party slots from memory. Returns list of Pokemon dicts.

    Args:
        refresh: If True, briefly open/close the party screen first to force
                 the game to re-encrypt party data. Guarantees full data
                 (moves, IVs, EVs) but requires overworld with player control.
                 If False (default), reads memory directly — may return partial
                 data for slots with stale encrypted blocks.
    """
    if refresh:
        _refresh_party_data(emu)
    sp_names = species_names()
    mv_names = move_names()

    enc_count_raw = emu.read_memory_range(ENCRYPTED_PARTY_COUNT, size="long", count=1)
    enc_party_count = min(enc_count_raw[0], PARTY_MAX_SLOTS)

    if enc_party_count == 0:
        return []

    enc_raw = emu.read_memory_range(
        ENCRYPTED_PARTY_BASE, size="byte", count=enc_party_count * ENCRYPTED_SLOT_SIZE
    )
    summary_raw = emu.read_memory_range(
        PARTY_SUMMARY_BASE, size="byte", count=PARTY_MAX_SLOTS * PARTY_SLOT_SIZE
    )

    # First pass: decode all slots
    decoded_slots = []
    for i in range(enc_party_count):
        enc_offset = i * ENCRYPTED_SLOT_SIZE
        enc_slot = bytes(enc_raw[enc_offset : enc_offset + ENCRYPTED_SLOT_SIZE])
        decoded_slots.append(_decode_encrypted_pokemon(enc_slot))

    # Deduce species for partial slots via species array elimination
    known_species: set[int] = set()
    for d in decoded_slots:
        if d and not d.get("partial") and d["species_id"] > 0:
            known_species.add(d["species_id"])

    has_partial = any(d and d.get("partial") for d in decoded_slots)
    if has_partial:
        all_species = _read_species_array(emu)
        remaining = [s for s in all_species if s not in known_species]

        for d in decoded_slots:
            if d and d.get("partial") and d["species_id"] == 0:
                if len(remaining) == 1:
                    d["species_id"] = remaining[0]
                    known_species.add(remaining[0])
                    remaining.clear()
                elif len(remaining) > 1:
                    # Multiple unknowns — take the first remaining as best guess
                    d["species_id"] = remaining.pop(0)
                    known_species.add(d["species_id"])

    # Second pass: build party list
    party = []
    for i, decoded in enumerate(decoded_slots):
        if not decoded:
            continue

        species = decoded["species_id"]
        if species == 0 and not decoded.get("partial"):
            continue

        name = sp_names.get(species, f"Pokemon#{species}") if species > 0 else "???"

        # Try HP/level from summary (valid in overworld only)
        summary_offset = i * PARTY_SLOT_SIZE
        summary_slot = bytes(summary_raw[summary_offset : summary_offset + PARTY_SLOT_SIZE])
        summary_species = struct.unpack_from("<H", summary_slot, OFF_SPECIES)[0]

        if summary_species == species and species > 0:
            cur_hp = struct.unpack_from("<H", summary_slot, OFF_CUR_HP)[0]
            max_hp = struct.unpack_from("<H", summary_slot, OFF_MAX_HP)[0]
            level = summary_slot[OFF_LEVEL]
        elif decoded.get("ext_level", 0) > 0:
            # Summary unavailable or species mismatch — use encrypted extension
            level = decoded["ext_level"]
            cur_hp = decoded["ext_cur_hp"]
            max_hp = decoded["ext_max_hp"]
        else:
            cur_hp = -1
            max_hp = -1
            level = -1

        partial = decoded.get("partial", False)

        pokemon: dict[str, Any] = {
            "slot": i + 1,
            "species_id": species,
            "name": name,
            "level": level,
            "hp": cur_hp,
            "max_hp": max_hp,
            "moves": decoded["moves"],
            "move_names": [
                mv_names.get(m, f"#{m}") if m > 0 else "-" for m in decoded["moves"]
            ],
            "pp": decoded["pp"],
            "nature": decoded["nature"],
            "item_id": decoded.get("item_id", 0),
            "friendship": decoded.get("friendship", 0),
            "exp": decoded.get("exp", 0),
            "ivs": decoded.get("ivs", {}),
            "evs": decoded.get("evs", {}),
        }
        if partial:
            pokemon["partial"] = True

        party.append(pokemon)

    return party


def format_party(party: list[dict[str, Any]]) -> str:
    """Format party data as a readable string."""
    if not party:
        return "Party is empty!"

    lines = [f"=== Party ({len(party)} Pokemon) ==="]
    for p in party:
        nature_str = f" ({p['nature']})" if p.get("nature", "?") != "?" else ""
        level_str = f"Lv{p['level']}" if p["level"] >= 0 else "Lv?"

        if p["hp"] >= 0 and p["max_hp"] > 0:
            hp_pct = p["hp"] / p["max_hp"] * 100
            filled = int(hp_pct / 100 * 20)
            bar = "\u2588" * filled + "\u2591" * (20 - filled)
            hp_str = f"HP {p['hp']}/{p['max_hp']} [{bar}]"
        else:
            hp_str = "HP ?/?"

        partial_tag = " [stale data]" if p.get("partial") else ""
        lines.append(f"  {p['slot']}. {p['name']} {level_str}{nature_str}  {hp_str}{partial_tag}")

        if p.get("partial"):
            lines.append("     (moves/IVs/EVs unavailable — encrypted data stale)")
        elif p.get("move_names"):
            for mname, pp in zip(p["move_names"], p["pp"]):
                if mname == "-":
                    continue
                lines.append(f"     - {mname} (PP {pp})")
        else:
            lines.append("     (moves unavailable)")

        ivs = p.get("ivs", {})
        evs = p.get("evs", {})
        if ivs and not p.get("partial"):
            iv_str = "/".join(str(ivs[s]) for s in ["hp", "atk", "def", "spa", "spd", "spe"])
            lines.append(f"     IVs: {iv_str} (HP/Atk/Def/SpA/SpD/Spe)")
        if evs and not p.get("partial") and any(evs[s] > 0 for s in evs):
            ev_str = "/".join(str(evs[s]) for s in ["hp", "atk", "def", "spa", "spd", "spe"])
            lines.append(f"     EVs: {ev_str}")

    return "\n".join(lines)
