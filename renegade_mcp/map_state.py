"""Terrain, dynamic objects, and player state reading + ASCII map rendering.

Terrain is always loaded from ROM via the zone header → matrix → land_data
chain. RAM terrain at 0x0231D1E4 is unreliable (garbled after menu
interactions indoors) and only used as a last-resort fallback.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from renegade_mcp.map_names import lookup_map_name

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Memory addresses ──
TERRAIN_ADDR = 0x0231D1E4
TERRAIN_SIZE = 2048  # 32*32*2

PLAYER_POS_BASE = 0x0227F450
# Player facing: MapObject[0].facingDir (0x022A1A38 + 0x28)
PLAYER_FACING_ADDR = 0x022A1A60

# Zone header table in ARM9 (Platinum US / Renegade Platinum).
# Each entry is 24 bytes; first u16 is the matrix_id for that zone.
ZONE_HEADER_BASE = 0x020E601E
ZONE_HEADER_STRIDE = 24

OBJ_ARRAY_FPX_BASE = 0x022A1AA8
OBJ_STRUCT_BASE = OBJ_ARRAY_FPX_BASE - 0x70  # True start of MapObject[0]
OBJ_STRIDE = 0x128
OBJ_MAX_ENTRIES = 64

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
    0x38: "ledge_S", 0x39: "ledge_N", 0x3A: "ledge_W", 0x3B: "ledge_E",
    0x5E: "stairs_up", 0x5F: "stairs_down",
    0x62: "warp", 0x65: "door", 0x69: "door2", 0x6B: "warp3",
    0x80: "counter", 0xA9: "tree_tile",
}

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


# ── Terrain reading ──

def read_terrain_from_ram(emu: EmulatorClient) -> list[list[int]]:
    """Read the 32x32 terrain collision grid from RAM."""
    vals = emu.read_memory_range(TERRAIN_ADDR, size="short", count=1024)
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


def get_matrix_for_map(emu: "EmulatorClient", map_id: int) -> tuple | None:
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


def read_warps_from_rom(emu: "EmulatorClient", map_id: int) -> list[dict[str, int]]:
    """Read warp events for a map from the ROM zone_event data.

    Returns list of dicts with keys: x, y (tile coords), dest_map, dest_warp.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE + _EVENTS_ARCHIVE_OFFSET
    events_id = emu.read_memory(addr, size="short")

    event_path = ZONE_EVENT_DIR / f"{events_id:04d}.bin"
    if not event_path.exists():
        return []

    data = event_path.read_bytes()
    off = 0

    # Skip BG events
    num_bg = struct.unpack_from("<I", data, off)[0]; off += 4
    off += num_bg * _BG_EVENT_SIZE

    # Skip Object events
    num_obj = struct.unpack_from("<I", data, off)[0]; off += 4
    off += num_obj * _OBJ_EVENT_SIZE

    # Read Warp events
    num_warps = struct.unpack_from("<I", data, off)[0]; off += 4
    warps = []
    for _ in range(num_warps):
        wx, wz, dest_map, dest_warp = struct.unpack_from("<HHHH", data, off)
        off += _WARP_EVENT_SIZE
        warps.append({"x": wx, "y": wz, "dest_map": dest_map, "dest_warp": dest_warp})

    return warps


def resolve_terrain_from_rom(emu: "EmulatorClient", map_id: int, px: int, py: int) -> tuple:
    """Resolve terrain from ROM via zone header → matrix → land_data.

    Works for both indoor (single-chunk) and overworld (multi-chunk) maps.
    Returns (grid, origin_x, origin_y) or (None, 0, 0) on failure.
    """
    addr = ZONE_HEADER_BASE + map_id * ZONE_HEADER_STRIDE
    matrix_id = emu.read_memory(addr, size="short")

    matrix_path = MATRIX_DIR / f"{matrix_id:04d}.bin"
    if not matrix_path.exists():
        return None, 0, 0

    w, h, _header_ids, terrain_ids = parse_matrix(matrix_path)

    chunk_x = px // CHUNK_SIZE
    chunk_y = py // CHUNK_SIZE

    if not (0 <= chunk_x < w and 0 <= chunk_y < h):
        return None, 0, 0

    land_data_id = terrain_ids[chunk_y][chunk_x]
    if land_data_id == 0xFFFF:
        return None, 0, 0

    grid = load_terrain_from_rom(land_data_id)
    origin_x = chunk_x * CHUNK_SIZE
    origin_y = chunk_y * CHUNK_SIZE
    return grid, origin_x, origin_y


# ── Dynamic objects ──

def read_objects(emu: EmulatorClient) -> list[dict[str, Any]]:
    """Scan the overworld object array and return active objects with identity info.

    For each active entry, reads the MapObject struct header to get graphicsID,
    movementType, localID, trainerType, and script — enabling identification of
    what each object actually is (NPC, item ball, briefcase, boulder, etc.).
    """
    objects = []
    consecutive_empty = 0

    for i in range(OBJ_MAX_ENTRIES):
        struct_base = OBJ_STRUCT_BASE + (i * OBJ_STRIDE)

        # Read struct header first: status, unk, localID, mapID, graphicsID,
        # movementType, trainerType, flag, script (9 longs from struct base)
        header = emu.read_memory_range(struct_base, size="long", count=9)
        status = header[0] if header else 0

        # Use status field for empty detection — position (0,0) doesn't mean
        # empty (some objects are loaded at origin before being placed)
        if status == 0:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            continue
        consecutive_empty = 0

        fpx_addr = OBJ_ARRAY_FPX_BASE + (i * OBJ_STRIDE)
        fpy_addr = fpx_addr + 8

        fpx = emu.read_memory(fpx_addr, size="long")
        fpy = emu.read_memory(fpy_addr, size="long")

        tile_x = (fpx >> 16) & 0xFFFF
        tile_y = (fpy >> 16) & 0xFFFF

        if tile_x > 10000 or tile_y > 10000:
            continue

        obj: dict[str, Any] = {
            "index": i, "x": tile_x, "y": tile_y, "fpx": fpx, "fpy": fpy,
        }

        if len(header) >= 9:
            gfx_id = header[4]
            obj["local_id"] = header[2]
            obj["graphics_id"] = gfx_id
            obj["name"] = GFX_NAMES.get(gfx_id, f"Unknown ({gfx_id})")
            obj["movement_type"] = MOVEMENT_TYPES.get(header[5], f"type_{header[5]}")
            obj["trainer_type"] = header[6]
            obj["script"] = header[8]

        objects.append(obj)

    return objects


# ── Player state ──

def read_player_state(emu: EmulatorClient) -> tuple[int, int, int, int]:
    """Read player position and facing. Returns (map_id, x, y, facing)."""
    map_id = emu.read_memory(PLAYER_POS_BASE, size="long")
    x = emu.read_memory(PLAYER_POS_BASE + 8, size="long")
    y = emu.read_memory(PLAYER_POS_BASE + 12, size="long")
    facing = emu.read_memory(PLAYER_FACING_ADDR, size="long")
    return map_id, x, y, facing


# ── High-level map state ──

def get_map_state(emu: EmulatorClient) -> dict[str, Any] | None:
    """Read full map state: terrain grid, objects, player position.

    Terrain is resolved from ROM (zone header → matrix → land_data) which is
    immune to RAM corruption from menu overlays.  Falls back to RAM terrain
    only when ROM resolution fails.

    Returns dict with terrain, objects, positions, and origin info.
    Returns None if all resolution methods fail.
    """
    map_id, px, py, facing = read_player_state(emu)
    objects = read_objects(emu)

    # Always try ROM first — reliable regardless of menu state.
    terrain, origin_x, origin_y = resolve_terrain_from_rom(emu, map_id, px, py)
    chunked = origin_x > 0 or origin_y > 0

    # Fall back to RAM terrain if ROM resolution failed.
    if terrain is None:
        ram_terrain = read_terrain_from_ram(emu)
        if not is_terrain_empty(ram_terrain):
            terrain = ram_terrain
            origin_x, origin_y = 0, 0
            chunked = False

    if terrain is None:
        return None

    local_px = px - origin_x
    local_py = py - origin_y
    height = len(terrain)
    width = len(terrain[0]) if terrain else 0
    for obj in objects:
        lx = obj["x"] - origin_x
        ly = obj["y"] - origin_y
        obj["local_x"] = lx
        obj["local_y"] = ly
        # Record terrain behavior underneath this object
        if 0 <= ly < height and 0 <= lx < width:
            tile_val = terrain[ly][lx]
            behavior = tile_val & 0x00FF
            if behavior != 0:
                obj["standing_on"] = f"0x{behavior:02X}"

    return {
        "terrain": terrain,
        "objects": objects,
        "map_id": map_id,
        "px": px, "py": py,
        "local_px": local_px, "local_py": local_py,
        "origin_x": origin_x, "origin_y": origin_y,
        "facing": facing,
        "chunked": chunked,
    }


# ── ASCII map rendering ──

def render_map(terrain: list, objects: list, player_local_x: int, player_local_y: int, facing: int) -> str:
    """Render an ASCII map combining terrain and dynamic objects."""
    obj_at = {}
    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
            if obj["index"] == 0:
                obj_at[(lx, ly)] = FACING_ARROWS.get(facing, "P")
            else:
                idx = obj["index"]
                if 1 <= idx <= 26:
                    obj_at[(lx, ly)] = chr(ord("A") + idx - 1)
                elif 27 <= idx <= 52:
                    obj_at[(lx, ly)] = chr(ord("a") + idx - 27)
                else:
                    obj_at[(lx, ly)] = "?"

    # Find map bounds
    min_row, max_row = 31, 0
    min_col, max_col = 31, 0
    for row in range(32):
        for col in range(32):
            if terrain[row][col] != 0:
                min_row = min(min_row, row)
                max_row = max(max_row, row)
                min_col = min(min_col, col)
                max_col = max(max_col, col)

    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < 32 and 0 <= ly < 32:
            min_row = min(min_row, ly)
            max_row = max(max_row, ly)
            min_col = min(min_col, lx)
            max_col = max(max_col, lx)

    min_row = max(0, min_row - 1)
    max_row = min(31, max_row + 1)
    min_col = max(0, min_col - 1)
    max_col = min(31, max_col + 1)

    lines = []

    header = "     "
    for col in range(min_col, max_col + 1):
        header += f"{col:>3}"
    lines.append(header)
    lines.append("    " + "-" * ((max_col - min_col + 1) * 3 + 1))

    behaviors_seen = {}

    for row in range(min_row, max_row + 1):
        line = f"{row:>3} |"
        for col in range(min_col, max_col + 1):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF

            if (col, row) in obj_at:
                cell = f"  {obj_at[(col, row)]}"
            elif val == 0:
                cell = "  ."
            elif is_blocked and behavior == 0:
                cell = "  #"
            elif is_blocked and behavior != 0:
                cell = f" {behavior:02x}"
                behaviors_seen[behavior] = "blocked"
            elif behavior == 0x00:
                cell = "  _"
            elif behavior == 0x08:
                cell = "   "
            else:
                cell = f" {behavior:02x}"
                behaviors_seen[behavior] = "passable"

            line += cell
        lines.append(line)

    lines.append("")
    lines.append("Legend:")
    lines.append("  ^v<> = player (facing direction)")
    lines.append("  A-Z, a-z = NPC/dynamic object")
    lines.append("  .    = void  #  = wall  _  = walkable ground")
    lines.append("  xx   = tile behavior (hex)")

    if behaviors_seen:
        lines.append("")
        lines.append("Behaviors:")
        for beh, passability in sorted(behaviors_seen.items()):
            name = BEHAVIORS.get(beh, "unknown")
            lines.append(f"  {beh:02x} = {passability} ({name})")

    return "\n".join(lines)


def view_map(emu: EmulatorClient) -> dict[str, Any]:
    """Get full map view with ASCII rendering and metadata."""
    state = get_map_state(emu)
    if state is None:
        return {"error": "Could not resolve map chunk", "map": "", "player": {}, "objects": []}

    facing_name = FACING_NAMES.get(state["facing"], "?")
    map_str = render_map(
        state["terrain"], state["objects"],
        state["local_px"], state["local_py"], state["facing"],
    )

    # Build header
    if state["chunked"]:
        chunk_cx = state["px"] // CHUNK_SIZE
        chunk_cy = state["py"] // CHUNK_SIZE
        header = (
            f"Map {state['map_id']} — Player at ({state['px']}, {state['py']}) "
            f"facing {facing_name}\n"
            f"Chunk ({chunk_cx}, {chunk_cy}) — "
            f"origin ({state['origin_x']}, {state['origin_y']}) — "
            f"local ({state['local_px']}, {state['local_py']})"
        )
    else:
        header = f"Map {state['map_id']} — Player at ({state['px']}, {state['py']}) facing {facing_name}"

    # Object list
    obj_info = []
    for obj in state["objects"]:
        idx = obj["index"]
        if 1 <= idx <= 26:
            letter = chr(ord("A") + idx - 1)
        elif 27 <= idx <= 52:
            letter = chr(ord("a") + idx - 27)
        else:
            letter = f"#{idx}"
        name = obj.get("name", "")
        if idx == 0:
            label = "PLAYER"
        elif name:
            label = f"{name} ({letter})"
        else:
            label = f"NPC {letter}"
        entry: dict[str, Any] = {
            "index": idx,
            "label": label,
            "x": obj["x"], "y": obj["y"],
            "local_x": obj["local_x"], "local_y": obj["local_y"],
        }
        if "movement_type" in obj:
            entry["movement"] = obj["movement_type"]
        if obj.get("trainer_type", 0) > 0:
            entry["trainer"] = True
        obj_info.append(entry)

    # Warp destinations within displayed grid
    origin_x = state["origin_x"]
    origin_y = state["origin_y"]
    terrain = state["terrain"]
    grid_h = len(terrain)
    grid_w = len(terrain[0]) if grid_h > 0 else 0

    all_warps = read_warps_from_rom(emu, state["map_id"])
    warp_info = []
    for w in all_warps:
        lx = w["x"] - origin_x
        ly = w["y"] - origin_y
        if 0 <= lx < grid_w and 0 <= ly < grid_h:
            dest = lookup_map_name(w["dest_map"])
            warp_info.append({
                "x": w["x"], "y": w["y"],
                "dest_name": dest["name"],
                "dest_map_id": w["dest_map"],
            })

    return {
        "map": header + "\n\n" + map_str,
        "map_id": state["map_id"],
        "player": {
            "x": state["px"], "y": state["py"],
            "local_x": state["local_px"], "local_y": state["local_py"],
            "facing": facing_name,
        },
        "origin": {"x": state["origin_x"], "y": state["origin_y"]},
        "chunked": state["chunked"],
        "objects": obj_info,
        "warps": warp_info,
    }
