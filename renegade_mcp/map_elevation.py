"""BDHC (height) parsing and per-tile elevation analysis.

The DS stores per-chunk elevation plates in the BDHC section of each
land_data ROM file. analyze_elevation walks those plates and produces a
dict with:
  - level_map: {(col, row): [levels]} — which flat levels a tile belongs to
  - ramp_tiles: {(col, row): ramp_info} — ramp tiles with direction
  - ramps: list of ramp descriptors
  - levels: [{"level": L, "height": H}, ...]
  - height_to_level: {height: level_index}

read_player_height reads the player's Y in fx32 from the MapObject array
for disambiguating 3D situations (e.g. under-bridge vs on-bridge).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from renegade_mcp.addresses import ZONE_HEADER_BASE, ZONE_HEADER_STRIDE
from renegade_mcp.map_terrain import CHUNK_SIZE, LAND_DATA_DIR, MATRIX_DIR, parse_matrix

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def parse_bdhc(land_data_id: int) -> dict | None:
    """Parse BDHC (elevation plate) data from a land_data ROM file.

    Returns dict with points, normals, constants, plates — or None if no
    meaningful BDHC data exists.
    """
    path = LAND_DATA_DIR / f"{land_data_id:04d}.bin"
    if not path.exists():
        return None

    data = path.read_bytes()
    if len(data) < 0x10:
        return None

    map_props_size = struct.unpack_from("<I", data, 0x04)[0]
    map_model_size = struct.unpack_from("<I", data, 0x08)[0]
    bdhc_size = struct.unpack_from("<I", data, 0x0C)[0]

    if bdhc_size == 0:
        return None

    off = 0x0810 + map_props_size + map_model_size
    if off + 0x10 > len(data) or data[off:off + 4] != b"BDHC":
        return None

    points_count = struct.unpack_from("<H", data, off + 0x04)[0]
    normals_count = struct.unpack_from("<H", data, off + 0x06)[0]
    constants_count = struct.unpack_from("<H", data, off + 0x08)[0]
    plates_count = struct.unpack_from("<H", data, off + 0x0A)[0]

    p = off + 0x10
    points = []
    for _ in range(points_count):
        x = struct.unpack_from("<i", data, p)[0] / 4096.0
        z = struct.unpack_from("<i", data, p + 4)[0] / 4096.0
        points.append((x, z))
        p += 8

    normals = []
    for _ in range(normals_count):
        nx = struct.unpack_from("<i", data, p)[0] / 4096.0
        ny = struct.unpack_from("<i", data, p + 4)[0] / 4096.0
        nz = struct.unpack_from("<i", data, p + 8)[0] / 4096.0
        normals.append((nx, ny, nz))
        p += 12

    constants = []
    for _ in range(constants_count):
        d = struct.unpack_from("<i", data, p)[0] / 4096.0
        constants.append(d)
        p += 4

    plates = []
    for _ in range(plates_count):
        p1 = struct.unpack_from("<H", data, p)[0]
        p2 = struct.unpack_from("<H", data, p + 2)[0]
        ni = struct.unpack_from("<H", data, p + 4)[0]
        ci = struct.unpack_from("<H", data, p + 6)[0]
        plates.append({"p1": p1, "p2": p2, "normal": ni, "constant": ci})
        p += 8

    return {"points": points, "normals": normals, "constants": constants, "plates": plates}


def get_land_data_id(emu: EmulatorClient, map_id: int, px: int, py: int) -> int | None:
    """Resolve the land_data file ID for a map position via zone header chain."""
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None

    w, h, _, terrain_ids = parse_matrix(matrix_path)
    chunk_x = px // CHUNK_SIZE
    chunk_y = py // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None

    land_id = terrain_ids[chunk_y][chunk_x]
    return None if land_id == 0xFFFF else land_id


def read_player_height(emu: EmulatorClient) -> float:
    """Read the player's current Y height from MapObject[0].pos.y (fx32)."""
    from renegade_mcp.addresses import addr
    raw = emu.read_memory(addr("OBJ_ARRAY_FPX_BASE") + 4, size="long")
    if raw >= 0x80000000:
        raw -= 0x100000000
    return raw / 4096.0


def tile_to_bdhc(col: int, row: int) -> tuple[float, float]:
    """Convert tile center to BDHC coordinate space (origin = map center)."""
    return (col + 0.5) * 16 - 256, (row + 0.5) * 16 - 256


# Legacy private-name alias — pathfinding.py imports `_tile_to_bdhc` directly.
_tile_to_bdhc = tile_to_bdhc


def analyze_elevation(bdhc: dict, terrain: list[list[int]]) -> dict | None:
    """Analyze BDHC data to build per-tile elevation levels.

    Returns None for flat maps (single height). Otherwise returns dict with
    level_map, ramp_tiles, ramps, and levels for rendering.
    """
    plates = bdhc["plates"]
    pts = bdhc["points"]
    norms = bdhc["normals"]
    consts = bdhc["constants"]

    # Step 1: Collect discrete heights from flat plates only
    flat_heights: set[int] = set()
    for plate in plates:
        nx, ny, nz = norms[plate["normal"]]
        if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny) > 0.01:
            d = consts[plate["constant"]]
            flat_heights.add(round(-d / ny))

    if len(flat_heights) <= 1:
        return None

    sorted_heights = sorted(flat_heights)
    h2l = {h: i for i, h in enumerate(sorted_heights)}

    # Step 2: Map tiles to levels from flat plates
    level_map: dict[tuple[int, int], list[int]] = {}

    for row in range(32):
        for col in range(32):
            if terrain[row][col] & 0x8000:
                continue
            x, z = tile_to_bdhc(col, row)
            levels: set[int] = set()
            for plate in plates:
                x1, z1 = pts[plate["p1"]]
                x2, z2 = pts[plate["p2"]]
                if not (min(x1, x2) <= x <= max(x1, x2) and min(z1, z2) <= z <= max(z1, z2)):
                    continue
                nx, ny, nz = norms[plate["normal"]]
                if abs(nx) < 0.01 and abs(nz) < 0.01 and abs(ny) > 0.01:
                    d = consts[plate["constant"]]
                    h = round(-d / ny)
                    if h in h2l:
                        levels.add(h2l[h])
            if levels:
                level_map[(col, row)] = sorted(levels)

    # Step 3: Identify ramp plates and mark tiles
    ramp_tiles: dict[tuple[int, int], dict] = {}
    ramps: list[dict] = []

    for plate in plates:
        nx, ny, nz = norms[plate["normal"]]
        if abs(nx) < 0.01 and abs(nz) < 0.01:
            continue
        if abs(ny) < 0.01:
            continue

        x1, z1 = pts[plate["p1"]]
        x2, z2 = pts[plate["p2"]]
        d = consts[plate["constant"]]

        # Heights at plate corners to find connected levels
        corners = [
            (min(x1, x2), min(z1, z2)), (min(x1, x2), max(z1, z2)),
            (max(x1, x2), min(z1, z2)), (max(x1, x2), max(z1, z2)),
        ]
        corner_heights = [round(-(nx * cx + nz * cz + d) / ny) for cx, cz in corners]
        h_max, h_min = max(corner_heights), min(corner_heights)

        from_level = h2l.get(h_max)
        to_level = h2l.get(h_min)
        if from_level is None or to_level is None:
            continue

        direction = ("south" if nz > 0 else "north") if abs(nz) >= abs(nx) else ("east" if nx > 0 else "west")

        col_min = int((min(x1, x2) + 256) / 16)
        col_max = int((max(x1, x2) + 256) / 16)
        row_min = int((min(z1, z2) + 256) / 16)
        row_max = int((max(z1, z2) + 256) / 16)

        ramp_info = {
            "ramp_index": len(ramps),
            "col_range": (col_min, col_max),
            "row_range": (row_min, row_max),
            "from_level": from_level,
            "to_level": to_level,
            "direction": direction,
        }
        ramps.append(ramp_info)

        for r in range(row_min, row_max):
            for c in range(col_min, col_max):
                if not (terrain[r][c] & 0x8000):
                    ramp_tiles[(c, r)] = ramp_info

    levels_info = [{"level": h2l[h], "height": h} for h in sorted_heights]

    return {
        "level_map": level_map,
        "ramp_tiles": ramp_tiles,
        "ramps": ramps,
        "levels": levels_info,
        "height_to_level": h2l,
    }
