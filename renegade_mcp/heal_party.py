"""Heal the party at a Pokemon Center by talking to Nurse Joy.

If already inside a Pokemon Center, finds the nurse and heals directly.
If on a city/town overworld, auto-navigates to the Pokemon Center first,
then heals. Encounter interruptions during navigation are reported back.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from renegade_mcp.data import map_table
from renegade_mcp.dialogue import (
    _decode_values,
    _find_active_slots,
    _overworld_region,
    read_dialogue,
)
from renegade_mcp.map_state import get_map_state, read_player_state, read_warps_from_rom
from renegade_mcp.navigation import interact_with, navigate_to
from renegade_mcp.party import read_party

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
TEXT_WAIT = 120       # frames to let a dialogue line render
HEAL_ANIM_WAIT = 300  # frames for the Pokeball healing animation
SETTLE_WAIT = 120     # frames after final dialogue dismissal

# ── Expected dialogue ──
NURSE_GREETING = "would you like to rest your"


def _press(emu: EmulatorClient, buttons: list[str], wait: int = TEXT_WAIT) -> None:
    """Press buttons and wait.

    Uses a 2-frame hold to avoid bleed-through on melonDS — 8 frames
    can span fast menu transitions and register as multiple actions.
    """
    emu.press_buttons(buttons, frames=2)
    emu.advance_frames(wait)


def _dialogue_contains(emu: EmulatorClient, needle: str) -> bool:
    """Check if ANY active dialogue slot contains the given text (case-insensitive)."""
    start_addr, size, _ = _overworld_region()
    raw = emu.read_memory_range(start_addr, size="byte", count=size)
    if not raw:
        return False
    data = bytes(raw)
    slots = _find_active_slots(data, start_addr)
    for _, values, _ in slots:
        lines = _decode_values(values)
        text = " ".join(lines).lower()
        if needle in text:
            return True
    return False


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


# ── City / warp helpers ──


def _city_code_from_map(map_id: int) -> str | None:
    """Extract the city/town code (e.g. 'C01', 'T03') from a map ID."""
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")
    m = re.match(r"^([CT]\d{2})", code)
    return m.group(1) if m else None


def _find_pokecenter_warp(
    emu: EmulatorClient, map_id: int, city_code: str,
) -> dict | None:
    """Find a warp on the current map that leads to this city's Pokemon Center."""
    warps = read_warps_from_rom(emu, map_id)
    table = map_table()
    for w in warps:
        dest_entry = table.get(w["dest_map"], {})
        dest_code = dest_entry.get("code", "")
        if dest_code.startswith(f"{city_code}PC"):
            return w
    return None


# ── Core heal logic ──


def _heal_at_nurse(emu: EmulatorClient) -> dict[str, Any]:
    """Find nurse on current map, interact, heal, verify HP restored."""
    state = get_map_state(emu)
    if state is None:
        return _error("Could not read map state.")

    nurse = next(
        (obj for obj in state["objects"] if obj.get("name") == "Pokecenter Nurse"),
        None,
    )
    if nurse is None:
        names = [obj.get("name", "?") for obj in state["objects"] if obj["index"] != 0]
        return _error(
            f"No Pokecenter Nurse found on this map. "
            f"NPCs: {', '.join(names)}"
        )

    # ── Interact ──
    result = interact_with(emu, nurse["index"])

    if result.get("interrupted") or result.get("encounter"):
        return _error(
            "Navigation to Nurse Joy was interrupted by an encounter or event. "
            f"Details: {result.get('encounter') or result}"
        )

    if result.get("stopped_early"):
        return _error("Could not reach Nurse Joy — path was blocked.")

    # ── Validate greeting dialogue ──
    dialogue = result.get("dialogue")
    dialogue_text = (dialogue.get("text", "") if dialogue else "").lower()

    if NURSE_GREETING not in dialogue_text:
        # Possibly stale dialogue from a previous interaction. Dismiss with B,
        # then re-talk to nurse (B won't re-trigger her).
        for _ in range(6):
            _press(emu, ["b"], wait=60)

        _press(emu, ["a"])
        found_greeting = _dialogue_contains(emu, NURSE_GREETING)

        if not found_greeting:
            actual = dialogue.get("text", "(none)") if dialogue else "(none)"
            return _error(
                f"Unexpected dialogue from Nurse Joy: \"{actual}\". "
                "An event may be active — aborting heal to avoid misclicks."
            )

    # ── Dialogue is confirmed. Advance through healing flow. ──
    # interact_with + advance_dialogue stops at the Yes/No prompt,
    # so the first A press selects YES (no extra press needed to reach it).
    _press(emu, ["a"])                    # select YES
    _press(emu, ["a"], wait=HEAL_ANIM_WAIT)  # healing animation
    for _ in range(5):                    # clear remaining dialogue lines
        _press(emu, ["b"])
    emu.advance_frames(SETTLE_WAIT)

    # ── Verify dialogue is gone (back to free movement) ──
    leftover = read_dialogue(emu, region="overworld")
    if leftover.get("region") != "none" and leftover.get("text"):
        for _ in range(5):
            _press(emu, ["b"])
        emu.advance_frames(SETTLE_WAIT)

    # ── Verify healing ──
    party = read_party(emu)
    all_healed = all(
        p.get("hp", 0) == p.get("max_hp", 0)
        for p in party
        if not p.get("partial")
    )

    formatted_lines = ["=== Pokemon Center Heal ==="]
    for p in party:
        hp = p.get("hp", "?")
        max_hp = p.get("max_hp", "?")
        name = p.get("name", "???")
        level = p.get("level", "?")
        partial = " [stale data]" if p.get("partial") else ""
        formatted_lines.append(f"  {name} Lv{level}  HP {hp}/{max_hp}{partial}")

    if all_healed:
        formatted_lines.append("\nAll Pokemon restored to full health!")
    else:
        formatted_lines.append("\nWarning: some Pokemon may not be fully healed.")

    return {
        "success": all_healed,
        "party": party,
        "formatted": "\n".join(formatted_lines),
    }


# ── Public entry point ──


def heal_party(emu: EmulatorClient) -> dict[str, Any]:
    """Heal the party at a Pokemon Center.

    Routing logic:
      1. Already inside a Pokemon Center → heal directly.
      2. On a city/town overworld → find PC warp, navigate there, then heal.
      3. Anywhere else → error (navigate manually first).

    Encounter interruptions during overworld navigation are returned with
    an ``encounter`` key so the caller can handle them.
    """
    map_id, _x, _y, _facing = read_player_state(emu)
    entry = map_table().get(map_id, {})
    code = entry.get("code", "")

    # ── Case 1: already in a Pokemon Center ──
    if "PC" in code:
        return _heal_at_nurse(emu)

    # ── Case 2: on a city/town overworld ──
    city_code = _city_code_from_map(map_id)
    if city_code is not None and code == city_code:
        pc_warp = _find_pokecenter_warp(emu, map_id, city_code)
        if pc_warp is None:
            return _error(
                f"No Pokemon Center warp found in {entry.get('name', city_code)}."
            )

        nav_result = navigate_to(emu, pc_warp["x"], pc_warp["y"], flee_encounters=True)

        # Wild encounter or NPC event during navigation
        if nav_result.get("encounter"):
            return {
                "success": False,
                "error": "Navigation to Pokemon Center interrupted by encounter.",
                "encounter": nav_result["encounter"],
                "formatted": (
                    "Error: Navigation to Pokemon Center interrupted by encounter. "
                    "Deal with the encounter and try again."
                ),
            }

        # Path blocked and door wasn't entered
        if nav_result.get("stopped_early") and not nav_result.get("door_entered"):
            return _error(
                "Could not reach the Pokemon Center — path was blocked. "
                f"Path: {nav_result.get('path', 'unknown')}"
            )

        # Should now be inside the Pokemon Center
        result = _heal_at_nurse(emu)
        if result.get("success"):
            result["navigated_to_pc"] = True
        return result

    # ── Case 3: not in a city or inside a non-PC building ──
    loc_name = entry.get("name", f"Map {map_id}")
    return _error(
        f"Not in a Pokemon Center or city overworld ({loc_name}). "
        "Navigate closer to a Pokemon Center first."
    )
