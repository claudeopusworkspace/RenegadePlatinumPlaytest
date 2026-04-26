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


def _run_buy_press_flow(
    emu: EmulatorClient, menu_index: int, quantity: int, premier_bonus: bool,
) -> None:
    """Drive the post-greeting buy UI: BUY → scroll → qty → confirm → exit."""
    from renegade_mcp.phase_timer import phase

    with phase("shop_purchase_flow"):
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

        _press(emu, ["down"], wait=30)
        _press(emu, ["down"], wait=30)
        _press(emu, ["a"], wait=_TEXT_WAIT)
        _press(emu, ["a"], wait=_SETTLE_WAIT)


def buy_item(
    emu: EmulatorClient,
    item_name: str,
    quantity: int = 1,
    badge_count: int | None = None,
) -> dict[str, Any]:
    """Buy an item from a PokéMart or the Veilstone Department Store.

    Works from inside a mart, inside any Veilstone Dept Store floor, or from a
    city/town overworld (auto-navigates through the entrance warp). Finds the
    correct cashier, walks there, opens the shop, scrolls to the item, selects
    quantity, confirms, and exits.

    For the Dept Store, multi-floor navigation is automatic: the chain walks
    up or down through the stair tiles ((12,8) up, (7,8) down on 1F-5F; off-axis
    on the B1F↔1F connector) until on the floor that sells the requested item.
    The elevator is never used. If the player starts from the Veilstone
    overworld, the chain runs after the entrance warp into 1F.

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Potion", "Heal Ball", "TM83"). Case-insensitive.
        quantity: How many to buy (default 1).
        badge_count: Player's badge count for filtering. If None, defaults to 0.
            Ignored for Dept Store (no badge gating there).
    """
    from renegade_mcp.trainer import read_trainer_status

    code, err, navigated_to_mart = _enter_shop_or_error(emu)
    if err is not None:
        return err

    if _is_dept_store_map(code):
        return _buy_at_dept_store(
            emu, code, item_name, quantity, navigated_to_mart,
        )

    # ── Regular PokéMart path ──
    from renegade_mcp.map_state import read_player_state
    map_id, _x, _y, _facing = read_player_state(emu)
    city_code = _city_code_from_map(map_id)
    if city_code is None:
        return _error(f"Cannot determine city from map code: {code}")

    if badge_count is not None:
        badges = badge_count
    else:
        status = read_trainer_status(emu)
        badges = status.get("badges", 0) if isinstance(status.get("badges"), int) else 0
    threshold = _badge_threshold(badges)

    result = _find_item_position(item_name, threshold, city_code)
    if result is None:
        names = item_names()
        avail_common = [names.get(i, "?") for i in _available_common_items(threshold)]
        avail_spec = [names.get(i, "?") for i in SPECIALTY_MARTS.get(city_code, [])]
        return _error(
            f"Item \"{item_name}\" not found in shop. "
            f"Common: {', '.join(avail_common)}. "
            f"Specialty: {', '.join(avail_spec) if avail_spec else '(none)'}."
        )

    cashier_type, menu_index, item_id = result
    prices = item_prices()
    price = prices.get(item_id, 0)
    total_cost = price * quantity
    display_name = item_names().get(item_id, item_name)

    status = read_trainer_status(emu)
    money = status.get("money", 0)
    if total_cost > money:
        return _error(
            f"Not enough money. {display_name} x{quantity} costs ¥{total_cost:,} "
            f"but you only have ¥{money:,}."
        )

    from renegade_mcp.move_services import _find_npc
    from renegade_mcp.navigation import interact_with
    from renegade_mcp.phase_timer import phase

    cashier_name = "Cashier F" if cashier_type == "common" else "Cashier M"
    cashier, err = _find_npc(emu, cashier_name, cashier_name)
    if err is not None:
        return err

    with phase("shop_interact_cashier"):
        nav_result = interact_with(emu, cashier["index"])
    if nav_result.get("interrupted") or nav_result.get("encounter"):
        return _error(f"Navigation to {cashier_name} interrupted: {nav_result}")
    if nav_result.get("stopped_early"):
        return _error(f"Could not reach {cashier_name} — path blocked.")

    _run_buy_press_flow(
        emu, menu_index, quantity, _has_premier_bonus(item_name, quantity),
    )

    new_status = read_trainer_status(emu)
    new_money = new_status.get("money", 0)
    spent = money - new_money

    if spent != total_cost:
        return _error(
            f"Purchase verification failed: expected to spend ¥{total_cost:,} "
            f"but actually spent ¥{spent:,} (money {money:,} → {new_money:,}). "
            f"Shop UI may be in a bad state — screenshot to diagnose."
        )

    result = {
        "success": True,
        "item": display_name,
        "item_id": item_id,
        "quantity": quantity,
        "unit_price": price,
        "total_cost": total_cost,
        "money_before": money,
        "money_after": new_money,
        "money_spent": spent,
        "cashier": cashier_type,
        "formatted": (
            f"Bought {display_name} x{quantity} for ¥{total_cost:,}. "
            f"Money: ¥{money:,} → ¥{new_money:,}"
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result


def _buy_at_dept_store(
    emu: EmulatorClient,
    code: str,
    item_name: str,
    quantity: int,
    navigated_to_mart: bool,
) -> dict[str, Any]:
    """buy_item branch for Veilstone Dept Store interior maps."""
    from renegade_mcp.map_state import get_map_state, read_player_state
    from renegade_mcp.navigation import interact_with
    from renegade_mcp.phase_timer import phase
    from renegade_mcp.trainer import read_trainer_status

    found = _find_dept_store_cashier_anywhere(item_name)

    if found is None:
        names = item_names()
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
        msg = f'"{item_name}" is not sold in the Dept Store.'
        if per_floor:
            msg += " Stocked: " + " | ".join(per_floor) + "."
        return _error(msg)

    target_code, cashier_spec, menu_index, item_id = found
    prices = item_prices()
    price = prices.get(item_id, 0)
    total_cost = price * quantity
    display_name = item_names().get(item_id, item_name)

    status = read_trainer_status(emu)
    money = status.get("money", 0)
    if total_cost > money:
        return _error(
            f"Not enough money. {display_name} x{quantity} costs ¥{total_cost:,} "
            f"but you only have ¥{money:,}."
        )

    floors_traversed: list[str] = []
    if code != target_code:
        start_floor = DEPT_STORE_FLOOR_NAMES.get(code, code)
        nav_err = _navigate_dept_store_floor(emu, target_code)
        if nav_err is not None:
            return nav_err
        # Re-read to confirm and capture the path label for the result.
        new_map_id, _, _, _ = read_player_state(emu)
        code = map_table().get(new_map_id, {}).get("code", "")
        floors_traversed = [
            start_floor, DEPT_STORE_FLOOR_NAMES.get(code, code),
        ]

    floor = DEPT_STORE_FLOOR_NAMES.get(code, "?")

    state = get_map_state(emu)
    if state is None:
        return _error("Could not read map state.")

    cashier_obj = _find_npc_at(
        state, cashier_spec["npc"], cashier_spec["x"], cashier_spec["y"],
    )
    if cashier_obj is None:
        return _error(
            f"No {cashier_spec['npc']} at "
            f"({cashier_spec['x']}, {cashier_spec['y']}) on {floor}."
        )

    with phase("shop_interact_cashier"):
        nav_result = interact_with(emu, cashier_obj["index"])

    if nav_result.get("interrupted") or nav_result.get("encounter"):
        return _error(f"Navigation to {cashier_spec['npc']} interrupted: {nav_result}")
    if nav_result.get("stopped_early"):
        return _error(f"Could not reach {cashier_spec['npc']} — path blocked.")

    _run_buy_press_flow(
        emu, menu_index, quantity, _has_premier_bonus(item_name, quantity),
    )

    new_status = read_trainer_status(emu)
    new_money = new_status.get("money", 0)
    spent = money - new_money

    if spent != total_cost:
        return _error(
            f"Purchase verification failed: expected to spend ¥{total_cost:,} "
            f"but actually spent ¥{spent:,} (money {money:,} → {new_money:,}). "
            f"Shop UI may be in a bad state — screenshot to diagnose."
        )

    result: dict[str, Any] = {
        "success": True,
        "item": display_name,
        "item_id": item_id,
        "quantity": quantity,
        "unit_price": price,
        "total_cost": total_cost,
        "money_before": money,
        "money_after": new_money,
        "money_spent": spent,
        "cashier": "dept_store",
        "floor": floor,
        "counter": cashier_spec["label"],
        "formatted": (
            f"Bought {display_name} x{quantity} for ¥{total_cost:,} "
            f"at Dept Store {floor} ({cashier_spec['label']}). "
            f"Money: ¥{money:,} → ¥{new_money:,}"
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    if floors_traversed:
        result["floors_traversed"] = floors_traversed
    return result


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


def sell_item(
    emu: EmulatorClient,
    item_name: str,
    quantity: int = 1,
) -> dict[str, Any]:
    """Sell an item at a PokéMart or the Veilstone Department Store.

    Works from inside a mart, inside any Veilstone Dept Store floor, or from
    a city/town overworld (auto-navigates through the entrance warp). Talks
    to the floor's cashier, selects SELL, navigates the sell bag to the
    item, sets quantity, confirms the sale, and exits.

    In the Dept Store any active vendor counter on the current floor accepts
    SELL — the bag UI is identical regardless of which counter you talk to.

    Sell price = buy price / 2 (standard Pokémon formula).

    Args:
        emu: Emulator client.
        item_name: Item name (e.g. "Potion", "Repel"). Case-insensitive.
        quantity: How many to sell (default 1).
    """
    from renegade_mcp.bag import read_bag
    from renegade_mcp.bag_cursor import get_pocket_cursor
    from renegade_mcp.map_state import get_map_state
    from renegade_mcp.navigation import interact_with
    from renegade_mcp.trainer import read_trainer_status

    item_lower = item_name.lower()

    # ── Find item in bag ──
    bag = read_bag(emu)
    found_pocket = None
    found_index = None
    found_entry = None
    for pocket in bag:
        if pocket["name"] in _UNSELLABLE_POCKETS:
            continue
        for i, item in enumerate(pocket["items"]):
            if item["name"].lower() == item_lower:
                found_pocket = pocket["name"]
                found_index = i
                found_entry = item
                break
        if found_entry is not None:
            break

    if found_entry is None:
        # Check if item is in an unsellable pocket
        for pocket in bag:
            if pocket["name"] in _UNSELLABLE_POCKETS:
                for item in pocket["items"]:
                    if item["name"].lower() == item_lower:
                        return _error(
                            f"'{item['name']}' is in {pocket['name']} pocket "
                            f"and cannot be sold."
                        )
        sellable = []
        for pocket in bag:
            if pocket["name"] not in _UNSELLABLE_POCKETS:
                sellable.extend(it["name"] for it in pocket["items"])
        return _error(
            f"'{item_name}' not found in bag. "
            f"Sellable items: {', '.join(sellable) if sellable else '(none)'}."
        )

    # ── Check quantity ──
    if quantity < 1:
        return _error("Quantity must be at least 1.")
    if quantity > found_entry["qty"]:
        return _error(
            f"Not enough {found_entry['name']}. "
            f"Have {found_entry['qty']}, want to sell {quantity}."
        )

    # ── Calculate sell price ──
    prices = item_prices()
    names = item_names()
    display_name = found_entry["name"]
    # Reverse-lookup item ID from name
    item_id = found_entry.get("id")
    if item_id is None:
        for iid, iname in names.items():
            if iname.lower() == item_lower:
                item_id = iid
                break
    buy_price = prices.get(item_id, 0) if item_id else 0
    sell_price = buy_price // 2
    if sell_price == 0:
        return _error(f"'{display_name}' has no sell value (buy price: ¥0).")
    total_value = sell_price * quantity

    # ── Navigate to mart (auto-warp from city overworld if needed) ──
    code, err, navigated_to_mart = _enter_shop_or_error(emu)
    if err is not None:
        return err

    # ── Record money before ──
    status = read_trainer_status(emu)
    money_before = status.get("money", 0)

    # ── Find a cashier on the current floor and interact ──
    if _is_dept_store_map(code):
        state = get_map_state(emu)
        if state is None:
            return _error("Could not read map state.")
        # Any vendor counter on this floor accepts SELL — pick the first
        # one whose tile we can match on the live object array.
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

    nav_result = interact_with(emu, cashier["index"])

    if nav_result.get("interrupted") or nav_result.get("encounter"):
        return _error(f"Navigation to {cashier_label} interrupted: {nav_result}")
    if nav_result.get("stopped_early"):
        return _error(f"Could not reach {cashier_label} — path blocked.")

    # interact_with auto-advances "Welcome! What do you need?" dialogue.
    # We're now at the BUY/SELL/SEE YA menu with cursor on BUY.

    # ── Select SELL (one down from BUY) ──
    _press(emu, ["down"], wait=30)    # BUY → SELL
    _press(emu, ["a"], _MENU_WAIT)    # open sell bag

    # ── Navigate to correct pocket via touch tab ──
    pocket_coords = _SELL_POCKET_COORDS.get(found_pocket)
    if pocket_coords is None:
        # Shouldn't happen — we filtered unsellable pockets above
        _press(emu, ["b"], _MENU_WAIT)   # exit sell bag
        _press(emu, ["down"], wait=30)    # → SEE YA
        _press(emu, ["a"])                # select SEE YA
        _press(emu, ["a"], _SETTLE_WAIT)  # dismiss farewell
        return _error(f"Pocket '{found_pocket}' has no sell tab coordinates.")

    px, py = pocket_coords
    emu.tap_touch_screen(px, py, frames=8)
    emu.advance_frames(_MENU_WAIT)

    # ── Scroll to item ──
    # Reset cursor to top first (sell bag may have its own cursor state)
    scroll, index = get_pocket_cursor(emu, found_pocket)
    for _ in range(scroll + index):
        _press(emu, ["up"], wait=30)
    for _ in range(found_index):
        _press(emu, ["down"], wait=30)

    # ── Select item ──
    _press(emu, ["a"])                # "How many would you like to sell?"
    _press(emu, ["a"])                # text finishes → quantity selector (x01)

    # ── Set quantity (up to increase from 1) ──
    for _ in range(quantity - 1):
        _press(emu, ["up"], wait=15)

    # ── Confirm sale ──
    # Confirm qty goes straight to YES/NO (no intermediate text screen).
    _press(emu, ["a"])                # confirm qty → "I can pay ¥X. Would that be OK?" + YES/NO
    _press(emu, ["a"])                # select YES → "Turned over [item] and received ¥X."

    # ── Post-sale dialogue ──
    _press(emu, ["a"])                # advance scrolling "Turned over..." text
    _press(emu, ["a"], _MENU_WAIT)    # dismiss finished text → back to sell bag

    # ── Exit sell bag + shop ──
    # After B, cursor returns to BUY (first option), not SELL.
    _press(emu, ["b"], _MENU_WAIT)    # exit sell bag → BUY/SELL/SEE YA (cursor on BUY)
    _press(emu, ["down"], wait=30)    # BUY → SELL
    _press(emu, ["down"], wait=30)    # SELL → SEE YA!
    _press(emu, ["a"])                # "Please come again!"
    _press(emu, ["a"], _SETTLE_WAIT)  # dismiss farewell, back to overworld

    # ── Verify sale ──
    new_status = read_trainer_status(emu)
    new_money = new_status.get("money", 0)
    earned = new_money - money_before

    result = {
        "success": True,
        "item": display_name,
        "item_id": item_id,
        "quantity": quantity,
        "unit_sell_price": sell_price,
        "total_value": total_value,
        "money_before": money_before,
        "money_after": new_money,
        "money_earned": earned,
        "formatted": (
            f"Sold {display_name} x{quantity} for ¥{total_value:,}. "
            f"Money: ¥{money_before:,} → ¥{new_money:,}"
        ),
    }
    if navigated_to_mart:
        result["navigated_to_mart"] = True
    return result
