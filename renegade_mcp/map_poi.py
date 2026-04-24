"""POI classification, warp/sign reading, and interactible construction.

This module reads the ROM zone_event data (warps + sign objects) and
classifies dynamic NPC/item/berry objects. It also builds the
player-facing `interactibles` list consumed by view_map — with
reachability annotations, merged warp clusters, and per-kind previews.

Depends on map_terrain (constants, sign GFX ids) and map_elevation
(read_player_height for the cycling-road under-bridge disambiguation).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.addresses import ZONE_HEADER_BASE, ZONE_HEADER_STRIDE
from renegade_mcp.map_elevation import read_player_height
from renegade_mcp.map_names import lookup_map_name
from renegade_mcp.map_terrain import (
    CYCLING_ROAD_BRIDGE_BEHAVIORS,
    SIGN_GFX_IDS,
    ZONE_EVENT_DIR,
    _BG_EVENT_SIZE,
    _EVENTS_ARCHIVE_OFFSET,
    _OBJ_EVENT_SIZE,
    _WARP_EVENT_SIZE,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def is_on_cycling_road(emu: EmulatorClient, target_x: int = -1, target_y: int = -1) -> bool:
    """Check if player or target is on cycling road bridge tiles while cycling.

    The cycling road (Route 206) forces downhill sliding when the player is
    on the bicycle and standing on bridge tiles (behaviors 0x70/0x71). Detection
    uses tile behavior + cycling state rather than script flags, since the runtime
    flag (PlayerAvatar.unk_00) isn't in save RAM.

    When target coordinates are provided, also checks if the path between player
    and target would cross bridge body tiles (0x71) — catches the case where the
    player is just above the bridge but the target is on it. The column-scan
    heuristic is gated on player *elevation* (BUG-030): under-bridge players
    on ground tiles share the bridge's 2D column but are physically below it,
    so the slide mode must not engage for them.
    """
    from renegade_mcp.addresses import addr
    from renegade_mcp.map_state import get_map_state

    cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
    if not cycling:
        return False

    state = get_map_state(emu)
    if state is None:
        return False

    terrain = state["terrain"]
    lx, ly = state["local_px"], state["local_py"]
    ox = state.get("origin_x", 0)
    oy = state.get("origin_y", 0)

    # Check current tile
    if 0 <= ly < len(terrain) and 0 <= lx < len(terrain[ly]):
        behavior = terrain[ly][lx] & 0x00FF
        if behavior in CYCLING_ROAD_BRIDGE_BEHAVIORS:
            return True

    # Column-scan heuristic for "player about to step onto bridge body from
    # above". Skipping a naive target-tile behavior check — `bridge_start`
    # (0x70) appears as bookend tiles on Wayward-style bike bridges that
    # are NOT forced-slide, and triggering cycling_road dispatch for
    # those produces a false positive (the Wayward bridges are bike-
    # required but not auto-slide).
    # Only valid when the player is actually at bridge elevation —
    # an under-bridge player on ground shares the bridge's 2D column but is
    # physically below it, and sliding would be wrong. Compare player
    # height to typical bridge body height (>= 40 in fx32 units for Cycling
    # Road's L3 bridge body). Skip scan if we can't read height.
    if target_x >= 0 and target_y >= 0:
        tlx = target_x - ox
        tly = target_y - oy

        try:
            player_h = read_player_height(emu)
        except Exception:
            player_h = None

        if player_h is None or player_h >= 40:
            min_y = min(ly, tly)
            max_y = max(ly, tly)
            check_x = lx  # scan along player's column
            for scan_y in range(min_y, max_y + 1):
                if 0 <= scan_y < len(terrain) and 0 <= check_x < len(terrain[scan_y]):
                    scan_b = terrain[scan_y][check_x] & 0x00FF
                    if scan_b == 0x71:  # bridge body = auto-slide
                        return True

    return False


def read_warps_from_rom(emu: EmulatorClient, map_id: int) -> list[dict[str, int]]:
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


def read_sign_tiles_from_rom(emu: EmulatorClient, map_id: int) -> list[tuple[int, int]]:
    """Read sign obstacle tiles from ROM zone_event data.

    Returns both the sign tile itself (impassable object) and the activation
    tile one south of it (auto-triggers dialogue when facing north).
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

    # Read Object events, extract sign positions
    num_obj = struct.unpack_from("<I", data, off)[0]; off += 4
    tiles = []
    for _ in range(num_obj):
        gfx_id = struct.unpack_from("<H", data, off + 0x02)[0]
        if gfx_id in SIGN_GFX_IDS:
            sign_x = struct.unpack_from("<H", data, off + 0x18)[0]
            sign_y = struct.unpack_from("<H", data, off + 0x1A)[0]
            tiles.append((sign_x, sign_y))        # sign tile itself (impassable)
            tiles.append((sign_x, sign_y + 1))  # activation tile one south
        off += _OBJ_EVENT_SIZE

    return tiles


# ── Interactibles: reachable POIs (dynamic objects + merged warps) ──

# Dynamic-object graphics ids that classify as non-NPC POIs.
_GFX_POKEBALL = 87
_GFX_BERRY = 100

# Adjacency offsets used to find an interaction tile next to a POI.
# (adj_dx, adj_dy, face_direction): `adj_dx/dy` is the displacement FROM
# the POI tile TO the interaction tile; `face_direction` is the direction
# the player must face to see the POI from that adjacent tile.
_INTERACTIBLE_ADJ = (
    (0, -1, "down"),   # adjacent tile is north of POI → face down
    (0, 1, "up"),      # south → face up
    (-1, 0, "right"),  # west → face right
    (1, 0, "left"),    # east → face left
)


def _merge_adjacent_warps(
    warps: list[dict[str, int]],
    reachable_tiles: dict[tuple[int, int], int],
    player_x: int, player_y: int,
    reach_info_3d: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Cluster warps that share a destination AND are 4-adjacent.

    Returns a list of cluster dicts with keys:
      - dest_map, dest_warp: destination identity
      - tiles: list of (x, y) for every constituent warp
      - interaction_xy: (x, y) of the representative tile (nearest
        reachable to the player; falls back to nearest-Manhattan if no
        constituent is reachable)
      - reachable: bool
      - metric: BFS steps when reachable, Manhattan distance otherwise
    """
    by_dest: dict[tuple[int, int], list[dict[str, int]]] = {}
    for w in warps:
        by_dest.setdefault((w["dest_map"], w["dest_warp"]), []).append(w)

    clusters: list[dict[str, Any]] = []
    for (dest_map, dest_warp), group in by_dest.items():
        # 4-connectivity union-find within the group.
        unmerged = list(group)
        while unmerged:
            seed = unmerged.pop(0)
            current = [seed]
            changed = True
            while changed:
                changed = False
                i = 0
                while i < len(unmerged):
                    w = unmerged[i]
                    if any(
                        abs(w["x"] - c["x"]) + abs(w["y"] - c["y"]) == 1
                        for c in current
                    ):
                        current.append(unmerged.pop(i))
                        changed = True
                    else:
                        i += 1

            # Pick the representative interaction tile.
            # On 3D maps, a warp is reachable only if the BFS reached its
            # tile at a level the tile actually has (level_map entry).
            # Falls back to plain 2D lookup when 3D info isn't available.
            best_reach: tuple[int, tuple[int, int]] | None = None
            best_manh: tuple[int, tuple[int, int]] | None = None
            for w in current:
                wx, wy = w["x"], w["y"]
                reach_s: int | None = None
                if reach_info_3d is not None:
                    elev = reach_info_3d["elevation"]
                    ox, oy = reach_info_3d["origin"]
                    reach3d = reach_info_3d["reach"]
                    level_map = elev["level_map"]
                    ramp_tiles = elev["ramp_tiles"]
                    lx, ly = wx - ox, wy - oy
                    tile_levels = level_map.get((lx, ly))
                    if tile_levels is None:
                        ri = ramp_tiles.get((lx, ly))
                        if ri is not None:
                            tile_levels = [ri["from_level"], ri["to_level"]]
                    if tile_levels is None:
                        # Tile not in BDHC → treat as any-level passable.
                        if (wx, wy) in reachable_tiles:
                            reach_s = reachable_tiles[(wx, wy)]
                    else:
                        for lv in tile_levels:
                            s3 = reach3d.get((wx, wy, lv))
                            if s3 is not None and (
                                reach_s is None or s3 < reach_s
                            ):
                                reach_s = s3
                elif (wx, wy) in reachable_tiles:
                    reach_s = reachable_tiles[(wx, wy)]

                if reach_s is not None:
                    if best_reach is None or reach_s < best_reach[0]:
                        best_reach = (reach_s, (wx, wy))
                d = abs(wx - player_x) + abs(wy - player_y)
                if best_manh is None or d < best_manh[0]:
                    best_manh = (d, (wx, wy))

            if best_reach is not None:
                clusters.append({
                    "dest_map": dest_map,
                    "dest_warp": dest_warp,
                    "tiles": [(w["x"], w["y"]) for w in current],
                    "interaction_xy": best_reach[1],
                    "reachable": True,
                    "metric": best_reach[0],
                })
            else:
                assert best_manh is not None
                clusters.append({
                    "dest_map": dest_map,
                    "dest_warp": dest_warp,
                    "tiles": [(w["x"], w["y"]) for w in current],
                    "interaction_xy": best_manh[1],
                    "reachable": False,
                    "metric": best_manh[0],
                })

    return clusters


def _classify_object(
    obj: dict[str, Any], map_id: int,
) -> tuple[str, int | None, dict[str, Any]]:
    """Decide the interactible kind for a dynamic object.

    Returns (kind, resolved_trainer_id_or_None, preview_dict).
    `preview_dict` always includes `object_index` for dispatch. For
    trainers, the caller (which has `emu` in scope) fills in the
    `defeated` field — this helper stops at identity data.
    """
    from renegade_mcp.trainer import (
        is_flavor_trainer,
        lookup_trainer_class,
        trainer_id_from_script,
    )

    idx = obj["index"]
    gfx_id = obj.get("graphics_id", 0)
    sprite_name = (obj.get("name", "") or "").strip()
    trainer_type = obj.get("trainer_type", 0)
    preview: dict[str, Any] = {"object_index": idx}

    if trainer_type > 0:
        tid = trainer_id_from_script(obj.get("script", 0))
        if tid is not None and is_flavor_trainer(map_id, tid):
            preview["flavor_npc"] = True
            return "npc", tid, preview
        if tid is not None:
            trainer_class = lookup_trainer_class(tid)
            preview["trainer_id"] = tid
            if trainer_class is not None:
                preview["trainer_class"] = trainer_class
            if sprite_name and trainer_class and sprite_name != trainer_class:
                preview["sprite_name"] = sprite_name
            return "trainer", tid, preview

    if gfx_id in SIGN_GFX_IDS:
        return "sign", None, preview
    if gfx_id == _GFX_POKEBALL:
        return "item", None, preview
    if gfx_id == _GFX_BERRY:
        # Soil objects store the MiscSaveBlock berry-patch index in data[0].
        # The actual patch state read happens in _build_interactibles where
        # `emu` is in scope.
        patch_id = obj.get("data0")
        if isinstance(patch_id, int) and 0 <= patch_id < 128:
            preview["patch_id"] = patch_id
        return "berry", None, preview
    if sprite_name:
        return "npc", None, preview
    return "object", None, preview


def _build_interactibles(
    emu: EmulatorClient,
    map_id: int,
    objects: list[dict[str, Any]],
    reachable_tiles: dict[tuple[int, int], int],
    player_x: int, player_y: int,
    reach_info_3d: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Construct (reachable, unreachable) interactibles lists.

    `reachable_tiles` must be keyed by GLOBAL tile coords. Objects and
    warps whose interaction tile is in `reachable_tiles` are sorted by
    BFS steps; the rest are reported unreachable with Manhattan distance.

    Entries carry: id, kind, label, x/y (POI), interaction_x/y, face,
    steps (or distance), preview.
    """
    from renegade_mcp.berry_patches import read_patch
    from renegade_mcp.trainer import is_trainer_defeated

    reachable: list[dict[str, Any]] = []
    unreachable: list[dict[str, Any]] = []

    # --- Dynamic objects ---
    for obj in objects:
        idx = obj["index"]
        if idx == 0:
            continue  # player
        gx, gy = obj["x"], obj["y"]
        # Drayano left many unused zone_event entries in place (he disables
        # rather than deletes objects); the engine parks them at (0, 0).
        # They clutter `unreachable_interactibles` without being
        # actionable — filter them out regardless of kind.
        if gx == 0 and gy == 0:
            continue

        kind, tid, preview = _classify_object(obj, map_id)
        sprite_name = (obj.get("name", "") or "").strip()

        # Label — prefer authoritative trainer class, else sprite name, else generic.
        if kind == "trainer":
            trainer_class = preview.get("trainer_class")
            label = trainer_class or sprite_name or f"Trainer {tid}"
            # Fill in defeated bit now that we have emu in scope.
            if tid is not None:
                preview["defeated"] = is_trainer_defeated(emu, tid)
        elif kind == "sign":
            label = sprite_name or "Sign"
        elif kind == "item":
            label = sprite_name or "Item Ball"
        elif kind == "berry":
            # Resolve the soil's patch state now that emu is in scope.
            patch_id = preview.get("patch_id")
            patch_state: dict[str, Any] | None = None
            if isinstance(patch_id, int):
                patch_state = read_patch(emu, patch_id)
            if patch_state is not None:
                preview["patch"] = patch_state
            if patch_state is None or not patch_state.get("planted"):
                label = sprite_name or "Empty Berry Patch"
            elif patch_state.get("harvestable"):
                label = (
                    f"{patch_state['berry']} Berry (ripe x{patch_state['yield']})"
                )
            else:
                label = (
                    f"{patch_state['berry']} Berry ({patch_state['growth_stage']})"
                )
        elif kind == "npc":
            label = sprite_name or f"NPC {idx}"
        else:
            label = sprite_name or f"Object {idx}"

        # Find best interaction tile.
        # On 3D maps, the adjacent tile is only a valid approach if the
        # BFS reached it at the object's own level — a ground-level tile
        # under a bridge trainer doesn't let the player interact with
        # someone standing 8 tiles above them in the Y axis.
        best: tuple[int, int, int, str] | None = None  # (steps, adj_x, adj_y, face)
        obj_level: int | None = None
        if reach_info_3d is not None:
            obj_level = reach_info_3d["object_levels"].get(idx)
        for adj_dx, adj_dy, face in _INTERACTIBLE_ADJ:
            adj_gx, adj_gy = gx + adj_dx, gy + adj_dy
            s: int | None = None
            if reach_info_3d is not None and obj_level is not None:
                s = reach_info_3d["reach"].get((adj_gx, adj_gy, obj_level))
            elif (adj_gx, adj_gy) in reachable_tiles:
                s = reachable_tiles[(adj_gx, adj_gy)]
            if s is not None and (best is None or s < best[0]):
                best = (s, adj_gx, adj_gy, face)

        entry: dict[str, Any] = {
            "id": f"obj:{idx}",
            "kind": kind,
            "label": label,
            "x": gx, "y": gy,
            "preview": preview,
        }
        if best is not None:
            s, adj_gx, adj_gy, face = best
            entry["interaction_x"] = adj_gx
            entry["interaction_y"] = adj_gy
            entry["face"] = face
            entry["steps"] = s
            reachable.append(entry)
        else:
            entry["distance"] = abs(gx - player_x) + abs(gy - player_y)
            unreachable.append(entry)

    # --- Warps (merged by destination + adjacency) ---
    all_warps = read_warps_from_rom(emu, map_id)
    clusters = _merge_adjacent_warps(
        all_warps, reachable_tiles, player_x, player_y,
        reach_info_3d=reach_info_3d,
    )
    warp_idx = 0
    for c in clusters:
        dest = lookup_map_name(c["dest_map"])
        dest_name = dest.get("name", f"Map {c['dest_map']}")
        ix, iy = c["interaction_xy"]
        preview = {
            "dest_map_id": c["dest_map"],
            "dest_map_name": dest_name,
            "dest_warp": c["dest_warp"],
        }
        if len(c["tiles"]) > 1:
            preview["merged_tile_count"] = len(c["tiles"])
        entry = {
            "id": f"warp:{warp_idx}",
            "kind": "warp",
            "label": f"to {dest_name}",
            "x": ix, "y": iy,
            "interaction_x": ix, "interaction_y": iy,
            "face": None,
            "preview": preview,
        }
        warp_idx += 1
        if c["reachable"]:
            entry["steps"] = c["metric"]
            reachable.append(entry)
        else:
            entry["distance"] = c["metric"]
            unreachable.append(entry)

    reachable.sort(key=lambda e: e["steps"])
    unreachable.sort(key=lambda e: e["distance"])
    return reachable, unreachable
