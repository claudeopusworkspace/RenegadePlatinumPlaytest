#!/usr/bin/env python3
"""Export species names, move names, and map names from ROM message data to JSON.

Creates:
  data/species_names.json  - {dex_id: name} from file 0412
  data/move_names.json     - {move_id: name} from file 0647
  data/map_names.json      - {location_id: name} from file 0433
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decode_msg import decode_file

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

def export_simple_table(file_index, output_name, description):
    """Export a message file as {index: text} JSON."""
    entries = decode_file(file_index)
    table = {}
    for idx, text, _ in entries:
        # Skip empty strings and variables-only strings
        clean = text.strip()
        if clean and not clean.startswith('{'):
            table[str(idx)] = clean

    out_path = os.path.join(DATA_DIR, output_name)
    with open(out_path, 'w') as f:
        json.dump(table, f, indent=2, ensure_ascii=False)

    print(f"  {description}: {len(table)} entries → {out_path}")
    return table

print("Exporting lookup tables from ROM message data...")
species = export_simple_table(412, 'species_names.json', 'Species names')
moves = export_simple_table(647, 'move_names.json', 'Move names')
maps = export_simple_table(433, 'map_names.json', 'Map/location names')

# Print a few samples
print(f"\nSample species: {species.get('387', '?')} (#387), {species.get('133', '?')} (#133)")
print(f"Sample moves: {moves.get('33', '?')} (#33), {moves.get('71', '?')} (#71)")
print(f"Sample maps: {maps.get('1', '?')} (#1), {maps.get('2', '?')} (#2)")
