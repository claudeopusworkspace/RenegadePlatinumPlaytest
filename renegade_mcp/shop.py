"""Read PokéMart inventory for the player's current city.

Mart data is sourced from the ROM (mart_items.h in the decompilation).
Item prices come from pl_item_data.narc (extracted to data/item_prices.json).

Two inventory systems:
  1. Common items — shared across all standard PokéMarts, badge-gated.
  2. Specialty items — unique per city, always available.

Badge-gating uses the same switch logic as the game (scrcmd_shop.c):
  0 badges → threshold 1, 1-2 → 2, 3-4 → 3, 5-6 → 4, 7 → 5, 8 → 6
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import item_names, item_prices, map_table

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

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
    """
    from renegade_mcp.map_state import read_player_state

    map_id, x, y, _facing = read_player_state(emu)
    city_code = _city_code_from_map(map_id)

    if city_code is None:
        entry = map_table().get(map_id, {})
        loc_name = entry.get("name", f"Map {map_id}")
        return {
            "error": f"Not in a city or town with a standard PokéMart.",
            "location": loc_name,
            "map_id": map_id,
        }

    loc_name = _city_name(city_code)

    badges = badge_count if badge_count is not None else 0
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
