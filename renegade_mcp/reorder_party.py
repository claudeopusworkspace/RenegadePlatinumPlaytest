"""Swap two party Pokemon positions from the overworld.

Opens pause menu → Pokemon → selects source → Switch → selects destination.
Uses D-pad navigation (overworld party screen is on the top screen).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import (
    open_pause_menu,
)

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
MENU_WAIT = 300       # frames after major menu transitions
NAV_WAIT = 60         # frames after D-pad navigation

# ── Pause menu ──
POKEMON_INDEX = 1     # 0=Pokedex, 1=Pokemon, 2=Bag, ...
MENU_SIZE = 7

# ── Party screen (top screen, D-pad, 2-column grid) ──
# Layout:  0  1
#          2  3
#          4  5
PARTY_NAV_ABS = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _slot_pos(slot: int) -> tuple[int, int]:
    """Return (row, col) for a party slot."""
    return divmod(slot, 2)


def _relative_nav(from_slot: int, to_slot: int) -> list[str]:
    """Compute D-pad presses to navigate from one party slot to another."""
    fr, fc = _slot_pos(from_slot)
    tr, tc = _slot_pos(to_slot)

    moves: list[str] = []
    # Vertical first, then horizontal
    row_diff = tr - fr
    if row_diff > 0:
        moves.extend(["down"] * row_diff)
    elif row_diff < 0:
        moves.extend(["up"] * (-row_diff))

    col_diff = tc - fc
    if col_diff > 0:
        moves.extend(["right"] * col_diff)
    elif col_diff < 0:
        moves.extend(["left"] * (-col_diff))

    return moves


def reorder_party(
    emu: EmulatorClient, from_slot: int, to_slot: int,
) -> dict[str, Any]:
    """Swap two party Pokemon by slot index.

    Args:
        emu: Emulator client.
        from_slot: Source party slot (0-5).
        to_slot: Destination party slot (0-5).

    Returns dict with success status and updated party.
    """
    if from_slot == to_slot:
        return _error("from_slot and to_slot are the same.")
    if not (0 <= from_slot <= 5 and 0 <= to_slot <= 5):
        return _error(f"Slots must be 0-5, got from={from_slot} to={to_slot}.")

    # Pre-read party: we need the source Pokemon's moveset to compute the
    # sub-menu offset for "Switch", and we need the before-state species IDs
    # to verify the swap committed.
    party_before = read_party(emu)
    if from_slot >= len(party_before) or to_slot >= len(party_before):
        return _error(
            f"Party has {len(party_before)} member(s); cannot swap "
            f"{from_slot} <-> {to_slot}."
        )

    source_mon = party_before[from_slot]
    from renegade_mcp.party_submenu import switch_row

    # ── Step 1: Open pause menu (with readiness check) ──
    if not open_pause_menu(emu):
        return _error("Could not open pause menu — player may not have control.")

    # ── Step 2: Navigate to POKEMON ──
    from renegade_mcp.addresses import addr
    cursor = emu.read_memory(addr("PAUSE_CURSOR_ADDR"), size="byte")
    diff = POKEMON_INDEX - cursor
    direction = "down" if diff > 0 else "up"
    for _ in range(abs(diff)):
        _press(emu, [direction])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 3: Navigate to source slot and select ──
    for direction in PARTY_NAV_ABS[from_slot]:
        _press(emu, [direction])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 4: Choose "Switch" from submenu ──
    # Menu: Summary, [field moves in moveset order], Switch, Item, Cancel.
    # Each field move the Pokemon knows pushes Switch down one row.
    switch_offset = switch_row(source_mon)
    for _ in range(switch_offset):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 5: Navigate from source to destination ──
    for direction in _relative_nav(from_slot, to_slot):
        _press(emu, [direction])
    _press(emu, ["a"], wait=MENU_WAIT)

    # ── Step 6: Close menus ──
    _press(emu, ["b"], wait=MENU_WAIT)   # close party screen
    _press(emu, ["b"], wait=MENU_WAIT)   # close pause menu

    # ── Step 7: Verify the swap actually committed ──
    from renegade_mcp.party import format_party
    party_after = read_party(emu)
    names = [p.get("name", "?") for p in party_after]

    # Compare species IDs (name can be a nickname and thus unreliable for
    # same-species pairs, but species_id is stable across slots).
    before_src = source_mon.get("species_id", 0)
    before_dst = party_before[to_slot].get("species_id", 0)
    after_src = party_after[from_slot].get("species_id", 0) if from_slot < len(party_after) else 0
    after_dst = party_after[to_slot].get("species_id", 0) if to_slot < len(party_after) else 0

    swapped = (after_src == before_dst) and (after_dst == before_src)

    if not swapped:
        err = (
            f"Swap did not commit. Before: slot {from_slot}={source_mon.get('name','?')} "
            f"(species {before_src}), slot {to_slot}={party_before[to_slot].get('name','?')} "
            f"(species {before_dst}). After: slot {from_slot} species {after_src}, "
            f"slot {to_slot} species {after_dst}. Menu cursor likely landed on the "
            "wrong sub-menu row."
        )
        return {
            "success": False,
            "error": err,
            "from_slot": from_slot,
            "to_slot": to_slot,
            "party": party_after,
            "formatted": "Error: " + err + "\n\n" + format_party(party_after),
        }

    msg = f"Swapped slot {from_slot} with slot {to_slot}. Party: {', '.join(names)}."
    return {
        "success": True,
        "from_slot": from_slot,
        "to_slot": to_slot,
        "party": party_after,
        "formatted": msg + "\n\n" + format_party(party_after),
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
