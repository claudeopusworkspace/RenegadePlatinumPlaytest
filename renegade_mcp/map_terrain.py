"""ROM/RAM terrain loading, matrix parsing, and chunk resolution.

Terrain is always loaded from ROM via the zone header → matrix → land_data
chain. RAM terrain at 0x0231D1E4 is unreliable (garbled after menu
interactions indoors) and only used as a last-resort fallback.

This module owns the tile-behavior table (BEHAVIORS), directional
constants (FACING_ARROWS/NAMES), the bridge-behavior sets, and the
object-graphics-ID → name lookup. Higher-level modules (map_elevation,
map_poi, map_render) depend on it.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from renegade_mcp.addresses import ZONE_HEADER_BASE, ZONE_HEADER_STRIDE

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Memory layout constants ──
TERRAIN_SIZE = 2048  # 32*32*2

# ── ROM data paths (relative to CWD = project root) ──
ROMDATA_DIR = Path("romdata")
LAND_DATA_DIR = ROMDATA_DIR / "land_data"
MATRIX_DIR = ROMDATA_DIR / "map_matrix"
ZONE_EVENT_DIR = ROMDATA_DIR / "zone_event"
CHUNK_SIZE = 32

# Zone event struct sizes (bytes)
_BG_EVENT_SIZE = 20
_OBJ_EVENT_SIZE = 32
_WARP_EVENT_SIZE = 12

# Offset from ZONE_HEADER_BASE to eventsArchiveID within the zone header.
# ZONE_HEADER_BASE points to mapMatrixID (+0x02 in the C struct), so
# eventsArchiveID (+0x10 in the C struct) is at relative offset +0x0E.
_EVENTS_ARCHIVE_OFFSET = 0x0E

# ── Display constants ──
FACING_ARROWS = {0: "^", 1: "v", 2: "<", 3: ">"}
FACING_NAMES = {0: "up", 1: "down", 2: "left", 3: "right"}

BEHAVIORS = {
    0x00: "ground", 0x02: "tall_grass", 0x03: "very_tall_grass",
    0x08: "cave_floor", 0x10: "water", 0x13: "waterfall", 0x15: "sea",
    0x20: "ice", 0x21: "sand",
    0x30: "block_E", 0x31: "block_W",
    0x38: "ledge_E", 0x39: "ledge_W", 0x3A: "ledge_N", 0x3B: "ledge_S",
    0x5E: "stairs_E", 0x5F: "stairs_W",
    0x62: "warp_E", 0x63: "warp_W", 0x64: "warp_N", 0x65: "warp_S",
    0x67: "warp_panel", 0x69: "door",
    0x6A: "escalator", 0x6B: "escalator",
    0x6C: "side_E", 0x6D: "side_W", 0x6E: "side_N", 0x6F: "side_S",
    # Bridge tiles (0x70-0x7D) — from decomp map_tile_behaviors.h
    0x70: "bridge_start", 0x71: "bridge",
    0x72: "bridge_over_cave", 0x73: "bridge_over_water",
    0x74: "bridge_over_sand", 0x75: "bridge_over_snow",
    0x76: "bike_bridge_NS", 0x77: "bike_bridge_NS_enc",
    0x78: "bike_bridge_NS_water", 0x79: "bike_bridge_NS_sand",
    0x7A: "bike_bridge_EW", 0x7B: "bike_bridge_EW_enc",
    0x7C: "bike_bridge_EW_water", 0x7D: "bike_bridge_EW_sand",
    0x80: "counter",
    # Snow/mud tiles (0xA0-0xA9) — from decomp map_tile_behaviors.h
    0xA0: "berry_patch",
    0xA1: "snow_deep", 0xA2: "snow_deeper", 0xA3: "snow_deepest",
    0xA4: "mud", 0xA5: "mud_deep", 0xA6: "mud_grass", 0xA7: "mud_deep_grass",
    0xA8: "snow_shallow", 0xA9: "snow_shadows",
    # Bike slope/ramp tiles (0xD7-0xDB) — from decomp map_tile_behaviors.h
    0xD7: "bike_ramp_E", 0xD8: "bike_ramp_W",
    0xD9: "bike_slope_top", 0xDA: "bike_slope_bottom", 0xDB: "bike_parking",
}

# Behavior bytes that indicate Cycling Road forced-slide bridge tiles.
# 0x70 = bridge_start, 0x71 = bridge body. `is_on_cycling_road` uses this
# set to dispatch into the auto-slide traversal on Route 206.
# IMPORTANT: the Wayward-style bike bridges (0x76–0x7D) are NOT included
# here — those are bike-required but have NO forced slide, and must not
# go through `_navigate_cycling_road`. They are handled in nav_constants
# as `BIKE_BRIDGE_BEHAVIORS` and routed via `_step_needs_bike`.
# `BIKE_BRIDGE_BEHAVIORS` kept as an alias for backward compatibility
# with existing test imports.
CYCLING_ROAD_BRIDGE_BEHAVIORS = frozenset({0x70, 0x71})
BIKE_BRIDGE_BEHAVIORS = CYCLING_ROAD_BRIDGE_BEHAVIORS

# Cycling road flag — set by gate scripts, forces bike + downhill slide
FLAG_ON_CYCLING_ROAD = 2453

# ── Object graphics name lookup ──
GFX_DATA_FILE = Path("data/obj_event_gfx.txt")


def _load_gfx_names() -> dict[int, str]:
    """Load graphicsID → name mapping from data file."""
    names = {}
    if not GFX_DATA_FILE.exists():
        return names
    for line in GFX_DATA_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            gfx_id = int(parts[0])
        except ValueError:
            continue
        raw = parts[1].strip()
        # Strip prefix and convert to readable name
        clean = raw.removeprefix("OBJ_EVENT_GFX_").replace("_", " ").title()
        names[gfx_id] = clean
    return names


GFX_NAMES: dict[int, str] = _load_gfx_names()

MOVEMENT_TYPES = {
    0: "none", 1: "look_around", 2: "walk_around",
    3: "wander", 15: "stationary",
}

# Sign graphics IDs that auto-trigger dialogue when the player steps onto the
# tile directly south while facing north.
SIGN_GFX_IDS = {91, 93, 94, 95, 96}  # Map Signpost, Signboard, Arrow, Gym, Trainer Tips


# ── Terrain reading ──

def read_terrain_from_ram(emu: EmulatorClient) -> list[list[int]]:
    """Read the 32x32 terrain collision grid from RAM."""
    from renegade_mcp.addresses import addr
    vals = emu.read_memory_range(addr("TERRAIN_ADDR"), size="short", count=1024)
    return [vals[row * 32 : (row + 1) * 32] for row in range(32)]


def is_terrain_empty(grid: list[list[int]]) -> bool:
    """Check if the terrain grid is all zeros (overworld mode)."""
    return all(val == 0 for row in grid for val in row)


def needs_chunk_lookup(ram_terrain: list[list[int]], px: int, py: int) -> bool:
    """Determine if we need ROM-based chunk lookup."""
    return px >= CHUNK_SIZE or py >= CHUNK_SIZE or is_terrain_empty(ram_terrain)


# ── ROM chunk system ──

def parse_matrix(matrix_path: str | Path) -> tuple[int, int, list | None, list]:
    """Parse a map matrix file. Returns (width, height, header_ids_2d_or_None, terrain_ids_2d)."""
    with open(matrix_path, "rb") as f:
        data = f.read()

    w, h = data[0], data[1]
    has_headers, has_heights = data[2], data[3]
    name_len = data[4]
    offset = 5 + name_len

    header_ids = None
    if has_headers:
        header_ids = []
        for row in range(h):
            row_ids = []
            for col in range(w):
                idx = offset + (row * w + col) * 2
                val = struct.unpack_from("<H", data, idx)[0]
                row_ids.append(val)
            header_ids.append(row_ids)
        offset += w * h * 2

    if has_heights:
        offset += w * h

    terrain_ids = []
    for row in range(h):
        row_ids = []
        for col in range(w):
            idx = offset + (row * w + col) * 2
            val = struct.unpack_from("<H", data, idx)[0]
            row_ids.append(val)
        terrain_ids.append(row_ids)

    return w, h, header_ids, terrain_ids


def find_matrix_for_map(map_id: int) -> tuple | None:
    """Search all matrix files for the given map_id.

    Returns (matrix_id, width, height, header_ids, terrain_ids) or None.
    """
    if not MATRIX_DIR.exists():
        return None

    for fname in sorted(os.listdir(MATRIX_DIR)):
        if not fname.endswith(".bin"):
            continue
        matrix_id = int(fname.split(".")[0])
        path = MATRIX_DIR / fname

        w, h, header_ids, terrain_ids = parse_matrix(path)
        if header_ids is None:
            continue

        for row in range(h):
            for col in range(w):
                if header_ids[row][col] == map_id:
                    return matrix_id, w, h, header_ids, terrain_ids

    return None


def load_terrain_from_rom(land_data_id: int) -> list[list[int]] | None:
    """Load a 32x32 terrain grid from a land_data ROM file."""
    path = LAND_DATA_DIR / f"{land_data_id:04d}.bin"
    if not path.exists():
        return None

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 0x10 + TERRAIN_SIZE:
        return None

    terrain_size = struct.unpack_from("<I", data, 0)[0]
    if terrain_size != TERRAIN_SIZE:
        return None

    grid = []
    for row in range(32):
        row_data = []
        for col in range(32):
            idx = 0x10 + (row * 32 + col) * 2
            val = struct.unpack_from("<H", data, idx)[0]
            row_data.append(val)
        grid.append(row_data)

    return grid


def resolve_chunk(map_id: int, global_x: int, global_y: int) -> tuple:
    """Resolve terrain for a global coordinate. Returns (grid, origin_x, origin_y, matrix_id) or (None, 0, 0, None)."""
    result = find_matrix_for_map(map_id)
    if result is None:
        return None, 0, 0, None

    matrix_id, w, h, header_ids, terrain_ids = result

    chunk_x = global_x // CHUNK_SIZE
    chunk_y = global_y // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0, None

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0, None

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y, matrix_id


def get_matrix_for_map(emu: EmulatorClient, map_id: int) -> tuple | None:
    """Look up matrix data for a map via the zone header table.

    Returns (matrix_id, width, height, header_ids, terrain_ids) or None.
    Much faster than find_matrix_for_map() which scans all files.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None

    w, h, header_ids, terrain_ids = parse_matrix(matrix_path)
    return matrix_id, w, h, header_ids, terrain_ids


def resolve_terrain_from_rom(emu: EmulatorClient, map_id: int, px: int, py: int) -> tuple:
    """Resolve terrain from ROM via zone header → matrix → land_data.

    Works for both indoor (single-chunk) and overworld (multi-chunk) maps.
    Returns (grid, origin_x, origin_y, matrix_w, matrix_h) or
    (None, 0, 0, 1, 1) on failure.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None, 0, 0, 1, 1

    w, h, _header_ids, terrain_ids = parse_matrix(matrix_path)

    chunk_x = px // CHUNK_SIZE
    chunk_y = py // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0, 1, 1

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0, 1, 1

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y, w, h
