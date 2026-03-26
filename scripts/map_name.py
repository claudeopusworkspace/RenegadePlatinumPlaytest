#!/usr/bin/env python3
"""Look up the name of a map by its ID.

Usage:
    python3 scripts/map_name.py              # show current map name (reads from emulator)
    python3 scripts/map_name.py 414          # look up map ID 414
    python3 scripts/map_name.py 411 418 422  # look up multiple map IDs
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_TABLE_PATH = os.path.join(PROJECT_ROOT, 'data', 'map_id_to_name.json')

_map_table = None

def get_map_table():
    global _map_table
    if _map_table is None:
        if os.path.exists(MAP_TABLE_PATH):
            with open(MAP_TABLE_PATH) as f:
                _map_table = json.load(f)
        else:
            _map_table = {}
    return _map_table

def lookup_map_name(map_id):
    """Return the location name for a map ID, or a fallback string."""
    table = get_map_table()
    entry = table.get(str(map_id))
    if entry:
        name = entry.get('name', 'Unknown')
        room = entry.get('room', '')
        code = entry.get('code', '')
        if room:
            return f"{name} ({code})"
        return name
    return f"Map {map_id}"

def main():
    if len(sys.argv) > 1:
        # Look up specific map IDs
        for arg in sys.argv[1:]:
            try:
                map_id = int(arg)
                name = lookup_map_name(map_id)
                print(f"  Map {map_id}: {name}")
            except ValueError:
                print(f"  Invalid map ID: {arg}")
    else:
        # Read current map from emulator
        sys.path.insert(0, "/workspace/DesmumeMCP")
        from desmume_mcp.client import connect
        emu = connect()
        try:
            map_id = emu.read_memory(0x0227F450, size="long")
            name = lookup_map_name(map_id)
            x = emu.read_memory(0x0227F458, size="long")
            y = emu.read_memory(0x0227F45C, size="long")
            print(f"  {name} (map {map_id}) — Player at ({x}, {y})")
        finally:
            emu.close()

if __name__ == '__main__':
    main()
