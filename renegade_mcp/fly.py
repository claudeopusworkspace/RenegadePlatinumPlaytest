"""Use Fly from the overworld to fast-travel between cities/towns.

Flow: pause menu → Pokemon → select Fly user → select Fly →
      town map opens → navigate cursor to destination → A to confirm →
      fly animation + warp → verify arrival.

Cursor navigation uses the "reset to corner" strategy: press left+up enough
times to guarantee the cursor is at the top-left bound (2, 7), then navigate
from there to the target grid position.  This avoids needing to know the
cursor's starting position.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
MENU_WAIT = 300
NAV_WAIT = 60
FLY_MAP_OPEN_WAIT = 600   # town map open animation
FLY_WARP_WAIT = 3600      # fly cut-in + night sky + landing animation (~60 sec game time)

# ── Pause menu ──
POKEMON_INDEX = 1
MENU_SIZE = 7

# ── Party screen (D-pad, 2-column grid) ──
PARTY_NAV_ABS = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}

# ── Cursor bounds on the town map ──
CURSOR_MIN_X = 2
CURSOR_MIN_Z = 7
CURSOR_MAX_X = 27
CURSOR_MAX_Z = 27

# ── Fly destinations ──
# Grid positions derived from decomp (fly_locations.c spriteX/spriteY ÷ 7).
# Cursor target = grid position that falls within the destination's hitbox.
# For multi-tile shapes, we target the NW corner (which is inside the shape).
_FLY_DESTINATIONS: list[dict[str, Any]] = [
    # Towns (1x1 or small shapes) — grid positions verified against decomp
    # sprite coords, with +1/+1 offset for cursor hit detection.
    {"name": "Twinleaf Town",     "code": "T01", "map_id": 411, "grid": (4, 28)},
    {"name": "Sandgem Town",      "code": "T02", "map_id": 418, "grid": (6, 27)},
    {"name": "Floaroma Town",     "code": "T03", "map_id": 426, "grid": (6, 20)},
    {"name": "Solaceon Town",     "code": "T04", "map_id": 433, "grid": (18, 21)},
    {"name": "Celestic Town",     "code": "T05", "map_id": 442, "grid": (15, 17)},
    {"name": "Survival Area",     "code": "T06", "map_id": 450, "grid": (21, 11)},
    {"name": "Resort Area",       "code": "T07", "map_id": 457, "grid": (26, 15)},
    # Cities (2x2 or L-shaped)
    {"name": "Jubilife City",     "code": "C01", "map_id":   3, "grid": (5, 24)},
    {"name": "Canalave City",     "code": "C02", "map_id":  33, "grid": (2, 23)},
    {"name": "Oreburgh City",     "code": "C03", "map_id":  45, "grid": (9, 24)},
    {"name": "Eterna City",       "code": "C04", "map_id":  65, "grid": (10, 17)},
    {"name": "Hearthome City",    "code": "C05", "map_id":  86, "grid": (15, 22)},
    {"name": "Pastoria City",     "code": "C06", "map_id": 120, "grid": (19, 26)},
    {"name": "Veilstone City",    "code": "C07", "map_id": 132, "grid": (22, 19)},
    {"name": "Sunyshore City",    "code": "C08", "map_id": 150, "grid": (27, 24)},
    {"name": "Snowpoint City",    "code": "C09", "map_id": 165, "grid": (12, 7)},
    {"name": "Fight Area",        "code": "C11", "map_id": 188, "grid": (20, 14)},
    # Special locations
    {"name": "Pal Park",          "code": "D11", "map_id": 252, "grid": (10, 27)},
    {"name": "Pokemon League",    "code": "C10", "map_id": 172, "grid": (27, 18)},
]

# Lookup by name (case-insensitive) and by code
_BY_NAME = {d["name"].lower(): d for d in _FLY_DESTINATIONS}
_BY_CODE = {d["code"]: d for d in _FLY_DESTINATIONS}

# Map code prefix → fly destination (for determining cursor start position)
_CODE_TO_FLY = {}
for d in _FLY_DESTINATIONS:
    _CODE_TO_FLY[d["code"]] = d


def _resolve_destination(destination: str) -> dict[str, Any] | None:
    """Resolve a destination string to a fly destination dict."""
    key = destination.strip().lower()
    # Exact name match
    if key in _BY_NAME:
        return _BY_NAME[key]
    # Code match (case-insensitive)
    upper = destination.strip().upper()
    if upper in _BY_CODE:
        return _BY_CODE[upper]
    # Partial name match
    for name, dest in _BY_NAME.items():
        if key in name:
            return dest
    return None


def _find_fly_user(party: list[dict]) -> int | None:
    """Find the first party slot that knows Fly."""
    for p in party:
        for m in p.get("moves", []):
            if m.get("name", "").lower() == "fly":
                return p["slot"]
    return None


def _count_field_moves(party: list[dict], slot: int) -> int:
    """Count usable field moves before Fly in the Pokemon submenu.

    In Gen 4, field moves appear in the submenu in the order they appear
    in the Pokemon's moveset.  We need to know how many field moves come
    before Fly to navigate the submenu correctly.
    """
    field_hms = {
        "cut", "fly", "surf", "strength", "defog",
        "rock smash", "waterfall", "rock climb",
    }
    mon = party[slot] if slot < len(party) else None
    if not mon:
        return 0
    count = 0
    for m in mon.get("moves", []):
        name = m.get("name", "").lower()
        if name == "fly":
            return count
        if name in field_hms:
            count += 1
    return count


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def use_fly(emu: EmulatorClient, destination: str) -> dict[str, Any]:
    """Fly to a destination city or town.

    Args:
        emu: Emulator client.
        destination: City/town name (e.g. "Jubilife City", "Eterna City")
                     or code (e.g. "C01", "T03"). Case-insensitive, partial match OK.

    Returns dict with success status, destination info, and new location.
    """
    from renegade_mcp.party import read_party
    from renegade_mcp.trainer import read_trainer_status
    from renegade_mcp.map_names import lookup_map_name
    from renegade_mcp.map_state import read_player_state

    # ── Resolve destination ──
    dest = _resolve_destination(destination)
    if not dest:
        names = [d["name"] for d in _FLY_DESTINATIONS]
        return _error(
            f"Unknown fly destination: {destination!r}. "
            f"Valid destinations: {', '.join(names)}"
        )

    # ── Pre-checks ──
    trainer = read_trainer_status(emu)
    if trainer.get("badges", 0) < 3:
        return _error(
            f"Fly requires the Cobble Badge (3rd badge). "
            f"Current badges: {trainer.get('badges', 0)}/8."
        )

    party = read_party(emu)
    fly_slot = _find_fly_user(party)
    if fly_slot is None:
        return _error("No party Pokemon knows Fly. Teach HM02 to a Pokemon first.")

    fly_user = party[fly_slot].get("name", f"slot {fly_slot}")

    # Record starting map to verify warp later
    start_map_id, _, _, _ = read_player_state(emu)
    start_info = lookup_map_name(start_map_id)

    # ── Step 1: Open pause menu ──
    from renegade_mcp.pause_menu import open_pause_menu
    from renegade_mcp.addresses import addr

    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to POKEMON ──
    cursor = emu.read_memory(addr("PAUSE_CURSOR_ADDR"), size="byte")
    diff = (POKEMON_INDEX - cursor) % MENU_SIZE
    for _ in range(diff):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Navigate to the Fly user's party slot ──
    for direction in PARTY_NAV_ABS.get(fly_slot, []):
        _press(emu, [direction])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 4: Select "Fly" from the submenu ──
    # Submenu order: SUMMARY, [field moves in moveset order...], SWITCH, ITEM, CANCEL.
    # SUMMARY is always first (index 0). Fly is at index 1 + number of field
    # moves that appear before it in the Pokemon's moveset.
    fly_menu_pos = 1 + _count_field_moves(party, fly_slot)
    for _ in range(fly_menu_pos):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=FLY_MAP_OPEN_WAIT)

    # ── Step 5: Navigate town map cursor to destination ──
    # Strategy: reset cursor to top-left corner, then navigate to target.
    # Cursor bounds: X ∈ [2, 27], Z ∈ [7, 27].
    # Max 26 presses in any direction guarantees we hit the corner.
    reset_presses = 26
    for _ in range(reset_presses):
        emu.press_buttons(["left"], frames=4)
        emu.advance_frames(4)
    for _ in range(reset_presses):
        emu.press_buttons(["up"], frames=4)
        emu.advance_frames(4)
    emu.advance_frames(NAV_WAIT)  # settle

    # Now cursor is at (CURSOR_MIN_X, CURSOR_MIN_Z) = (2, 7).
    # Navigate to target grid position.
    target_x, target_z = dest["grid"]
    dx = target_x - CURSOR_MIN_X
    dz = target_z - CURSOR_MIN_Z

    h_dir = "right" if dx > 0 else "left"
    for _ in range(abs(dx)):
        emu.press_buttons([h_dir], frames=4)
        emu.advance_frames(4)

    v_dir = "down" if dz > 0 else "up"
    for _ in range(abs(dz)):
        emu.press_buttons([v_dir], frames=4)
        emu.advance_frames(4)

    emu.advance_frames(NAV_WAIT)  # settle on target

    # ── Step 6: Confirm selection ──
    # A on a valid fly destination starts the fly immediately (no confirmation prompt).
    _press(emu, ["a"], wait=FLY_WARP_WAIT)

    # ── Step 7: Verify arrival ──
    # Advance a few extra frames to ensure the overworld is fully loaded
    # and the renderer has caught up (melonDS skips rendering on fast-forwarded
    # frames, so the last rendered frame may lag behind game state).
    emu.advance_frames(300)
    new_map_id, _, _, _ = read_player_state(emu)
    new_info = lookup_map_name(new_map_id)

    # Check if we arrived at the destination (or a related map)
    dest_code = dest["code"]
    arrived = (
        new_info.get("code", "").startswith(dest_code)
        or new_map_id == dest["map_id"]
        or new_map_id != start_map_id  # at least we moved somewhere
    )

    if arrived and new_map_id != start_map_id:
        return {
            "success": True,
            "destination": dest["name"],
            "fly_user": fly_user,
            "from": start_info.get("display", f"Map {start_map_id}"),
            "to": new_info.get("display", f"Map {new_map_id}"),
            "map_id": new_map_id,
            "formatted": (
                f"Flew from {start_info.get('display', '?')} to "
                f"{new_info.get('display', '?')} using {fly_user}!"
            ),
        }

    # Fly might have failed (indoors, partner, etc.) or map didn't change
    # Try to clean up menus
    for _ in range(5):
        _press(emu, ["b"], wait=MENU_WAIT)

    return _error(
        f"Fly to {dest['name']} may have failed. "
        f"Still on map {new_info.get('display', new_map_id)}. "
        "Check: are you indoors? Travelling with a partner? "
        "Location might not allow Fly."
    )


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
