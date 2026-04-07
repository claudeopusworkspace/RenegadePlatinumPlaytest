"""Read party Pokemon data from emulator memory.

Reads Gen 4 party data at 0x0227E270 — each slot is 236 bytes containing:
  - Data blocks (bytes 8-135): species, moves, IVs, EVs, ability, nature, etc.
  - Party extension (bytes 136-235): level, HP, maxHP, calculated stats.

The game encrypts party data in RAM and temporarily decrypts in-place when
accessing it (party screen, battle init, etc.). Flags at offset 0x004 of each
slot track the current encryption state:
  - bit 0: partyDecrypted (party extension is plaintext)
  - bit 1: boxDecrypted   (data blocks are plaintext)

We auto-detect the actual encryption state using a three-tier approach:
  1. Try the flag-indicated state, then the opposite (handles normal + transient
     mid-GetValue states where the game decrypts without setting flags).
  2. If neither validates, try mixed-state split-point recovery. Frame boundaries
     can land mid-loop inside Pokemon_DecryptData/EncryptData, leaving the first
     K words in one state and the rest in the other. Since the PRNG keystream is
     deterministic (seeded by checksum), we sweep all 126 possible split points
     and validate each against the checksum to recover the correct plaintext.
  3. The block recovery direction also infers the extension state: mid-decrypt
     means the extension is plaintext, mid-encrypt means it's encrypted.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import ability_names, move_data, move_names, species_names

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Memory layout constants (struct-internal, no shift) ──
ENCRYPTED_SLOT_SIZE = 236
PARTY_MAX_SLOTS = 6
SPECIES_ARRAY_STRIDE = 8

# All 24 permutations of ABCD (block unshuffle table)
BLOCK_ORDERS = [
    [0, 1, 2, 3], [0, 1, 3, 2], [0, 2, 1, 3], [0, 2, 3, 1], [0, 3, 1, 2], [0, 3, 2, 1],
    [1, 0, 2, 3], [1, 0, 3, 2], [1, 2, 0, 3], [1, 2, 3, 0], [1, 3, 0, 2], [1, 3, 2, 0],
    [2, 0, 1, 3], [2, 0, 3, 1], [2, 1, 0, 3], [2, 1, 3, 0], [2, 3, 0, 1], [2, 3, 1, 0],
    [3, 0, 1, 2], [3, 0, 2, 1], [3, 1, 0, 2], [3, 1, 2, 0], [3, 2, 0, 1], [3, 2, 1, 0],
]

# ── Status condition bitfield (party extension offset 0x00) ──
STATUS_SLEEP_MASK = 0x07
STATUS_POISON = 0x08
STATUS_BURN = 0x10
STATUS_FREEZE = 0x20
STATUS_PARALYSIS = 0x40
STATUS_TOXIC = 0x80


def decode_status_conditions(status_val: int) -> list[str]:
    """Decode Gen 4 status condition bitfield into a list of condition names."""
    if status_val == 0:
        return []
    conditions = []
    if status_val & STATUS_SLEEP_MASK:
        conditions.append("Sleep")
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
    return conditions


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


def _checksum_blocks(data: bytes, checksum: int) -> bool:
    """Validate that decrypted block data matches the stored checksum."""
    calc = sum(
        struct.unpack_from("<H", data, i)[0] for i in range(0, 128, 2)
    ) & 0xFFFF
    return calc == checksum


def _resolve_block_encryption(
    block_data: bytes, checksum: int, flag_says_decrypted: bool
) -> tuple[bytes | None, str]:
    """Determine the actual encryption state of data blocks and return decrypted data.

    Three-tier resolution:
      1. Try flag-indicated state, then opposite (handles normal + transient GetValue).
      2. If neither validates, try mixed-state recovery — the frame boundary may have
         landed mid-loop inside Pokemon_DecryptData/EncryptData, leaving the first K
         words in one state and the rest in the other.

    Returns (decrypted_data, method):
      - "decrypted": data was already plaintext
      - "encrypted": data was encrypted, now decrypted
      - "mid_decrypt": recovered from mid-decryption split (ext is plaintext)
      - "mid_encrypt": recovered from mid-encryption split (ext is encrypted)
      - (None, "failed"): unrecoverable
    """
    if flag_says_decrypted:
        if _checksum_blocks(block_data, checksum):
            return block_data, "decrypted"
        attempt = _prng_decrypt(block_data, checksum)
        if _checksum_blocks(attempt, checksum):
            return attempt, "encrypted"
    else:
        attempt = _prng_decrypt(block_data, checksum)
        if _checksum_blocks(attempt, checksum):
            return attempt, "encrypted"
        if _checksum_blocks(block_data, checksum):
            return block_data, "decrypted"

    # Neither full interpretation valid — try mixed-state split-point recovery
    recovered = _try_mixed_state_recovery(block_data, checksum)
    if recovered is not None:
        return recovered

    return None, "failed"


def _try_mixed_state_recovery(
    block_data: bytes, checksum: int
) -> tuple[bytes, str] | None:
    """Recover blocks caught mid-encrypt/decrypt by finding the split point.

    The game's PRNG XOR loop in Pokemon_DecryptData / Pokemon_EncryptData
    processes u16 words sequentially. If the frame boundary landed mid-loop,
    words 0..K-1 are in one encryption state and words K..63 in the other.

    We know the full PRNG keystream (seeded by checksum), so we can try all
    126 possible split points (63 mid-decrypt + 63 mid-encrypt) and validate
    each candidate against the checksum. Only the correct split validates.

    Returns (decrypted_bytes, direction) or None.
    direction is "mid_decrypt" (ext is plaintext) or "mid_encrypt" (ext is encrypted).
    """
    # Pre-compute PRNG keystream (same algorithm as _prng_decrypt)
    keystream: list[int] = []
    state = checksum
    for _ in range(64):
        state = (state * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        keystream.append((state >> 16) & 0xFFFF)

    # Read raw u16 words from block data
    raw = [struct.unpack_from("<H", block_data, i * 2)[0] for i in range(64)]

    # Compute fully-decrypted version (XOR each word with its keystream value)
    decrypted = [raw[i] ^ keystream[i] for i in range(64)]

    # ── Mid-decryption: words 0..K-1 already plain, K..63 still encrypted ──
    # Fully-decrypted candidate = raw[:K] + decrypted[K:]
    # Use incremental checksum starting from all-decrypted (K=0, already tried)
    running = sum(decrypted)
    for k in range(1, 64):
        running += raw[k - 1] - decrypted[k - 1]
        if (running & 0xFFFF) == checksum:
            words = raw[:k] + decrypted[k:]
            return _words_to_bytes(words), "mid_decrypt"

    # ── Mid-encryption: words 0..K-1 re-encrypted, K..63 still plain ──
    # Fully-decrypted candidate = decrypted[:K] + raw[K:]
    running = sum(raw)  # K=0 case = all plaintext (already tried)
    for k in range(1, 64):
        running += decrypted[k - 1] - raw[k - 1]
        if (running & 0xFFFF) == checksum:
            words = decrypted[:k] + raw[k:]
            return _words_to_bytes(words), "mid_encrypt"

    return None


def _words_to_bytes(words: list[int]) -> bytes:
    """Convert a list of u16 words to a little-endian byte string."""
    result = bytearray(len(words) * 2)
    for i, w in enumerate(words):
        struct.pack_into("<H", result, i * 2, w)
    return bytes(result)


def _ext_sane(data: bytes) -> bool:
    """Check if party extension bytes look like valid decrypted data."""
    level = data[4]
    hp = struct.unpack_from("<H", data, 6)[0]
    max_hp = struct.unpack_from("<H", data, 8)[0]
    if level < 1 or level > 100:
        return False
    if max_hp < 1 or max_hp > 999:
        return False
    if hp > max_hp:
        return False
    return True


def _resolve_party_extension(
    ext_raw: bytes, pid: int, flag_says_decrypted: bool
) -> tuple[int, int, int, int]:
    """Resolve the actual encryption state of the party extension and extract status/level/HP.

    The extension has no checksum, so we try the flag-indicated state first,
    then fall back to the opposite if values look insane. This handles save
    states captured mid-GetValue where blocks and extension can be in
    different encryption states.

    Returns (status, level, cur_hp, max_hp).
    """
    if flag_says_decrypted:
        primary, secondary = ext_raw, _prng_decrypt(ext_raw, pid)
    else:
        primary, secondary = _prng_decrypt(ext_raw, pid), ext_raw

    if _ext_sane(primary):
        src = primary
    elif _ext_sane(secondary):
        src = secondary
    else:
        # Neither looks right — return primary and hope for the best
        src = primary

    status = struct.unpack_from("<I", src, 0)[0]
    return status, src[4], struct.unpack_from("<H", src, 6)[0], struct.unpack_from("<H", src, 8)[0]


def _decode_encrypted_pokemon(raw: bytes) -> dict[str, Any] | None:
    """Decode a Pokemon structure (136-byte box or 236-byte party).

    Checks the partyDecrypted/boxDecrypted flags at offset 0x004 to determine
    whether the data is currently encrypted or sitting in a decryption context.
    Handles both states correctly — no more "stale data" from double-decrypting.

    Returns None if the slot is empty (PID=0).
    """
    pid = struct.unpack_from("<I", raw, 0)[0]
    flags = struct.unpack_from("<H", raw, 4)[0]
    checksum = struct.unpack_from("<H", raw, 6)[0]

    if pid == 0:
        return None

    party_decrypted = bool(flags & 0x01)
    box_decrypted = bool(flags & 0x02)

    nature_idx = pid % 25
    nature = NATURES[nature_idx]

    # Determine actual encryption state for data blocks.
    # Three-tier: flag-indicated → opposite → mixed-state split-point recovery.
    block_data = raw[8:136]
    decrypted, method = _resolve_block_encryption(
        block_data, checksum, box_decrypted
    )

    if decrypted is None:
        # All recovery methods failed — genuine corruption
        return {
            "pid": pid,
            "shiny": False,
            "partial": True,
            "species_id": 0,
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
            "ext_level": 0,
            "ext_cur_hp": 0,
            "ext_max_hp": 0,
        }

    # Party extension: use mixed-state direction hint when available.
    # If blocks were mid-decrypt (Step B), extension already finished Step A → plaintext.
    # If blocks were mid-encrypt (Step D), extension already finished Step C → encrypted.
    # Otherwise, use the flag + heuristic approach.
    ext_status = 0
    ext_level = 0
    ext_cur_hp = 0
    ext_max_hp = 0
    if len(raw) >= 236:
        ext_raw = raw[136:236]
        if method == "mid_decrypt":
            # Extension is plaintext — try that first (True = plaintext priority)
            ext_status, ext_level, ext_cur_hp, ext_max_hp = _resolve_party_extension(
                ext_raw, pid, True
            )
        elif method == "mid_encrypt":
            # Extension is encrypted — try that first (False = encrypted priority)
            ext_status, ext_level, ext_cur_hp, ext_max_hp = _resolve_party_extension(
                ext_raw, pid, False
            )
        else:
            ext_status, ext_level, ext_cur_hp, ext_max_hp = _resolve_party_extension(
                ext_raw, pid, party_decrypted
            )

    blocks = _unshuffle_blocks(decrypted, pid)

    # Block A (Growth)
    species = struct.unpack_from("<H", blocks, 0)[0]
    item = struct.unpack_from("<H", blocks, 2)[0]
    ot_id = struct.unpack_from("<I", blocks, 4)[0]  # TID (lower 16) | SID (upper 16)
    exp = struct.unpack_from("<I", blocks, 8)[0]
    friendship = blocks[12]
    ability_idx = blocks[13]

    # Shiny detection: (TID ^ SID ^ (PID >> 16) ^ (PID & 0xFFFF)) < threshold
    # Renegade Platinum increases shiny rate from 1/8192 (threshold 8) to ~1/512 (threshold 128)
    tid = ot_id & 0xFFFF
    sid = (ot_id >> 16) & 0xFFFF
    shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 128
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
        "shiny": shiny,
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
        "ext_status": ext_status,
        "ext_level": ext_level,
        "ext_cur_hp": ext_cur_hp,
        "ext_max_hp": ext_max_hp,
    }


def _read_species_array(emu: EmulatorClient) -> list[int]:
    """Read the unencrypted species array (catch-order, not party-order)."""
    from renegade_mcp.addresses import addr
    raw = emu.read_memory_range(
        addr("SPECIES_ARRAY_BASE"), size="byte", count=PARTY_MAX_SLOTS * SPECIES_ARRAY_STRIDE
    )
    data = bytes(raw)
    species = []
    for i in range(PARTY_MAX_SLOTS):
        sp = struct.unpack_from("<H", data, i * SPECIES_ARRAY_STRIDE)[0]
        if sp > 0 and sp <= 493:
            species.append(sp)
    return species


# ── Party Reading ──

def read_party(emu: EmulatorClient) -> list[dict[str, Any]]:
    """Read all party slots from memory. Returns list of Pokemon dicts.

    Checks encryption-state flags on each slot, so reads are reliable whether
    the game has data encrypted (normal) or in a decryption context (party
    screen open, battle init, etc.). No refresh/sync step needed.
    """
    sp_names = species_names()
    mv_names = move_names()
    mv_data = move_data()
    ab_names = ability_names()

    from renegade_mcp.addresses import addr
    enc_count_raw = emu.read_memory_range(addr("ENCRYPTED_PARTY_COUNT"), size="long", count=1)
    enc_party_count = min(enc_count_raw[0], PARTY_MAX_SLOTS)

    if enc_party_count == 0:
        return []

    enc_raw = emu.read_memory_range(
        addr("ENCRYPTED_PARTY_BASE"), size="byte", count=enc_party_count * ENCRYPTED_SLOT_SIZE
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

        level = decoded.get("ext_level", 0) or -1
        cur_hp = decoded.get("ext_cur_hp", 0) or -1
        max_hp = decoded.get("ext_max_hp", 0) or -1

        partial = decoded.get("partial", False)
        status_raw = decoded.get("ext_status", 0)
        status_conds = decode_status_conditions(status_raw)

        move_ids = decoded["moves"]
        pp_vals = decoded["pp"]
        move_names_list = [
            mv_names.get(m, f"#{m}") if m > 0 else "-" for m in move_ids
        ]
        # Combined moves list: name, pp, and inline detail (type/power/acc/class)
        moves_combined = []
        for m_id, m_name, m_pp in zip(move_ids, move_names_list, pp_vals):
            entry: dict[str, Any] = {"name": m_name, "pp": m_pp}
            if m_id > 0 and m_id in mv_data:
                info = mv_data[m_id]
                entry["type"] = info.get("type")
                entry["power"] = info.get("power")
                entry["accuracy"] = info.get("accuracy")
                entry["class"] = info.get("class")
            moves_combined.append(entry)

        pokemon: dict[str, Any] = {
            "slot": i,
            "species_id": species,
            "name": name,
            "level": level,
            "hp": cur_hp,
            "max_hp": max_hp,
            "shiny": decoded.get("shiny", False),
            "status_conditions": status_conds,
            "moves": moves_combined,
            "move_names": move_names_list,
            "pp": pp_vals,
            "nature": decoded["nature"],
            "ability": ab_names.get(decoded.get("ability_idx", 0), f"#{decoded.get('ability_idx', 0)}"),
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


def _format_move_detail(info: dict) -> str:
    """Format move type/class/power/accuracy as a bracketed tag."""
    if not info:
        return ""
    parts = [info.get("type", "???"), info.get("class", "???")]
    power = info.get("power")
    if power:
        parts.append(f"{power} pwr")
    acc = info.get("accuracy")
    if acc:
        parts.append(f"{acc}% acc")
    return f" [{' · '.join(parts)}]"


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

        shiny_tag = " *SHINY*" if p.get("shiny") else ""
        ability_str = f"  [{p['ability']}]" if p.get("ability") and p.get("ability") != "-" else ""
        status_conds = p.get("status_conditions", [])
        status_str = f"  ⚠ {', '.join(status_conds)}" if status_conds else ""
        partial_tag = " [stale data]" if p.get("partial") else ""
        lines.append(f"  {p['slot']}. {p['name']}{shiny_tag} {level_str}{nature_str}{ability_str}  {hp_str}{status_str}{partial_tag}")

        if p.get("partial"):
            lines.append("     (moves/IVs/EVs unavailable — encrypted data stale)")
        elif p.get("moves"):
            for m in p["moves"]:
                if m.get("name", "-") == "-":
                    continue
                detail = _format_move_detail(m)
                lines.append(f"     - {m['name']}{detail} (PP {m['pp']})")
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
