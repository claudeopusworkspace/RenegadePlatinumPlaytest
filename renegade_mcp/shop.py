"""PokéMart inventory lookup and purchasing.

Mart data is sourced from the ROM (mart_items.h in the decompilation).
Item prices come from pl_item_data.narc (extracted to data/item_prices.json).

Three inventory systems:
  1. Common items — shared across all standard PokéMarts, badge-gated.
  2. Specialty items — unique per city, always available.
  3. Veilstone Dept Store — per-floor, per-cashier fixed lists (no badge gating,
     no common stock mixed in). Each cashier sells one named category.

Badge-gating uses the same switch logic as the game (scrcmd_shop.c):
  0 badges → threshold 1, 1-2 → 2, 3-4 → 3, 5-6 → 4, 7 → 5, 8 → 6

PokéMart rooms use city code prefix "FS" (Friendly Shop).
All standard marts share identical layouts:
  - Cashier F at (3, 5) — common items
  - Cashier M at (2, 5) — specialty items
  - Exit warp at (3, 11)

Veilstone Dept Store rooms use code prefix "C07R02" (1F=01 … B1F=07).
Floors carry 1-2 vendor counters each, and 2F has two "Cashier F" NPCs at
different tiles — so dept-store cashier lookup matches by NPC name + coords,
not name alone.

If called from a city/town overworld, auto-navigates to the mart (or to
the Veilstone Dept Store 1F entrance if in Veilstone).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import item_names, item_prices, map_table

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Common mart items: (item_id, badge_threshold) ──
# Every standard PokéMart sells these, filtered by the player's badge count.
# Data from: ref/pokeplatinum/include/data/mart_items.h PokeMartCommonItems[]
COMMON_MART_ITEMS: list[tuple[int, int]] = [
    (4, 1),    # Poké Ball
    (3, 3),    # Great Ball
    (2, 4),    # Ultra Ball
    (17, 1),   # Potion
    (26, 2),   # Super Potion
    (25, 4),   # Hyper Potion
    (24, 5),   # Max Potion
    (23, 6),   # Full Restore
    (28, 3),   # Revive
    (18, 1),   # Antidote
    (22, 1),   # Parlyz Heal
    (21, 2),   # Awakening
    (19, 2),   # Burn Heal
    (20, 2),   # Ice Heal
    (27, 4),   # Full Heal
    (78, 2),   # Escape Rope
    (79, 2),   # Repel
    (76, 3),   # Super Repel
    (77, 4),   # Max Repel
]

# Badge count → threshold value (from scrcmd_shop.c switch statement)
_BADGE_THRESHOLDS: dict[int, int] = {
    0: 1, 1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 5, 8: 6,
}

# ── Specialty marts: city_code → list of item IDs ──
# Each city's PokéMart has additional unique items alongside the common stock.
# Data from: ref/pokeplatinum/include/data/mart_items.h PokeMartSpecialties[]
SPECIALTY_MARTS: dict[str, list[int]] = {
    "C01": [146, 14],              # Jubilife: Air Mail, Heal Ball
    "C02": [146, 15, 10, 9],      # Canalave: Air Mail, Quick Ball, Timer Ball, Repeat Ball
    "C03": [141, 14, 6],          # Oreburgh: Tunnel Mail, Heal Ball, Net Ball
    "C04": [146, 14, 6, 8],      # Eterna: Air Mail, Heal Ball, Net Ball, Nest Ball
    "C05": [143, 14, 6, 8],      # Hearthome: Heart Mail, Heal Ball, Net Ball, Nest Ball
    "C06": [146, 8, 13, 15],     # Pastoria: Air Mail, Nest Ball, Dusk Ball, Quick Ball
    # C07 (Veilstone) = Dept Store — not a standard mart, skipped
    "C08": [142, 11],            # Sunyshore: Steel Mail, Luxury Ball
    "C09": [144, 13, 15, 10],    # Snowpoint: Snow Mail, Dusk Ball, Quick Ball, Timer Ball
    "C10": [14, 6, 8, 13, 15, 10, 9, 11],  # Pokémon League (all specialty balls)
    "T03": [140, 14, 6],         # Floaroma: Bloom Mail, Heal Ball, Net Ball
    "T04": [146, 6, 8, 13],     # Solaceon: Air Mail, Net Ball, Nest Ball, Dusk Ball
    "T05": [146, 13, 15, 10],   # Celestic: Air Mail, Dusk Ball, Quick Ball, Timer Ball
}


def _badge_threshold(badge_count: int) -> int:
    """Convert badge count to mart item availability threshold."""
    return _BADGE_THRESHOLDS.get(badge_count, 1)


# ── Veilstone Dept Store ──
# Each floor has 1-2 vendor counters; each counter sells a fixed item list
# (no badge gating, no common items mixed in). Cashier coords use the same
# (x, y) convention as `read_objects` — events JSON's "z" field is engine "y".
#
# Skipped (different UIs / out of scope for now):
#   - 4F: decoration/doll shop (Shop_Start with MART_TYPE_DECORATION)
#   - 5F: no shops, only collectors
#   - B1F: Lava Cookie / Poffin / Rage Candy Bar vendors (custom press flows)
#
# Source: ref/pokeplatinum/include/data/mart_items.h VeilstoneDeptStoreStock_*[]
# Cashier coords: ref/pokeplatinum/res/field/events/events_veilstone_store_*.json
# Renegade Platinum may have edited TM lists in the binary scripts; if read_shop
# disagrees with the in-game menu, this table is the place to fix.
DEPT_STORE_CASHIERS: dict[str, list[dict]] = {
    # 1F: code C07R0201
    "C07R0201": [
        {
            "npc": "Cashier F", "x": 3, "y": 5,
            "label": "Potions & status healing",
            "items": [17, 26, 25, 24, 28, 18, 22, 19, 20, 21, 27],
        },
        {
            "npc": "Cashier M", "x": 2, "y": 5,
            "label": "Balls, repels & mail",
            "items": [4, 3, 2, 78, 63, 79, 76, 77, 137, 138, 139, 145],
        },
    ],
    # 2F: code C07R0202 — two "Cashier F" NPCs at different tiles.
    "C07R0202": [
        {
            "npc": "Cashier F", "x": 2, "y": 4,
            "label": "Battle X items",
            "items": [59, 57, 58, 55, 56, 60, 61, 62],
        },
        {
            "npc": "Cashier F", "x": 2, "y": 6,
            "label": "Vitamins (stat boosters)",
            "items": [46, 47, 49, 52, 48, 45],
        },
    ],
    # 3F: code C07R0203 — Renegade Platinum replaced both of vanilla's TM lists
    # with evolution stones, split into two themed counters. Both cashiers are
    # talked to ACROSS the counter strip (player one tile south of counter,
    # press A facing up/down). view_map's BFS doesn't model counter-talk and
    # will list both as "unreachable" — `interact_with` has the across-counter
    # fallback that drives the actual navigation.
    "C07R0203": [
        {
            "npc": "Cashier F", "x": 3, "y": 4,
            "label": "Evolution stones",
            "items": [82, 457, 85, 81, 80, 83, 84],  # Fire/Ice/Leaf/Moon/Sun/Thunder/Water
        },
        {
            "npc": "Cashier M", "x": 3, "y": 11,
            "label": "Special evolution stones",
            "items": [109, 108, 229, 238, 110, 107],  # Dawn/Dusk/Everstone/Hard/Oval/Shiny
        },
    ],
    # B1F: code C07R0207 — Berry vendor only (Lava Cookie/Poffin counters skipped).
    "C07R0207": [
        {
            "npc": "Cashier F", "x": 5, "y": 11,
            "label": "Berries",
            "items": [159, 160, 161, 162, 163],
        },
    ],
}

# Display labels and read_shop messages for every dept-store interior,
# including non-shop floors. (`message` is shown when the floor has no
# entry in DEPT_STORE_CASHIERS.)
DEPT_STORE_FLOORS: dict[str, dict] = {
    "C07R0201": {"name": "1F"},
    "C07R0202": {"name": "2F"},
    "C07R0203": {"name": "3F"},
    "C07R0204": {"name": "4F", "message": "4F is the decoration / doll counter — not yet supported."},
    "C07R0205": {"name": "5F", "message": "5F has no purchasable shop (collectors only)."},
    "C07R0206": {"name": "Elevator", "message": "Elevator — pick a floor, no shop here."},
    "C07R0207": {"name": "B1F"},
}

DEPT_STORE_FLOOR_NAMES: dict[str, str] = {
    code: floor["name"] for code, floor in DEPT_STORE_FLOORS.items()
}

# Veilstone overworld → Dept Store 1F entrance (events_veilstone_city.json).
VEILSTONE_DEPT_STORE_ENTRANCE: tuple[int, int] = (701, 603)

# ── Inter-floor stair warps ──
# Vertical floor order, B1F at the bottom, used to compute up vs. down. 4F/5F
# are non-shop floors but may be transited by the chain (no current cashier
# lives there, so in practice we never enter them, but the table keeps the
# graph complete).
DEPT_STORE_FLOOR_SEQUENCE: list[str] = [
    "C07R0207",  # B1F
    "C07R0201",  # 1F
    "C07R0202",  # 2F
    "C07R0203",  # 3F
    "C07R0204",  # 4F
    "C07R0205",  # 5F
]

# (current_floor_code, "up"|"down") → (x, y) of the stairs warp tile to step
# onto. Stairs on 1F-5F sit at (12, 8) going up and (7, 8) going down. The
# B1F↔1F connection is off-axis: the 1F south-stair tile is (7, 8) and on
# B1F you ascend from (11, 8). Sourced from events_veilstone_store_*.json
# (warp_events with dest_header_id pointing at adjacent floors).
DEPT_STORE_STAIR_TILES: dict[tuple[str, str], tuple[int, int]] = {
    ("C07R0207", "up"):   (11, 8),  # B1F → 1F
    ("C07R0201", "down"): (7, 8),   # 1F  → B1F
    ("C07R0201", "up"):   (12, 8),  # 1F  → 2F
    ("C07R0202", "down"): (7, 8),   # 2F  → 1F
    ("C07R0202", "up"):   (12, 8),  # 2F  → 3F
    ("C07R0203", "down"): (7, 8),   # 3F  → 2F
    ("C07R0203", "up"):   (12, 8),  # 3F  → 4F
    ("C07R0204", "down"): (7, 8),   # 4F  → 3F
    ("C07R0204", "up"):   (12, 8),  # 4F  → 5F
    ("C07R0205", "down"): (7, 8),   # 5F  → 4F
}


def _is_dept_store_map(code: str) -> bool:
    """True if `code` is a Veilstone Dept Store interior map."""
    return code.startswith("C07R02")


def _city_code_from_map(map_id: int) -> str | None:
    """Extract the city/town code (e.g. 'C01', 'T03') from a map ID."""
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")
    m = re.match(r"^([CT]\d{2})", code)
    return m.group(1) if m else None


def _city_name(city_code: str) -> str:
    """Resolve a city code to its display name by finding the overworld map entry."""
    for entry in map_table().values():
        if entry.get("code") == city_code:
            name = entry.get("name", "")
            if name and not name.startswith("["):
                return name
    return city_code


def _find_mart_warp(
    emu: "EmulatorClient", map_id: int, city_code: str,
) -> dict | None:
    """Find a warp on the current map that leads to this city's PokéMart.

    For Veilstone (C07) there is no Friendly Shop — instead, accept the
    warp to the Department Store 1F (code C07R0201) as the mart entrance.
    """
    from renegade_mcp.map_state import read_warps_from_rom

    warps = read_warps_from_rom(emu, map_id)
    table = map_table()
    for w in warps:
        dest_entry = table.get(w["dest_map"], {})
        dest_code = dest_entry.get("code", "")
        if dest_code.startswith(f"{city_code}FS"):
            return w
        if city_code == "C07" and dest_code == "C07R0201":
            return w
    return None


def _find_dept_store_cashier_for_item(
    map_code: str, item_name: str,
) -> tuple[dict, int, int] | None:
    """Locate a dept-store cashier on this floor that sells `item_name`.

    Returns (cashier_spec, menu_index, item_id) or None.
    """
    target = item_name.lower()
    names = item_names()
    for cashier in DEPT_STORE_CASHIERS.get(map_code, []):
        for idx, item_id in enumerate(cashier["items"]):
            if names.get(item_id, "").lower() == target:
                return (cashier, idx, item_id)
    return None


def _find_dept_store_cashier_anywhere(
    item_name: str,
) -> tuple[str, dict, int, int] | None:
    """Locate any dept-store cashier on any floor that sells `item_name`.

    Returns (floor_code, cashier_spec, menu_index, item_id) or None.
    """
    target = item_name.lower()
    names = item_names()
    for code, cashiers in DEPT_STORE_CASHIERS.items():
        for cashier in cashiers:
            for idx, item_id in enumerate(cashier["items"]):
                if names.get(item_id, "").lower() == target:
                    return (code, cashier, idx, item_id)
    return None


def _navigate_dept_store_floor(
    emu: EmulatorClient, target_code: str,
) -> dict | None:
    """Walk from the current dept-store floor to `target_code` via stairs.

    Reads the current floor, picks the up- or down-stair tile from
    DEPT_STORE_STAIR_TILES, drives navigate_to onto it, and re-reads the map.
    Loops until on the target floor or until the chain stalls.

    Returns None on success, or an error result dict on failure.
    """
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.navigation import navigate_to
    from renegade_mcp.phase_timer import phase

    if target_code not in DEPT_STORE_FLOOR_SEQUENCE:
        return _error(f"Floor {target_code} is not stair-routable.")

    target_idx = DEPT_STORE_FLOOR_SEQUENCE.index(target_code)

    # 6 floors top-to-bottom, so 5 stair hops is the worst case. Cap at 8.
    for _ in range(8):
        map_id, _, _, _ = read_player_state(emu)
        code = map_table().get(map_id, {}).get("code", "")
        if code == target_code:
            return None
        if code not in DEPT_STORE_FLOOR_SEQUENCE:
            return _error(
                f"Off the dept-store floor sequence (current code: {code})."
            )
        cur_idx = DEPT_STORE_FLOOR_SEQUENCE.index(code)
        direction = "up" if target_idx > cur_idx else "down"
        tile = DEPT_STORE_STAIR_TILES.get((code, direction))
        if tile is None:
            return _error(
                f"No stair tile registered for "
                f"{DEPT_STORE_FLOOR_NAMES.get(code, code)} going {direction}."
            )

        with phase("shop_dept_store_stairs"):
            nav_result = navigate_to(emu, tile[0], tile[1], flee_encounters=True)

        if nav_result.get("encounter"):
            err = _error("Dept Store stair navigation interrupted by encounter.")
            err["encounter"] = nav_result["encounter"]
            return err
        if nav_result.get("stopped_early") and not nav_result.get("door_entered"):
            return _error(
                f"Could not reach stairs at ({tile[0]}, {tile[1]}) on "
                f"{DEPT_STORE_FLOOR_NAMES.get(code, code)} — path blocked."
            )

        new_map_id, _, _, _ = read_player_state(emu)
        new_code = map_table().get(new_map_id, {}).get("code", "")
        if new_code == code:
            return _error(
                f"Stair warp at ({tile[0]}, {tile[1]}) on "
                f"{DEPT_STORE_FLOOR_NAMES.get(code, code)} did not trigger "
                f"(still on same floor)."
            )

    return _error("Dept Store stair chain exceeded safety cap (8 hops).")


def _find_npc_at(state: dict, npc_name: str, x: int, y: int) -> dict | None:
    """Find an active map object matching `npc_name` at exact tile (x, y).

    Used to disambiguate same-named NPCs (e.g. dept-store 2F has two
    "Cashier F" objects at different tiles).
    """
    for obj in state["objects"]:
        if obj.get("name") == npc_name and obj.get("x") == x and obj.get("y") == y:
            return obj
    return None


def _format_item(name: str, price: int, tag: str = "") -> str:
    """Format one item line: name, price, optional tag."""
    s = f"  {name:<16s} ¥{price:,}"
    if tag:
        s += f"  ({tag})"
    return s


def read_shop(emu: EmulatorClient, badge_count: int | None = None) -> dict[str, Any]:
    """Read the PokéMart inventory for the player's current location.

    Args:
        emu: Emulator client (used to read current map).
        badge_count: Player's badge count. If None, defaults to 0.

    Returns dict with common_items, specialty_items, formatted text, etc.
    For Veilstone Dept Store interiors the return shape is different:
    {location, floor, cashiers: [{npc, x, y, label, items}], formatted}.
    """
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.trainer import read_trainer_status

    map_id, x, y, _facing = read_player_state(emu)
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")

    if _is_dept_store_map(code):
        return _read_dept_store(map_id, code)

    city_code = _city_code_from_map(map_id)

    if city_code is None:
        loc_name = entry.get("name", f"Map {map_id}")
        return {
            "error": f"Not in a city or town with a standard PokéMart.",
            "location": loc_name,
            "map_id": map_id,
        }

    # Veilstone overworld: no Friendly Shop — direct the caller at the
    # Dept Store instead so they don't get a confusing badge-gated stock
    # listing for a mart that doesn't exist.
    if code == "C07":
        return _veilstone_overworld_summary(map_id)

    loc_name = _city_name(city_code)

    if badge_count is not None:
        badges = badge_count
    else:
        status = read_trainer_status(emu)
        badges = status.get("badges", 0) if isinstance(status.get("badges"), int) else 0
    threshold = _badge_threshold(badges)

    names = item_names()
    prices = item_prices()

    # ── Common items ──
    common = []
    next_unlock_at: int | None = None
    for item_id, req in COMMON_MART_ITEMS:
        available = threshold >= req
        item = {
            "name": names.get(item_id, f"???#{item_id}"),
            "price": prices.get(item_id, 0),
            "item_id": item_id,
            "available": available,
        }
        if not available:
            item["badges_needed"] = req
            if next_unlock_at is None or req < next_unlock_at:
                next_unlock_at = req
        common.append(item)

    # ── Specialty items ──
    specialty = []
    if city_code in SPECIALTY_MARTS:
        for item_id in SPECIALTY_MARTS[city_code]:
            specialty.append({
                "name": names.get(item_id, f"???#{item_id}"),
                "price": prices.get(item_id, 0),
                "item_id": item_id,
            })

    # ── Formatted output ──
    lines = [f"PokéMart — {loc_name}"]
    if badge_count is not None:
        lines.append(f"Badges: {badges}/8 (threshold {threshold})")
    else:
        lines.append(f"Badges: unknown (showing 0-badge stock, threshold {threshold})")
    lines.append("")

    avail = [i for i in common if i["available"]]
    locked = [i for i in common if not i["available"]]

    if avail:
        lines.append("Common stock:")
        for item in avail:
            lines.append(_format_item(item["name"], item["price"]))

    if specialty:
        lines.append("")
        lines.append(f"Specialty ({loc_name}):")
        for item in specialty:
            lines.append(_format_item(item["name"], item["price"]))

    if locked:
        lines.append("")
        lines.append(f"Locked (next unlock at threshold {next_unlock_at}):")
        for item in locked:
            lines.append(_format_item(
                item["name"], item["price"],
                tag=f"threshold {item['badges_needed']}",
            ))

    has_specialty = city_code in SPECIALTY_MARTS
    if not has_specialty:
        lines.append("")
        lines.append(f"(No specialty items for {loc_name})")

    if city_code == "C07":
        lines.append("")
        lines.append("Note: Veilstone has a Dept Store, not a standard mart.")

    return {
        "location": loc_name,
        "city_code": city_code,
        "map_id": map_id,
        "badges": badges,
        "badges_confirmed": badge_count is not None,
        "threshold": threshold,
        "common_items": common,
        "specialty_items": specialty,
        "formatted": "\n".join(lines),
    }


def _resolve_cashier_items(cashier: dict) -> list[dict]:
    """Materialize a cashier's item list into name/price/item_id dicts."""
    names = item_names()
    prices = item_prices()
    return [
        {
            "name": names.get(item_id, f"???#{item_id}"),
            "price": prices.get(item_id, 0),
            "item_id": item_id,
        }
        for item_id in cashier["items"]
    ]


def _read_dept_store(map_id: int, code: str) -> dict[str, Any]:
    """read_shop branch for Veilstone Dept Store interior maps."""
    floor_meta = DEPT_STORE_FLOORS.get(code, {"name": "?"})
    floor = floor_meta["name"]
    cashiers_raw = DEPT_STORE_CASHIERS.get(code, [])

    cashiers_out = [
        {
            "npc": c["npc"], "x": c["x"], "y": c["y"], "label": c["label"],
            "items": _resolve_cashier_items(c),
        }
        for c in cashiers_raw
    ]

    lines = [f"Veilstone Dept Store — {floor}"]
    if not cashiers_out:
        lines.append("")
        lines.append(floor_meta.get(
            "message", "(No purchasable shops indexed for this floor.)",
        ))
    for c in cashiers_out:
        lines.append("")
        lines.append(f"{c['label']} — {c['npc']} @ ({c['x']},{c['y']}):")
        for it in c["items"]:
            lines.append(_format_item(it["name"], it["price"]))

    return {
        "location": "Veilstone Dept Store",
        "floor": floor,
        "city_code": "C07",
        "map_code": code,
        "map_id": map_id,
        "cashiers": cashiers_out,
        "formatted": "\n".join(lines),
    }


def _veilstone_overworld_summary(map_id: int) -> dict[str, Any]:
    """read_shop branch for the Veilstone City overworld (no Friendly Shop)."""
    cashiers_out = []
    for floor_code in ("C07R0201", "C07R0202", "C07R0203", "C07R0207"):
        floor = DEPT_STORE_FLOOR_NAMES.get(floor_code, "?")
        for c in DEPT_STORE_CASHIERS.get(floor_code, []):
            cashiers_out.append({
                "floor": floor, "map_code": floor_code,
                "npc": c["npc"], "x": c["x"], "y": c["y"], "label": c["label"],
                "items": _resolve_cashier_items(c),
            })

    entrance_x, entrance_y = VEILSTONE_DEPT_STORE_ENTRANCE
    lines = [
        "Veilstone City — no standard PokéMart.",
        f"Enter the Department Store (warp at city tile {entrance_x}, {entrance_y}) for shops.",
        "",
        "Floor directory:",
    ]
    by_floor: dict[str, list[dict]] = {}
    for c in cashiers_out:
        by_floor.setdefault(c["floor"], []).append(c)
    for floor in ("1F", "2F", "3F", "B1F"):
        for c in by_floor.get(floor, []):
            lines.append(f"  {floor}  {c['label']:<28s} ({c['npc']} @ {c['x']},{c['y']})")
    lines.append("  4F  Decorations / dolls         (not yet supported)")
    lines.append("  5F  (no shop)")

    return {
        "location": "Veilstone City",
        "city_code": "C07",
        "map_id": map_id,
        "dept_store": True,
        "cashiers": cashiers_out,
        "formatted": "\n".join(lines),
    }


# ── Buy Item ──

# Timing constants (frames)
_TEXT_WAIT = 120      # dialogue line render
_MENU_WAIT = 300      # shop menu transition (camera pan + list load)
_SETTLE_WAIT = 120    # post-dialogue settle


def _press(emu: EmulatorClient, buttons: list[str], wait: int = _TEXT_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _available_common_items(threshold: int) -> list[int]:
    """Return item IDs for common mart items available at the given badge threshold."""
    return [item_id for item_id, req in COMMON_MART_ITEMS if threshold >= req]


def _find_item_position(
    item_name: str,
    threshold: int,
    city_code: str,
) -> tuple[str, int, int] | None:
    """Find which cashier sells an item and its menu position.

    Returns (cashier_type, menu_index, item_id) or None if not found.
    cashier_type is "common" or "specialty".
    menu_index is the 0-based position in that cashier's item list.
    """
    names = item_names()
    target = item_name.lower()

    # Check common items (badge-filtered, in array order)
    available = _available_common_items(threshold)
    for idx, item_id in enumerate(available):
        if names.get(item_id, "").lower() == target:
            return ("common", idx, item_id)

    # Check specialty items
    specialty_ids = SPECIALTY_MARTS.get(city_code, [])
    for idx, item_id in enumerate(specialty_ids):
        if names.get(item_id, "").lower() == target:
            return ("specialty", idx, item_id)

    return None


def _is_inside_shop_map(code: str) -> bool:
    """True if `code` is a regular mart or a Veilstone Dept Store interior."""
    return "FS" in code or _is_dept_store_map(code)


def _enter_shop_or_error(
    emu: EmulatorClient,
) -> tuple[str | None, dict | None, bool]:
    """Ensure the player is inside a shop map, auto-warping from city overworld.

    Returns (code, error, navigated_to_mart). On success `error` is None
    and `code` is the current map's code (a mart "FS" code or a Veilstone
    Dept Store interior). On failure `error` is a result dict ready to return.
    """
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.navigation import navigate_to
    from renegade_mcp.phase_timer import phase

    map_id, _x, _y, _facing = read_player_state(emu)
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")

    if _is_inside_shop_map(code):
        return code, None, False

    city_code = _city_code_from_map(map_id)
    if city_code is None or code != city_code:
        loc = _city_name(city_code) if city_code else entry.get("name", f"Map {map_id}")
        return None, _error(
            f"Not inside a PokéMart or city overworld ({loc}, code: {code}). "
            "Navigate to a town with a PokéMart first."
        ), False

    mart_warp = _find_mart_warp(emu, map_id, city_code)
    if mart_warp is None:
        return None, _error(f"No PokéMart warp found in {_city_name(city_code)}."), False

    with phase("shop_navigate_to_mart"):
        nav_result = navigate_to(
            emu, mart_warp["x"], mart_warp["y"], flee_encounters=True,
        )

    if nav_result.get("encounter"):
        err = _error("Navigation to PokéMart interrupted by encounter.")
        err["encounter"] = nav_result["encounter"]
        err["formatted"] = (
            "Error: Navigation to PokéMart interrupted by encounter. "
            "Deal with the encounter and try again."
        )
        return None, err, False

    if nav_result.get("stopped_early") and not nav_result.get("door_entered"):
        return None, _error(
            "Could not reach the PokéMart — path was blocked. "
            f"Path: {nav_result.get('path', 'unknown')}"
        ), False

    new_map_id, _, _, _ = read_player_state(emu)
    new_code = map_table().get(new_map_id, {}).get("code", "")
    if not _is_inside_shop_map(new_code):
        return None, _error(
            f"Navigated to mart warp but didn't enter (current code: {new_code})."
        ), False
    return new_code, None, True


def _has_premier_bonus(item_name: str, quantity: int) -> bool:
    """10+ Poké Balls of any kind triggers a Premier Ball gift dialogue."""
    return item_name.lower().endswith("ball") and quantity >= 10


def _validate_cart_input(cart: dict) -> dict | None:
    """Cart-shape validation: dict[str, int>=1], non-empty. Returns error or None."""
    if not isinstance(cart, dict):
        return _error("cart must be a dict of {item_name: quantity}.")
    if not cart:
        return _error("cart is empty.")
    for name, qty in cart.items():
        if not isinstance(name, str):
            return _error(f"cart key {name!r} is not a string.")
        if not isinstance(qty, int) or qty < 1:
            return _error(f"cart quantity for {name!r} must be a positive int (got {qty!r}).")
    return None


def _partition_cart_for_regular_mart(
    cart: dict[str, int], threshold: int, city_code: str,
) -> tuple[dict[str, list[dict]] | None, int, dict | None]:
    """Group a cart by cashier (common vs specialty) for a standard mart.

    Returns (groups, total_cost, error). On success error is None and groups
    is {"common": [purchase_dict, ...], "specialty": [...]} (each missing if
    no items in that group). On failure groups is None and error is a result
    dict listing items not stocked at this mart.

    Each purchase_dict: {name, item_id, menu_index, quantity, unit_price,
    line_total, premier_bonus}.
    """
    names = item_names()
    prices = item_prices()
    groups: dict[str, list[dict]] = {}
    total = 0
    missing: list[str] = []

    for name, qty in cart.items():
        found = _find_item_position(name, threshold, city_code)
        if found is None:
            missing.append(name)
            continue
        cashier_type, menu_index, item_id = found
        unit_price = prices.get(item_id, 0)
        line_total = unit_price * qty
        total += line_total
        display = names.get(item_id, name)
        groups.setdefault(cashier_type, []).append({
            "name": display,
            "item_id": item_id,
            "menu_index": menu_index,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "premier_bonus": _has_premier_bonus(display, qty),
        })

    if missing:
        avail_common = [
            names.get(i, "?") for i in _available_common_items(threshold)
        ]
        avail_spec = [
            names.get(i, "?") for i in SPECIALTY_MARTS.get(city_code, [])
        ]
        return None, 0, _error(
            f"Not sold at {_city_name(city_code)} mart: {', '.join(missing)}. "
            f"Common: {', '.join(avail_common)}. "
            f"Specialty: {', '.join(avail_spec) if avail_spec else '(none)'}."
        )

    # Sort each group by menu_index so we scroll forward only.
    for items in groups.values():
        items.sort(key=lambda p: p["menu_index"])

    return groups, total, None


def _partition_cart_for_dept_store(
    cart: dict[str, int],
) -> tuple[list[dict] | None, int, dict | None]:
    """Group a cart by (floor, counter) for the Veilstone Dept Store.

    Returns (groups, total_cost, error). On success error is None and groups
    is a list of {floor_code, cashier_spec, purchases: [purchase_dict, ...]}
    entries. Caller orders these groups by floor proximity to minimize stair
    hops.

    Each purchase_dict: {name, item_id, menu_index, quantity, unit_price,
    line_total, premier_bonus}.
    """
    names = item_names()
    prices = item_prices()
    by_counter: dict[tuple[str, str, int, int], dict] = {}
    total = 0
    missing: list[str] = []

    for name, qty in cart.items():
        target = name.lower()
        located: tuple[str, dict, int, int] | None = None
        for code, cashiers in DEPT_STORE_CASHIERS.items():
            for cashier in cashiers:
                for idx, item_id in enumerate(cashier["items"]):
                    if names.get(item_id, "").lower() == target:
                        located = (code, cashier, idx, item_id)
                        break
                if located is not None:
                    break
            if located is not None:
                break
        if located is None:
            missing.append(name)
            continue

        floor_code, cashier_spec, menu_index, item_id = located
        unit_price = prices.get(item_id, 0)
        line_total = unit_price * qty
        total += line_total
        display = names.get(item_id, name)

        key = (floor_code, cashier_spec["npc"], cashier_spec["x"], cashier_spec["y"])
        group = by_counter.setdefault(key, {
            "floor_code": floor_code,
            "cashier_spec": cashier_spec,
            "purchases": [],
        })
        group["purchases"].append({
            "name": display,
            "item_id": item_id,
            "menu_index": menu_index,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "premier_bonus": _has_premier_bonus(display, qty),
        })

    if missing:
        per_floor = []
        for fcode in ("C07R0201", "C07R0202", "C07R0203", "C07R0207"):
            fname = DEPT_STORE_FLOOR_NAMES.get(fcode, fcode)
            items_there = [
                names.get(i, "?")
                for c in DEPT_STORE_CASHIERS.get(fcode, [])
                for i in c["items"]
            ]
            if items_there:
                per_floor.append(f"{fname}: {', '.join(items_there)}")
        msg = f"Not sold in the Dept Store: {', '.join(missing)}."
        if per_floor:
            msg += " Stocked: " + " | ".join(per_floor) + "."
        return None, 0, _error(msg)

    for group in by_counter.values():
        group["purchases"].sort(key=lambda p: p["menu_index"])

    return list(by_counter.values()), total, None


def _press_buy_one_item(
    emu: EmulatorClient, menu_index: int, quantity: int, premier_bonus: bool,
) -> None:
    """Buy one item from a cashier already on BUY/SELL/SEE YA cursor=BUY.

    Ends with the cursor back on BUY ready for another _press_buy_one_item
    or a _press_see_ya_exit.
    """
    from renegade_mcp.phase_timer import phase

    with phase("shop_purchase_flow_item"):
        _press(emu, ["a"], _MENU_WAIT)  # BUY → item list

        for _ in range(menu_index):
            _press(emu, ["down"], wait=30)

        # Item-confirm renders "Item? Certainly. How many?" *and* the qty
        # selector x01 in one screen — so a single A here, not two. Pressing
        # A twice would land on the qty selector (cursor on x01) and confirm
        # qty=1, eating the up-press increments below.
        _press(emu, ["a"], _MENU_WAIT)

        for _ in range(quantity - 1):
            _press(emu, ["up"], wait=15)

        # qty-confirm produces "And you want N. ¥X. OK?" with YES/NO inline,
        # then YES advances to "Here you are!". Two A presses, not three.
        _press(emu, ["a"], _MENU_WAIT)
        _press(emu, ["a"], _MENU_WAIT)

        # Post-YES: B advances "Here you are!" → "You put away..." →
        # item list → BUY/SELL/SEE YA menu (cursor on BUY). Premier Ball
        # bonus (10+ Poké Balls) inserts two extra pages before the item list.
        n_b_presses = 5 if premier_bonus else 3
        for _ in range(n_b_presses):
            _press(emu, ["b"], wait=_MENU_WAIT)


def _press_see_ya_exit(emu: EmulatorClient) -> None:
    """From BUY/SELL/SEE YA cursor=BUY, exit through SEE YA back to overworld."""
    _press(emu, ["down"], wait=30)
    _press(emu, ["down"], wait=30)
    _press(emu, ["a"], wait=_TEXT_WAIT)
    _press(emu, ["a"], wait=_SETTLE_WAIT)


def _exit_shop(emu: EmulatorClient) -> dict | None:
    """Walk the player out the shop's door warp back to the city overworld.

    From any Veilstone Dept Store floor, first chains down to 1F (the
    entrance), then takes the warp tile to the overworld. From a regular
    mart, takes the single overworld-bound warp directly.

    Returns None on success, or an error result dict if exit fails.
    """
    from renegade_mcp.map_poi import read_warps_from_rom
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.navigation import navigate_to
    from renegade_mcp.phase_timer import phase

    map_id, _, _, _ = read_player_state(emu)
    code = map_table().get(map_id, {}).get("code", "")

    # Dept-store: descend to 1F first.
    if _is_dept_store_map(code) and code != "C07R0201":
        nav_err = _navigate_dept_store_floor(emu, "C07R0201")
        if nav_err is not None:
            return nav_err
        map_id, _, _, _ = read_player_state(emu)
        code = map_table().get(map_id, {}).get("code", "")

    if not _is_inside_shop_map(code):
        # Already outside (e.g. caller handed us a non-shop map). No-op.
        return None

    # Pick the warp whose destination is the overworld (city code without
    # mart/dept-store suffix).
    if _is_dept_store_map(code):
        target_city_code = "C07"
    else:
        m = re.match(r"^([CT]\d{2})", code)
        target_city_code = m.group(1) if m else None

    if target_city_code is None:
        return _error(f"Could not derive city code from shop map {code}.")

    table = map_table()
    exit_tile: tuple[int, int] | None = None
    for w in read_warps_from_rom(emu, map_id):
        dest_code = table.get(w["dest_map"], {}).get("code", "")
        if dest_code == target_city_code:
            exit_tile = (w["x"], w["y"])
            break

    if exit_tile is None:
        return _error(
            f"No exit warp on {code} leads to {target_city_code} overworld."
        )

    with phase("shop_exit_warp"):
        nav_result = navigate_to(
            emu, exit_tile[0], exit_tile[1], flee_encounters=True,
        )

    if nav_result.get("encounter"):
        err = _error("Shop exit interrupted by encounter.")
        err["encounter"] = nav_result["encounter"]
        return err
    if nav_result.get("stopped_early") and not nav_result.get("door_entered"):
        return _error(
            f"Could not reach exit warp at {exit_tile} on {code}."
        )

    new_map_id, post_x, post_y, post_facing = read_player_state(emu)
    new_code = table.get(new_map_id, {}).get("code", "")
    if _is_inside_shop_map(new_code):
        return _error(
            f"Stepped on exit warp but still inside a shop map ({new_code})."
        )

    # The dest warp on the city map places the player exactly on its tile.
    # Step one tile in the player's facing direction (the engine sets facing
    # away from the door after a warp) so future buy_item / sell_item calls
    # from the same overworld position can BFS-step ONTO the warp tile from
    # outside, which is what triggers the door re-entry. Without this, the
    # next entry attempt sees "already at target" and the door never fires.
    facing_button = {0: "up", 1: "down", 2: "left", 3: "right"}.get(post_facing)
    if facing_button is not None:
        emu.press_buttons([facing_button], frames=8)
        emu.advance_frames(30)
        # If facing direction is blocked (rare — e.g. exit faces a wall),
        # try the remaining cardinals so we leave the warp tile no matter what.
        _, after_x, after_y, _ = read_player_state(emu)
        if (after_x, after_y) == (post_x, post_y):
            for fallback in ("down", "up", "left", "right"):
                if fallback == facing_button:
                    continue
                emu.press_buttons([fallback], frames=8)
                emu.advance_frames(30)
                _, after_x, after_y, _ = read_player_state(emu)
                if (after_x, after_y) != (post_x, post_y):
                    break
    return None


def buy_item(
    emu: EmulatorClient,
    cart: dict[str, int],
    badge_count: int | None = None,
) -> dict[str, Any]:
    """Buy a cart of items from a PokéMart or the Veilstone Department Store.

    `cart` is a {item_name: quantity} dict (case-insensitive keys, qty ≥ 1).
    The tool auto-routes through the shop, visits every counter the cart
    spans, and walks the player back out the entrance warp at the end.

    Atomic: if any item isn't stocked or the cart exceeds the player's money,
    no purchases happen. Errors before stepping into the shop.

    Standard mart: visits Cashier F (common items) and/or Cashier M
    (specialty) as the cart requires, then exits through the front-door warp.

    Veilstone Dept Store: visits each floor in the cart in B1F→1F→2F→3F order
    (chaining stairs), one or two counters per floor, then chains back to 1F
    and exits via the entrance warp at (10, 12). The elevator is never used.

    Args:
        emu: Emulator client.
        cart: {item_name: quantity}. Names case-insensitive. Quantities ≥ 1.
            Example: {"Potion": 5, "Repel": 3, "Fire Stone": 1}.
        badge_count: Player's badge count for filtering common-mart stock. If
            None, reads from trainer status. Ignored at the Dept Store.
    """
    err = _validate_cart_input(cart)
    if err is not None:
        return err

    code, err, navigated_to_mart = _enter_shop_or_error(emu)
    if err is not None:
        return err

    if _is_dept_store_map(code):
        return _buy_cart_at_dept_store(emu, code, cart, navigated_to_mart)
    return _buy_cart_at_regular_mart(
        emu, code, cart, badge_count, navigated_to_mart,
    )


def _buy_cart_at_regular_mart(
    emu: EmulatorClient,
    code: str,
    cart: dict[str, int],
    badge_count: int | None,
    navigated_to_mart: bool,
) -> dict[str, Any]:
    """buy_item cart-loop branch for standard PokéMart maps."""
    from renegade_mcp.map_state import read_player_state
    from renegade_mcp.move_services import _find_npc
    from renegade_mcp.navigation import interact_with
    from renegade_mcp.phase_timer import phase
    from renegade_mcp.trainer import read_trainer_status

    map_id, _, _, _ = read_player_state(emu)
    city_code = _city_code_from_map(map_id)
    if city_code is None:
        return _error(f"Cannot determine city from map code: {code}")

    if badge_count is not None:
        badges = badge_count
    else:
        status = read_trainer_status(emu)
        badges_val = status.get("badges", 0)
        badges = badges_val if isinstance(badges_val, int) else 0
    threshold = _badge_threshold(badges)

    groups, total_cost, err = _partition_cart_for_regular_mart(
        cart, threshold, city_code,
    )
    if err is not None:
        return err

    status = read_trainer_status(emu)
    money_before = status.get("money", 0)
    if total_cost > money_before:
        return _error(
            f"Not enough money. Cart costs ¥{total_cost:,}, "
            f"you have ¥{money_before:,}."
        )

    purchases_log: list[dict] = []
    # Common counter first (always present), then specialty if needed.
    for cashier_type in ("common", "specialty"):
        items_at_cashier = groups.get(cashier_type)
        if not items_at_cashier:
            continue
        cashier_name = "Cashier F" if cashier_type == "common" else "Cashier M"
        cashier, npc_err = _find_npc(emu, cashier_name, cashier_name)
        if npc_err is not None:
            return npc_err

        with phase("shop_interact_cashier"):
            nav_result = interact_with(emu, cashier["index"])
        if nav_result.get("interrupted") or nav_result.get("encounter"):
            return _error(
                f"Navigation to {cashier_name} interrupted: {nav_result}"
            )
        if nav_result.get("stopped_early"):
            return _error(f"Could not reach {cashier_name} — path blocked.")

        for purchase in items_at_cashier:
            _press_buy_one_item(
                emu,
                purchase["menu_index"],
                purchase["quantity"],
                purchase["premier_bonus"],
            )
            purchases_log.append(_purchase_log_entry(purchase, counter=cashier_type))
        _press_see_ya_exit(emu)

    new_status = read_trainer_status(emu)
    money_after = new_status.get("money", 0)
    spent = money_before - money_after

    if spent != total_cost:
        return _error(
            f"Purchase verification failed: expected to spend ¥{total_cost:,} "
            f"but actually spent ¥{spent:,} "
            f"(money {money_before:,} → {money_after:,})."
        )

    exit_err = _exit_shop(emu)
    if exit_err is not None:
        return exit_err

    result: dict[str, Any] = {
        "success": True,
        "purchases": purchases_log,
        "total_cost": total_cost,
        "money_before": money_before,
        "money_after": money_after,
        "money_spent": spent,
        "exited": True,
        "formatted": _format_cart_buy(
            purchases_log, total_cost, money_before, money_after,
            f"{_city_name(city_code)} mart",
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result


def _buy_cart_at_dept_store(
    emu: EmulatorClient,
    code: str,
    cart: dict[str, int],
    navigated_to_mart: bool,
) -> dict[str, Any]:
    """buy_item cart-loop branch for the Veilstone Dept Store."""
    from renegade_mcp.map_state import get_map_state, read_player_state
    from renegade_mcp.navigation import interact_with
    from renegade_mcp.phase_timer import phase
    from renegade_mcp.trainer import read_trainer_status

    groups, total_cost, err = _partition_cart_for_dept_store(cart)
    if err is not None:
        return err

    status = read_trainer_status(emu)
    money_before = status.get("money", 0)
    if total_cost > money_before:
        return _error(
            f"Not enough money. Cart costs ¥{total_cost:,}, "
            f"you have ¥{money_before:,}."
        )

    # Visit floors in vertical order (B1F → 1F → 2F → 3F). Within a floor,
    # counters appear in DEPT_STORE_CASHIERS table order (top, then bottom).
    groups.sort(key=lambda g: (
        DEPT_STORE_FLOOR_SEQUENCE.index(g["floor_code"]),
        g["cashier_spec"]["y"],
    ))

    floors_traversed: list[str] = []
    purchases_log: list[dict] = []

    for group in groups:
        target_code = group["floor_code"]
        map_id, _, _, _ = read_player_state(emu)
        current_code = map_table().get(map_id, {}).get("code", "")
        if current_code != target_code:
            nav_err = _navigate_dept_store_floor(emu, target_code)
            if nav_err is not None:
                return nav_err

        floor_label = DEPT_STORE_FLOOR_NAMES.get(target_code, target_code)
        if not floors_traversed or floors_traversed[-1] != floor_label:
            floors_traversed.append(floor_label)

        cashier_spec = group["cashier_spec"]
        state = get_map_state(emu)
        if state is None:
            return _error("Could not read map state.")
        cashier_obj = _find_npc_at(
            state, cashier_spec["npc"], cashier_spec["x"], cashier_spec["y"],
        )
        if cashier_obj is None:
            return _error(
                f"No {cashier_spec['npc']} at "
                f"({cashier_spec['x']}, {cashier_spec['y']}) on {floor_label}."
            )

        with phase("shop_interact_cashier"):
            nav_result = interact_with(emu, cashier_obj["index"])
        if nav_result.get("interrupted") or nav_result.get("encounter"):
            return _error(
                f"Navigation to {cashier_spec['npc']} interrupted: {nav_result}"
            )
        if nav_result.get("stopped_early"):
            return _error(
                f"Could not reach {cashier_spec['npc']} — path blocked."
            )

        for purchase in group["purchases"]:
            _press_buy_one_item(
                emu,
                purchase["menu_index"],
                purchase["quantity"],
                purchase["premier_bonus"],
            )
            purchases_log.append(_purchase_log_entry(
                purchase, floor=floor_label, counter=cashier_spec["label"],
            ))
        _press_see_ya_exit(emu)

    new_status = read_trainer_status(emu)
    money_after = new_status.get("money", 0)
    spent = money_before - money_after

    if spent != total_cost:
        return _error(
            f"Purchase verification failed: expected to spend ¥{total_cost:,} "
            f"but actually spent ¥{spent:,} "
            f"(money {money_before:,} → {money_after:,})."
        )

    exit_err = _exit_shop(emu)
    if exit_err is not None:
        return exit_err

    result: dict[str, Any] = {
        "success": True,
        "purchases": purchases_log,
        "total_cost": total_cost,
        "money_before": money_before,
        "money_after": money_after,
        "money_spent": spent,
        "floors_traversed": floors_traversed,
        "exited": True,
        "formatted": _format_cart_buy(
            purchases_log, total_cost, money_before, money_after,
            "Veilstone Dept Store",
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result


def _purchase_log_entry(
    purchase: dict, floor: str | None = None, counter: str | None = None,
) -> dict:
    """Strip routing-only fields from a partition purchase dict for the result."""
    entry = {
        "name": purchase["name"],
        "item_id": purchase["item_id"],
        "quantity": purchase["quantity"],
        "unit_price": purchase["unit_price"],
        "line_total": purchase["line_total"],
    }
    if floor is not None:
        entry["floor"] = floor
    if counter is not None:
        entry["counter"] = counter
    return entry


def _format_cart_buy(
    purchases: list[dict], total_cost: int,
    money_before: int, money_after: int, location: str,
) -> str:
    """Multi-line summary of a cart purchase."""
    s = "s" if len(purchases) != 1 else ""
    lines = [
        f"Bought {len(purchases)} item{s} for ¥{total_cost:,} at {location}:",
    ]
    for p in purchases:
        line = f"  {p['name']} x{p['quantity']} (¥{p['line_total']:,})"
        if "floor" in p:
            line += f" [{p['floor']} — {p['counter']}]"
        elif "counter" in p:
            line += f" [{p['counter']}]"
        lines.append(line)
    lines.append(f"Money: ¥{money_before:,} → ¥{money_after:,}")
    return "\n".join(lines)


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


# ── Sell Item ──

# Pockets that cannot be sold (game rejects them)
_UNSELLABLE_POCKETS = {"Key Items", "TMs & HMs", "Mail"}

# Pocket touch-tab coords (bottom screen) — same layout as regular bag.
# Only sellable pockets listed.
_SELL_POCKET_COORDS: dict[str, tuple[int, int]] = {
    "Items":        (27, 51),
    "Medicine":     (35, 102),
    "Poke Balls":   (59, 142),
    "Berries":      (156, 165),
    "Battle Items": (220, 102),
}


def _validate_sell_cart(
    cart: dict[str, int], bag: list[dict],
) -> tuple[list[dict] | None, int, dict | None]:
    """Resolve a sell cart against the current bag.

    Returns (sales, total_value, error). On success error is None and sales
    is a list of {name, item_id, pocket, found_index, quantity, unit_sell_price,
    line_value} entries. On failure sales is None.
    """
    names = item_names()
    prices = item_prices()
    sales: list[dict] = []
    total = 0

    for cart_name, qty in cart.items():
        target = cart_name.lower()
        # Search sellable pockets.
        found_pocket = None
        found_index = None
        found_entry = None
        unsellable_hit = False
        for pocket in bag:
            for i, item in enumerate(pocket["items"]):
                if item["name"].lower() != target:
                    continue
                if pocket["name"] in _UNSELLABLE_POCKETS:
                    unsellable_hit = True
                    return None, 0, _error(
                        f"'{item['name']}' is in {pocket['name']} pocket "
                        f"and cannot be sold."
                    )
                found_pocket = pocket["name"]
                found_index = i
                found_entry = item
                break
            if found_entry is not None:
                break

        if found_entry is None and not unsellable_hit:
            sellable = []
            for pocket in bag:
                if pocket["name"] not in _UNSELLABLE_POCKETS:
                    sellable.extend(it["name"] for it in pocket["items"])
            return None, 0, _error(
                f"'{cart_name}' not found in bag. "
                f"Sellable items: {', '.join(sellable) if sellable else '(none)'}."
            )

        if qty > found_entry["qty"]:
            return None, 0, _error(
                f"Not enough {found_entry['name']}. "
                f"Have {found_entry['qty']}, want to sell {qty}."
            )

        item_id = found_entry.get("id")
        if item_id is None:
            for iid, iname in names.items():
                if iname.lower() == target:
                    item_id = iid
                    break
        buy_price = prices.get(item_id, 0) if item_id else 0
        sell_price = buy_price // 2
        if sell_price == 0:
            return None, 0, _error(
                f"'{found_entry['name']}' has no sell value (buy price: ¥0)."
            )

        line_value = sell_price * qty
        total += line_value
        sales.append({
            "name": found_entry["name"],
            "item_id": item_id,
            "pocket": found_pocket,
            "quantity": qty,
            "unit_sell_price": sell_price,
            "line_value": line_value,
        })

    return sales, total, None


def _press_sell_one_item_in_bag(
    emu: EmulatorClient, found_pocket: str, found_index: int, quantity: int,
) -> None:
    """Inside the sell bag, switch to pocket, scroll, sell N.

    Ends back at sell-bag-root with the cursor still in `found_pocket`.
    """
    from renegade_mcp.bag_cursor import get_pocket_cursor

    pocket_coords = _SELL_POCKET_COORDS[found_pocket]
    px, py = pocket_coords
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(_MENU_WAIT)

    # Reset cursor to top of pocket, then scroll to target index.
    scroll, index = get_pocket_cursor(emu, found_pocket)
    for _ in range(scroll + index):
        _press(emu, ["up"], wait=30)
    for _ in range(found_index):
        _press(emu, ["down"], wait=30)

    _press(emu, ["a"])                # "How many would you like to sell?"
    _press(emu, ["a"])                # text → quantity selector (x01)

    for _ in range(quantity - 1):
        _press(emu, ["up"], wait=15)

    _press(emu, ["a"])                # confirm qty → "I can pay ¥X." + YES/NO
    _press(emu, ["a"])                # YES → "Turned over [item] …"
    _press(emu, ["a"])                # advance scroll text
    _press(emu, ["a"], _MENU_WAIT)    # dismiss → back at sell-bag root


def sell_item(
    emu: EmulatorClient,
    cart: dict[str, int],
) -> dict[str, Any]:
    """Sell a cart of items at a PokéMart or the Veilstone Department Store.

    `cart` is a {item_name: quantity} dict (case-insensitive keys, qty ≥ 1).
    Talks to one cashier (any vendor counter accepts SELL), loops through
    each item in the bag, then walks the player back out the entrance warp.

    Atomic: validates every item exists in a sellable pocket with sufficient
    quantity before opening any UI. Items in Key Items / TMs & HMs / Mail
    pockets are rejected.

    Sell price = buy price / 2 (standard Pokémon formula).

    Args:
        emu: Emulator client.
        cart: {item_name: quantity}. Names case-insensitive. Quantities ≥ 1.
            Example: {"Potion": 3, "Antidote": 5}.
    """
    from renegade_mcp.bag import read_bag
    from renegade_mcp.map_state import get_map_state
    from renegade_mcp.navigation import interact_with
    from renegade_mcp.phase_timer import phase
    from renegade_mcp.trainer import read_trainer_status

    err = _validate_cart_input(cart)
    if err is not None:
        return err

    bag = read_bag(emu)
    sales, total_value, err = _validate_sell_cart(cart, bag)
    if err is not None:
        return err

    code, err, navigated_to_mart = _enter_shop_or_error(emu)
    if err is not None:
        return err

    status = read_trainer_status(emu)
    money_before = status.get("money", 0)

    # ── Find a cashier on the current floor and interact ──
    if _is_dept_store_map(code):
        state = get_map_state(emu)
        if state is None:
            return _error("Could not read map state.")
        floor_cashiers = DEPT_STORE_CASHIERS.get(code, [])
        if not floor_cashiers:
            return _error(
                f"Dept Store {DEPT_STORE_FLOOR_NAMES.get(code, code)} has no "
                "selling counter mapped (4F decoration / B1F lava-cookie / "
                "B1F poffin counters use custom UIs and aren't supported)."
            )
        cashier = None
        cashier_label = floor_cashiers[0]["npc"]
        for spec in floor_cashiers:
            obj = _find_npc_at(state, spec["npc"], spec["x"], spec["y"])
            if obj is not None:
                cashier = obj
                cashier_label = spec["npc"]
                break
        if cashier is None:
            return _error(
                f"No active cashier found on Dept Store "
                f"{DEPT_STORE_FLOOR_NAMES.get(code, code)}."
            )
    else:
        from renegade_mcp.move_services import _find_npc
        cashier_label = "Cashier F"
        cashier, npc_err = _find_npc(emu, cashier_label, cashier_label)
        if npc_err is not None:
            return npc_err

    with phase("shop_interact_cashier"):
        nav_result = interact_with(emu, cashier["index"])
    if nav_result.get("interrupted") or nav_result.get("encounter"):
        return _error(f"Navigation to {cashier_label} interrupted: {nav_result}")
    if nav_result.get("stopped_early"):
        return _error(f"Could not reach {cashier_label} — path blocked.")

    # ── Open sell bag (DOWN from BUY → SELL → A) ──
    _press(emu, ["down"], wait=30)
    _press(emu, ["a"], _MENU_WAIT)

    # ── Per-item sell loop ──
    # Bag layout shifts when stacks empty out; re-resolve each item's pocket
    # index against a fresh bag read between sales.
    sales_log: list[dict] = []
    for sale in sales:
        if sale["pocket"] not in _SELL_POCKET_COORDS:
            return _error(
                f"Pocket '{sale['pocket']}' has no sell tab coordinates."
            )

        # Re-find the item — earlier sales may have changed indices.
        live_bag = read_bag(emu)
        live_index: int | None = None
        for pocket in live_bag:
            if pocket["name"] != sale["pocket"]:
                continue
            for i, item in enumerate(pocket["items"]):
                if item["name"] == sale["name"]:
                    live_index = i
                    break
            break
        if live_index is None:
            return _error(
                f"Item '{sale['name']}' vanished from bag mid-cart "
                "(pre-flight validation passed but live bag lost the entry)."
            )

        _press_sell_one_item_in_bag(
            emu, sale["pocket"], live_index, sale["quantity"],
        )
        sales_log.append({
            "name": sale["name"],
            "item_id": sale["item_id"],
            "quantity": sale["quantity"],
            "unit_sell_price": sale["unit_sell_price"],
            "line_value": sale["line_value"],
            "pocket": sale["pocket"],
        })

    # ── Exit sell bag → BUY/SELL/SEE YA cursor=BUY → SEE YA → overworld ──
    _press(emu, ["b"], _MENU_WAIT)
    _press_see_ya_exit(emu)

    new_status = read_trainer_status(emu)
    money_after = new_status.get("money", 0)
    earned = money_after - money_before

    if earned != total_value:
        return _error(
            f"Sale verification failed: expected to earn ¥{total_value:,} "
            f"but actually earned ¥{earned:,} "
            f"(money {money_before:,} → {money_after:,})."
        )

    exit_err = _exit_shop(emu)
    if exit_err is not None:
        return exit_err

    result: dict[str, Any] = {
        "success": True,
        "sales": sales_log,
        "total_value": total_value,
        "money_before": money_before,
        "money_after": money_after,
        "money_earned": earned,
        "exited": True,
        "formatted": _format_cart_sell(
            sales_log, total_value, money_before, money_after,
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result


def _format_cart_sell(
    sales: list[dict], total_value: int, money_before: int, money_after: int,
) -> str:
    """Multi-line summary of a cart sell."""
    s = "s" if len(sales) != 1 else ""
    lines = [f"Sold {len(sales)} item{s} for ¥{total_value:,}:"]
    for entry in sales:
        lines.append(
            f"  {entry['name']} x{entry['quantity']} (¥{entry['line_value']:,})"
        )
    lines.append(f"Money: ¥{money_before:,} → ¥{money_after:,}")
    return "\n".join(lines)
