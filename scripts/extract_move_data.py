#!/usr/bin/env python3
"""Extract move data (type, power, accuracy, PP, class) from the ROM's waza_tbl NARC.

Writes data/move_data.json mapping move_id → {name, type, power, accuracy, pp, class, priority}.

Usage:
    python scripts/extract_move_data.py

Requires the ROM at RenegadePlatinum.nds and data/move_names.json to already exist.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROM_PATH = Path("RenegadePlatinum.nds")
MOVE_NAMES_PATH = Path("data/move_names.json")
OUTPUT_PATH = Path("data/move_data.json")

# MoveTable struct (16 bytes per entry, from pret/pokeplatinum include/move_table.h):
#   u16 effect, u8 class, u8 power, u8 type, u8 accuracy, u8 pp, u8 effectChance,
#   u16 range, s8 priority, u8 flags, 4 bytes contest data
MOVE_ENTRY_SIZE = 16

# Gen 4 type ID → name (same mapping as battle.py, with Fairy for Renegade Platinum)
TYPE_NAMES = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison",
    4: "Ground", 5: "Rock", 6: "Bug", 7: "Ghost", 8: "Steel",
    9: "Fairy",
    10: "Fire", 11: "Water", 12: "Grass", 13: "Electric",
    14: "Psychic", 15: "Ice", 16: "Dragon", 17: "Dark",
}

# Move class ID → label
CLASS_NAMES = {0: "Physical", 1: "Special", 2: "Status"}


def find_waza_narc(rom_data: bytes) -> tuple[int, int] | None:
    """Find pl_waza_tbl NARC by scanning all FAT entries for matching structure.

    Identifies the Renegade Platinum version (modified move data) by checking
    known move changes — e.g. Flamethrower power = 90 (Gen 6 rebalance).
    Returns (offset, size) or None.
    """
    fat_offset = struct.unpack_from("<I", rom_data, 0x48)[0]
    fat_size = struct.unpack_from("<I", rom_data, 0x4C)[0]
    num_files = fat_size // 8

    candidates = []
    for fid in range(num_files):
        entry_pos = fat_offset + fid * 8
        start = struct.unpack_from("<I", rom_data, entry_pos)[0]
        end = struct.unpack_from("<I", rom_data, entry_pos + 4)[0]
        size = end - start
        if size < 100 or size > 20000:
            continue
        if rom_data[start:start + 4] != b"NARC":
            continue
        # Check BTAF header
        hdr_size = struct.unpack_from("<H", rom_data, start + 12)[0]
        btaf_off = start + hdr_size
        if rom_data[btaf_off:btaf_off + 4] != b"BTAF":
            continue
        n_entries = struct.unpack_from("<H", rom_data, btaf_off + 8)[0]
        # waza_tbl has ~468-471 entries, each 16 bytes
        if not (460 <= n_entries <= 480):
            continue
        e_start = struct.unpack_from("<I", rom_data, btaf_off + 12)[0]
        e_end = struct.unpack_from("<I", rom_data, btaf_off + 20)[0]
        if e_end - e_start != MOVE_ENTRY_SIZE:
            continue
        candidates.append((fid, start, size, n_entries))

    if not candidates:
        return None

    # If multiple candidates, pick the one with Renegade Platinum modifications
    # (Flamethrower = move 53, should have 90 power instead of vanilla 95)
    for fid, start, size, n_entries in candidates:
        hdr_size = struct.unpack_from("<H", rom_data, start + 12)[0]
        btaf_off = start + hdr_size
        btaf_size = struct.unpack_from("<I", rom_data, btaf_off + 4)[0]
        btnf_off = btaf_off + btaf_size
        btnf_size = struct.unpack_from("<I", rom_data, btnf_off + 4)[0]
        gmif_off = btnf_off + btnf_size
        data_start = gmif_off + 8

        # Read move 53 (Flamethrower) power byte
        m53_fat = btaf_off + 12 + 53 * 8
        m53_start = struct.unpack_from("<I", rom_data, m53_fat)[0]
        power = rom_data[data_start + m53_start + 3]
        if power == 90:  # Renegade Platinum's modified value
            return start, size

    # Fall back to first candidate
    _, start, size, _ = candidates[0]
    return start, size


def parse_narc(narc_data: bytes) -> list[bytes]:
    """Parse a NARC archive and return individual file entries."""
    magic = narc_data[:4]
    if magic != b"NARC":
        raise ValueError(f"Not a NARC file (magic: {magic!r})")

    header_size = struct.unpack_from("<H", narc_data, 12)[0]

    # BTAF (FAT block)
    btaf_offset = header_size
    btaf_size = struct.unpack_from("<I", narc_data, btaf_offset + 4)[0]
    num_files = struct.unpack_from("<H", narc_data, btaf_offset + 8)[0]

    fat_entries = []
    for i in range(num_files):
        entry_pos = btaf_offset + 12 + i * 8
        start = struct.unpack_from("<I", narc_data, entry_pos)[0]
        end = struct.unpack_from("<I", narc_data, entry_pos + 4)[0]
        fat_entries.append((start, end))

    # BTNF block (skip)
    btnf_offset = btaf_offset + btaf_size
    btnf_size = struct.unpack_from("<I", narc_data, btnf_offset + 4)[0]

    # GMIF (file image) block
    gmif_offset = btnf_offset + btnf_size
    data_start = gmif_offset + 8

    files = []
    for start, end in fat_entries:
        files.append(narc_data[data_start + start:data_start + end])
    return files


def parse_move_entry(entry: bytes) -> dict:
    """Parse a 16-byte MoveTable struct into a dict."""
    if len(entry) < MOVE_ENTRY_SIZE:
        return {}
    move_class = entry[2]
    power = entry[3]
    type_id = entry[4]
    accuracy = entry[5]
    pp = entry[6]
    move_range = struct.unpack_from("<H", entry, 8)[0]
    priority = struct.unpack_from("<b", entry, 10)[0]

    return {
        "type": TYPE_NAMES.get(type_id, f"#{type_id}"),
        "power": power if power > 0 else None,
        "accuracy": accuracy if accuracy > 0 else None,
        "pp": pp,
        "class": CLASS_NAMES.get(move_class, f"#{move_class}"),
        "priority": priority,
        "range": move_range,
    }


def main():
    if not ROM_PATH.exists():
        print(f"Error: ROM not found at {ROM_PATH}", file=sys.stderr)
        sys.exit(1)

    move_names = {}
    if MOVE_NAMES_PATH.exists():
        with open(MOVE_NAMES_PATH) as f:
            move_names = {int(k): v for k, v in json.load(f).items()}

    print("Reading ROM...")
    rom_data = ROM_PATH.read_bytes()

    print("Scanning ROM for waza_tbl NARC...")
    result = find_waza_narc(rom_data)
    if result is None:
        print("Error: Could not find waza_tbl NARC in ROM", file=sys.stderr)
        sys.exit(1)

    offset, size = result
    print(f"Found NARC at ROM offset 0x{offset:X} ({size} bytes)")

    narc_data = rom_data[offset:offset + size]
    entries = parse_narc(narc_data)
    print(f"NARC contains {len(entries)} entries")

    move_data = {}
    for move_id, entry in enumerate(entries):
        if len(entry) < MOVE_ENTRY_SIZE:
            continue
        parsed = parse_move_entry(entry)
        if not parsed:
            continue
        name = move_names.get(move_id, f"Move #{move_id}")
        parsed["name"] = name
        move_data[str(move_id)] = parsed

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(move_data, f, indent=2)

    print(f"Wrote {len(move_data)} moves to {OUTPUT_PATH}")

    # Verification samples
    samples = [1, 10, 33, 53, 56, 85, 89, 94]
    print("\nSample entries:")
    for mid in samples:
        entry = move_data.get(str(mid))
        if entry:
            print(f"  #{mid} {entry['name']}: {entry['type']} {entry['class']} "
                  f"pow={entry['power']} acc={entry['accuracy']} pp={entry['pp']}")


if __name__ == "__main__":
    main()
