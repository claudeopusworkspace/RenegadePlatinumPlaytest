"""Map ID to location name lookup."""

from __future__ import annotations

from typing import Any

from renegade_mcp.data import map_table


def lookup_map_name(map_id: int) -> dict[str, Any]:
    """Return location info for a map ID.

    Returns dict with name, code, room (if applicable).
    """
    table = map_table()
    entry = table.get(map_id)
    if entry:
        name = entry.get("name", "Unknown")
        room = entry.get("room", "")
        code = entry.get("code", "")
        display = f"{name} ({code})" if room else name
        return {"map_id": map_id, "name": name, "display": display, "code": code, "room": room}
    return {"map_id": map_id, "name": f"Map {map_id}", "display": f"Map {map_id}", "code": "", "room": ""}
