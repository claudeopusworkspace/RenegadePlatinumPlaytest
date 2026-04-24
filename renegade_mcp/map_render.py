"""ASCII map rendering with axis rulers and viewport calculation.

Pure formatting: takes pre-computed terrain, object, and elevation data
and produces human-readable text. Does not read the emulator. Depends
only on map_terrain for shared constants (BEHAVIORS, FACING_ARROWS,
CHUNK_SIZE, load_terrain_from_rom).
"""

from __future__ import annotations

from renegade_mcp.map_terrain import BEHAVIORS, CHUNK_SIZE, FACING_ARROWS, load_terrain_from_rom


def _compute_viewport_bounds(
    px: int, py: int,
    matrix_w: int, matrix_h: int,
    terrain_ids: list[list[int]],
    terrain: list[list[int]],
    origin_x: int, origin_y: int,
    objects: list[dict],
    chunked: bool,
    viewport_size: int = 15,
) -> tuple[int, int, int, int]:
    """Compute viewport rectangle in global tile coordinates.

    Indoor/small maps: returns tight content bounds (preserves compact rendering).
    Overworld/multi-chunk maps: returns viewport_size x viewport_size centered on
    player, clamped to world edges.

    Returns (vp_x, vp_y, vp_w, vp_h).
    """
    if not chunked:
        # Indoor / single-chunk: find content bounds (existing crop logic)
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
            lx = obj["x"] - origin_x
            ly = obj["y"] - origin_y
            if 0 <= lx < 32 and 0 <= ly < 32:
                min_row = min(min_row, ly)
                max_row = max(max_row, ly)
                min_col = min(min_col, lx)
                max_col = max(max_col, lx)

        # 1-tile padding
        min_row = max(0, min_row - 1)
        max_row = min(31, max_row + 1)
        min_col = max(0, min_col - 1)
        max_col = min(31, max_col + 1)

        return (
            origin_x + min_col,
            origin_y + min_row,
            max_col - min_col + 1,
            max_row - min_row + 1,
        )

    # Overworld / multi-chunk: center on player, clamp to world bounds
    world_w = matrix_w * CHUNK_SIZE
    world_h = matrix_h * CHUNK_SIZE

    vp_w = min(viewport_size, world_w)
    vp_h = min(viewport_size, world_h)

    vp_x = px - vp_w // 2
    vp_y = py - vp_h // 2

    # Clamp to world edges
    vp_x = max(0, min(vp_x, world_w - vp_w))
    vp_y = max(0, min(vp_y, world_h - vp_h))

    return (vp_x, vp_y, vp_w, vp_h)


def _load_viewport_terrain(
    terrain_ids: list[list[int]],
    matrix_w: int, matrix_h: int,
    vp_x: int, vp_y: int, vp_w: int, vp_h: int,
) -> list[list[int]]:
    """Load and composite raw tile values for the viewport from ROM chunks.

    Returns a vp_h x vp_w grid of u16 tile values (same format as
    load_terrain_from_rom). Tiles from missing/void chunks are 0.
    """
    grid = [[0] * vp_w for _ in range(vp_h)]

    # Determine which chunks overlap the viewport
    cx_min = vp_x // CHUNK_SIZE
    cx_max = (vp_x + vp_w - 1) // CHUNK_SIZE
    cy_min = vp_y // CHUNK_SIZE
    cy_max = (vp_y + vp_h - 1) // CHUNK_SIZE

    for cy in range(cy_min, cy_max + 1):
        for cx in range(cx_min, cx_max + 1):
            if not (0 <= cx < matrix_w and 0 <= cy < matrix_h):
                continue
            land_id = terrain_ids[cy][cx]
            if land_id == 0xFFFF:
                continue

            chunk_terrain = load_terrain_from_rom(land_id)
            if chunk_terrain is None:
                continue

            # Copy the overlapping sub-rectangle from this chunk into the grid
            chunk_global_x = cx * CHUNK_SIZE
            chunk_global_y = cy * CHUNK_SIZE

            # Overlap region in global coords
            ox_start = max(vp_x, chunk_global_x)
            oy_start = max(vp_y, chunk_global_y)
            ox_end = min(vp_x + vp_w, chunk_global_x + CHUNK_SIZE)
            oy_end = min(vp_y + vp_h, chunk_global_y + CHUNK_SIZE)

            for gy in range(oy_start, oy_end):
                for gx in range(ox_start, ox_end):
                    grid[gy - vp_y][gx - vp_x] = chunk_terrain[gy - chunk_global_y][gx - chunk_global_x]

    return grid


def render_map(
    terrain: list, objects: list, player_local_x: int, player_local_y: int,
    facing: int, elevation: dict | None = None, player_level: int | None = None,
    filter_level: int | None = None,
) -> str:
    """Render a compact 1-char-per-tile ASCII map.

    Symbols: ^v<> player, A-Za-z NPCs, # wall, _ walkable floor,
    · cave floor, . void (outside map), ≈ water, " grass,
    0-9 elevation, /\\ ramps, ][ directional blocks.
    Hex behaviors mapped to single chars with a key when present.

    The terrain grid IS the viewport — render it all, no cropping needed.
    Objects' local_x/local_y are viewport-relative. Elevation keys are
    also viewport-relative when provided.
    """
    # 1-char behavior symbols for common hex behaviors
    _BEHAVIOR_CHAR: dict[int, str] = {
        0x00: '_',  # walkable ground
        0x02: '"', 0x03: '"',  # grass
        0x08: '·',  # cave / dungeon floor (distinct from '.' void)
        0x10: '≈', 0x13: '≈', 0x15: '≈',  # water
        0x20: '=', 0x21: ',',  # ice, sand
        0x30: ']', 0x31: '[',  # directional blocks
        0x38: '>', 0x39: '<', 0x3A: '^', 0x3B: 'v',  # ledges (arrow = jump direction)
        0x5E: '/', 0x5F: '\\',  # stairs
        0x69: 'D', 0x6E: 'D',  # doors
        0x62: '+', 0x63: '+', 0x64: '+', 0x65: '+', 0x67: '+',  # warps
        0x6A: '%', 0x6B: '%',  # escalators
        0x6C: '|', 0x6D: '|', 0x6F: '-',  # sides
        0x70: 'n', 0x71: 'n',  # bridge start/body
        0x72: 'n', 0x73: 'n', 0x74: 'n', 0x75: 'n',  # bridge-over variants
        0x76: 'n', 0x77: 'n', 0x78: 'n', 0x79: 'n',  # bike bridge N-S
        0x7A: 'n', 0x7B: 'n', 0x7C: 'n', 0x7D: 'n',  # bike bridge E-W
        0x80: ':',  # counter
        0xA1: '~', 0xA2: '~', 0xA3: '~',  # snow (deep/deeper/deepest)
        0xA8: '~', 0xA9: '~',  # snow (shallow/shadows)
        0xD9: '\\', 0xDA: '/',  # bike slope top/bottom
        0xD7: '>', 0xD8: '<',  # bike ramps (jump E/W on bike)
    }

    grid_h = len(terrain)
    grid_w = len(terrain[0]) if grid_h > 0 else 0

    obj_at = {}
    for obj in objects:
        lx, ly = obj["local_x"], obj["local_y"]
        if 0 <= lx < grid_w and 0 <= ly < grid_h:
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

    level_map = elevation["level_map"] if elevation else {}
    ramp_tiles = elevation["ramp_tiles"] if elevation else {}

    lines = []
    behaviors_seen: dict[int, str] = {}

    for row in range(grid_h):
        line_chars = []
        for col in range(grid_w):
            val = terrain[row][col]
            is_blocked = (val & 0x8000) != 0
            behavior = val & 0x00FF
            key = (col, row)

            tile_levels = level_map.get(key, [])
            is_filtered_out = (
                filter_level is not None
                and elevation
                and not is_blocked
                and key not in obj_at
                and tile_levels
                and filter_level not in tile_levels
                and key not in ramp_tiles
            )

            if is_filtered_out:
                ch = '~'
            elif key in obj_at:
                ch = obj_at[key]
            elif is_blocked and behavior == 0:
                ch = '#'
            elif is_blocked and behavior in _BEHAVIOR_CHAR:
                ch = _BEHAVIOR_CHAR[behavior]
                behaviors_seen[behavior] = "blocked"
            elif is_blocked:
                ch = '#'
                behaviors_seen[behavior] = "blocked"
            elif elevation and key in ramp_tiles:
                ri = ramp_tiles[key]
                if filter_level is not None and filter_level not in (ri["from_level"], ri["to_level"]):
                    ch = '~'
                else:
                    ch = '\\' if ri["direction"] in ("south", "east") else '/'
            elif elevation and key in level_map and len(level_map[key]) > 1:
                ch = str(level_map[key][-1])  # bridge — show upper level
            elif elevation and behavior in (0x30, 0x31):
                ch = _BEHAVIOR_CHAR[behavior]
            elif elevation and key in level_map and (val == 0 or behavior in (0x00, 0x08)):
                ch = str(level_map[key][0])
            elif val == 0:
                ch = '.'
            elif behavior in _BEHAVIOR_CHAR:
                ch = _BEHAVIOR_CHAR[behavior]
                behaviors_seen[behavior] = "passable"
            else:
                ch = '?'
                behaviors_seen[behavior] = "passable"

            line_chars.append(ch)
        lines.append("".join(line_chars))

    # Compact key — only show behaviors actually seen on this map
    if behaviors_seen:
        key_parts = []
        for beh in sorted(behaviors_seen):
            name = BEHAVIORS.get(beh, f"0x{beh:02x}")
            ch = _BEHAVIOR_CHAR.get(beh, "?")
            key_parts.append(f"{ch}={name}")
        lines.append("Key: " + " ".join(key_parts))

    # Elevation summary (compact single line)
    if elevation:
        parts = [f"L{lv['level']}{'*' if player_level is not None and lv['level'] == player_level else ''}" for lv in elevation["levels"]]
        lines.append(f"Elevation: {' '.join(parts)}")

    return "\n".join(lines)


def _render_with_axes(
    grid_str: str, vp_x: int, vp_y: int, vp_w: int, vp_h: int,
) -> str:
    """Prefix a rendered grid with an X-axis ruler + per-row Y labels.

    The ruler shows the *last digit* of each column's absolute X coordinate
    (a visual anchor that survives tokenization better than spacing — see
    "Stuck in the Matrix", arxiv 2510.20198). The Y column uses the full
    absolute Y, right-aligned to 3 chars. Trailing lines from render_map
    (Key:..., Elevation:...) are passed through untouched.
    """
    lines = grid_str.split("\n")
    grid_rows = lines[:vp_h]
    trailing = lines[vp_h:]

    x_ruler = "".join(str((vp_x + i) % 10) for i in range(vp_w))
    out: list[str] = [f"    {x_ruler}"]
    for i, row in enumerate(grid_rows):
        out.append(f"{vp_y + i:3d} {row}")
    out.extend(trailing)
    return "\n".join(out)
