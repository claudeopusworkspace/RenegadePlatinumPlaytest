#!/usr/bin/env python3
"""Build comprehensive map_id → location name table from mapname.bin.

mapname.bin has 16-byte ASCII area codes for each map_id.
Format: AreaCode[RoomInfo] padded with nulls.

Area codes map to location names via the game's naming convention.
"""

import json
import os
import struct

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPNAME_PATH = os.path.join(PROJECT_ROOT, 'romdata', 'mapname.bin')
MAP_NAMES_PATH = os.path.join(PROJECT_ROOT, 'data', 'map_names.json')
OUTPUT_PATH = os.path.join(PROJECT_ROOT, 'data', 'map_id_to_name.json')

with open(MAPNAME_PATH, 'rb') as f:
    data = f.read()

# Load location names from message NARC
with open(MAP_NAMES_PATH) as f:
    location_names = {int(k): v for k, v in json.load(f).items()}

entry_size = 16
num_entries = len(data) // entry_size

# Parse all entries
entries = []
for i in range(num_entries):
    raw = data[i*entry_size:(i+1)*entry_size]
    # Decode as ASCII, strip nulls
    code = raw.split(b'\x00')[0].decode('ascii', errors='replace')
    entries.append(code)

# Count unique area prefixes (before 'R' room suffix)
area_codes = {}
for i, code in enumerate(entries):
    if not code:
        continue
    # Split at 'R' room marker (if present and not the first char)
    if 'R' in code[1:]:
        area = code[:code.index('R', 1)]
        room = code[code.index('R', 1):]
    else:
        area = code
        room = ""
    if area not in area_codes:
        area_codes[area] = []
    area_codes[area].append((i, room))

# Print unique area codes sorted
print(f"Total entries: {num_entries}")
print(f"Unique area codes: {len(area_codes)}")
print()

# Build mapping by extracting the numeric part from each area code
# and trying to match it to location names
#
# Convention observed:
# T01-T15 → Towns/Cities (location IDs 1-15)
# R201-R230 → Routes (location IDs 16-45)
# C01-C?? → Caves/dungeons
# D01-D?? → Dungeons?
# L01-L?? → Lakes/Lakefronts
# etc.

# First, let's figure out the exact mapping by printing all area codes
# grouped by prefix letter
by_prefix = {}
for area in sorted(area_codes.keys()):
    prefix = area[0]
    if prefix not in by_prefix:
        by_prefix[prefix] = []
    by_prefix[prefix].append(area)

for prefix in sorted(by_prefix.keys()):
    codes = by_prefix[prefix]
    print(f"Prefix '{prefix}': {len(codes)} areas — {', '.join(sorted(codes)[:15])}")

# Now let's manually build the area_code → location_name_id mapping
# based on known areas from the location name list (file 433)
# I'll print both side by side so we can verify

print("\n=== Location names (from msg file 433) ===")
for lid in sorted(location_names.keys())[:60]:
    print(f"  {lid:3d}: {location_names[lid]}")

# Build the mapping by matching area codes to location names
# The key insight: "T01" = Town #1 = location_names[1], etc.
# For routes: "R201" = Route 201 = location_names[16], etc.

# Let me try the simpler approach: read a header from ROM that directly
# maps to location name IDs. But for now, build what we can heuristically.

# Actually, the easiest approach: map the ASCII area code for each map_id
# to a location name. We know T01=1, T02=2, etc. for towns.
# For routes, R201 would be route 201 which starts at location ID 16.

# Town mapping: T01=1, T02=2, ..., T15=15 (or whatever the max is)
# Route mapping: R201=16, R202=17, ...

AREA_TO_LOCATION = {}

# Towns: T01=1 (Twinleaf), T02=2 (Sandgem), ..., T05=5 (Celestic)
for i in range(1, 6):
    AREA_TO_LOCATION[f"T{i:02d}"] = i

# Cities: C01=6 (Jubilife), C02=7 (Canalave), ..., C10=15 (Pokemon League)
for i in range(1, 11):
    AREA_TO_LOCATION[f"C{i:02d}"] = i + 5

# Routes: R201=16, R202=17, etc. (also handle A/B splits like R204A)
for lid, name in location_names.items():
    if name.startswith("Route "):
        route_num = int(name.split()[1])
        AREA_TO_LOCATION[f"R{route_num}"] = lid
        # Some routes have A/B splits (e.g., R204A, R204B) — map both to same name
        AREA_TO_LOCATION[f"R{route_num}A"] = lid
        AREA_TO_LOCATION[f"R{route_num}B"] = lid

# Water routes: W220=Route 220, W223=Route 223, etc.
for lid, name in location_names.items():
    if name.startswith("Route "):
        route_num = int(name.split()[1])
        AREA_TO_LOCATION[f"W{route_num}"] = lid

# Dungeons/special areas (D prefix) — mapped by cross-referencing game data
# D01=Oreburgh Mine(46), D02=Valley Windworks(47), etc.
DUNGEON_MAP = {
    "D01": 46,  # Oreburgh Mine
    "D02": 47,  # Valley Windworks
    "D03": 48,  # Eterna Forest
    "D04": 49,  # Fuego Ironworks
    "D05": 50,  # Mt. Coronet
    "D06": 51,  # Spear Pillar
    "D07": 52,  # Great Marsh
    "D09": 53,  # Solaceon Ruins
    "D10": 54,  # Victory Road
    "D11": 55,  # Pal Park
    "D12": 56,  # Amity Square
    "D13": 57,  # Ravaged Path
    "D14": 58,  # Floaroma Meadow
    "D15": 59,  # Oreburgh Gate
    "D16": 117, # Distortion World
}
AREA_TO_LOCATION.update(DUNGEON_MAP)

# Lakes: L01-L04
LAKE_MAP = {
    "L01": 95,  # Verity Lakefront
    "L02": 94,  # Valor Lakefront
    "L03": 97,  # Acuity Lakefront
    "L04": 93,  # Lake Verity (guess — may need correction)
}
AREA_TO_LOCATION.update(LAKE_MAP)

# Special areas
AREA_TO_LOCATION["UG"] = 103       # Underground
AREA_TO_LOCATION["UNION"] = 104    # Union Room
AREA_TO_LOCATION["EVE"] = 0        # Event area
AREA_TO_LOCATION["NOTHING"] = 0    # Mystery Zone
AREA_TO_LOCATION["HI"] = 0         # Hidden area

# Print remaining unmapped areas to figure out lakes, caves, etc.
print(f"\n=== Mapped {len(AREA_TO_LOCATION)} areas ===")
unmapped = [a for a in area_codes if a not in AREA_TO_LOCATION]
print(f"Unmapped areas ({len(unmapped)}): {', '.join(sorted(unmapped)[:30])}")

# For remaining location names (>= 45), print them to help with mapping
print("\n=== Remaining location names (45+) ===")
for lid in sorted(location_names.keys()):
    if lid >= 45:
        print(f"  {lid:3d}: {location_names[lid]}")

# Build final map_id → name table
result = {}
for map_id, code in enumerate(entries):
    if not code:
        result[str(map_id)] = {"code": "", "name": "Mystery Zone"}
        continue

    # Get area prefix
    if 'R' in code[1:]:
        area = code[:code.index('R', 1)]
        room = code[code.index('R', 1):]
    else:
        area = code
        room = ""

    loc_id = AREA_TO_LOCATION.get(area)
    if loc_id is not None:
        name = location_names.get(loc_id, f"Location#{loc_id}")
    else:
        name = f"[{area}]"  # Unknown area

    result[str(map_id)] = {
        "code": code,
        "name": name,
        "room": room,
    }

with open(OUTPUT_PATH, 'w') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"\n=== Saved {len(result)} map entries to {OUTPUT_PATH} ===")

# Verify with known maps
print("\n=== Verification ===")
test_maps = [334, 411, 412, 414, 415, 418, 422]
for mid in test_maps:
    info = result.get(str(mid), {})
    print(f"  Map {mid}: {info.get('name', '?')} (code={info.get('code', '?')}, room={info.get('room', '')})")
