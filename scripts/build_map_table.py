#!/usr/bin/env python3
"""Build map_id → location name table from ROM zone headers.

Reads the mapLabelTextID directly from each zone header entry in the NDS
ROM's ARM9 binary, cross-references with message file 433 (location names),
and combines with area codes from mapname.bin.

Previous approach used hardcoded area-code-to-location-name mappings that
were stale for Renegade Platinum's reshuffled map IDs (e.g., map 258 was
"Floaroma Meadow" instead of "Oreburgh Gate"). This version is authoritative.

Zone header struct layout (from pokeplatinum decomp MapHeader):
  +0x00: u8  areaDataArchiveID
  +0x01: u8  unk_01
  +0x02: u16 mapMatrixID       ← ZONE_HEADER_BASE points here
  +0x04: u16 scriptsArchiveID
  +0x06: u16 initScriptsArchiveID
  +0x08: u16 msgArchiveID
  +0x0A: u16 dayMusicID
  +0x0C: u16 nightMusicID
  +0x0E: u16 wildEncountersArchiveID
  +0x10: u16 eventsArchiveID
  +0x12: u8  mapLabelTextID    ← indexes into msg file 433
  +0x13: u8  mapLabelWindowID
  +0x14: u8  weather
  +0x15: u8  cameraType
  +0x16: u16 (bitfield: mapType, battleBG, flags)
  Total: 24 bytes (ZONE_HEADER_STRIDE)

ZONE_HEADER_BASE (0x020E601E) points to mapMatrixID, which is at C struct
offset +0x02. So mapLabelTextID (C struct +0x12) is at relative offset +0x10
from ZONE_HEADER_BASE per entry.
"""

import json
import os
import struct

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM_PATH = os.path.join(PROJECT_ROOT, 'RenegadePlatinum.nds')
MAPNAME_PATH = os.path.join(PROJECT_ROOT, 'romdata', 'mapname.bin')
MAP_NAMES_PATH = os.path.join(PROJECT_ROOT, 'data', 'map_names.json')
OUTPUT_PATH = os.path.join(PROJECT_ROOT, 'data', 'map_id_to_name.json')

ZONE_HEADER_RAM_ADDR = 0x020E601E  # ARM9 address of zone header table
ZONE_HEADER_STRIDE = 24
LABEL_TEXT_ID_OFFSET = 0x10  # mapLabelTextID within each entry

# ── Read NDS ROM header to locate ARM9 binary ──
with open(ROM_PATH, 'rb') as f:
    f.seek(0x20)
    arm9_rom_offset = struct.unpack('<I', f.read(4))[0]
    f.seek(0x28)
    arm9_ram_addr = struct.unpack('<I', f.read(4))[0]

    # ── Read mapname.bin to determine map count ──
    with open(MAPNAME_PATH, 'rb') as mf:
        mapname_data = mf.read()
    num_maps = len(mapname_data) // 16

    # ── Read zone header table from ROM ──
    zone_file_offset = arm9_rom_offset + (ZONE_HEADER_RAM_ADDR - arm9_ram_addr)
    f.seek(zone_file_offset)
    zone_data = f.read(num_maps * ZONE_HEADER_STRIDE)

# ── Parse area codes from mapname.bin ──
area_codes = []
for i in range(num_maps):
    raw = mapname_data[i * 16:(i + 1) * 16]
    code = raw.split(b'\x00')[0].decode('ascii', errors='replace')
    area_codes.append(code)

# ── Parse mapLabelTextID from zone headers ──
label_ids = []
for i in range(num_maps):
    entry = zone_data[i * ZONE_HEADER_STRIDE:(i + 1) * ZONE_HEADER_STRIDE]
    label_ids.append(entry[LABEL_TEXT_ID_OFFSET])

# ── Load location names (msg file 433) ──
with open(MAP_NAMES_PATH) as f:
    location_names = {int(k): v for k, v in json.load(f).items()}

# ── Build map table ──
result = {}
for map_id in range(num_maps):
    code = area_codes[map_id]
    lid = label_ids[map_id]
    name = location_names.get(lid, f"Unknown (label={lid})")

    # Parse room suffix from area code
    room = ""
    if code and 'R' in code[1:]:
        room = code[code.index('R', 1):]

    result[str(map_id)] = {
        "code": code,
        "name": name,
        "room": room,
    }

with open(OUTPUT_PATH, 'w') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"Built {len(result)} map entries → {OUTPUT_PATH}")

# ── Verification ──
verify = {258: "Oreburgh Gate", 3: "Jubilife City", 411: "Twinleaf Town"}
all_ok = True
for mid, expected in verify.items():
    actual = result[str(mid)]["name"]
    status = "✓" if actual == expected else "✗"
    if actual != expected:
        all_ok = False
    print(f"  {status} Map {mid}: {actual} (expected {expected})")

if all_ok:
    print("All verification checks passed.")
