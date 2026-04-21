"""Shared helpers for the overworld party sub-menu.

When a Pokemon is selected in the pause-menu party screen, a context menu
appears. Its rows are built by `GetContextMenuEntriesForPartyMon` in the
decomp (`src/applications/party_menu/main.c:1793`):

    Summary
    [field moves known, in moveset order]
    Switch      (or "Take Mail" if holding mail)
    Item
    Cancel

The field-move list comes from `sFieldMoves` (main.c:245). A move is
"field-usable" if it's one of Cut, Fly, Surf, Strength, Defog, Rock Smash,
Waterfall, Rock Climb, Flash, Teleport, Dig, Sweet Scent, Chatter,
Milk Drink, or Softboiled — independent of whether the move is currently
usable in the environment.

Tools that drive the sub-menu with D-pad must offset their cursor by the
number of field moves the Pokemon knows (otherwise they land on the wrong
row). This module centralises that logic.
"""

from __future__ import annotations

# ── Field moves that create sub-menu rows (lowercase for case-insensitive compare) ──
FIELD_MOVES: frozenset[str] = frozenset({
    "cut", "fly", "surf", "strength", "defog",
    "rock smash", "waterfall", "rock climb",
    "flash", "teleport", "dig", "sweet scent", "chatter",
    "milk drink", "softboiled",
})


def _moves_of(mon: dict) -> list[str]:
    """Return a Pokemon's moves as a list of lowercase names."""
    return [m.get("name", "").lower() for m in mon.get("moves", [])]


def count_field_moves(mon: dict) -> int:
    """Total field moves in the Pokemon's moveset."""
    return sum(1 for name in _moves_of(mon) if name in FIELD_MOVES)


def count_field_moves_before(mon: dict, target_move: str) -> int:
    """Count field moves that appear BEFORE the named move in the moveset.

    Used by `use_fly` to navigate to the Fly row: Fly itself appears in
    moveset order among field moves, so its row index within the sub-menu
    is 1 (for Summary) + the number of field moves preceding it.
    """
    target_lower = target_move.lower()
    count = 0
    for name in _moves_of(mon):
        if name == target_lower:
            return count
        if name in FIELD_MOVES:
            count += 1
    return count


def switch_row(mon: dict) -> int:
    """Row index of "Switch" in the sub-menu (0-based)."""
    return 1 + count_field_moves(mon)


def item_row(mon: dict) -> int:
    """Row index of "Item" in the sub-menu (0-based)."""
    return 2 + count_field_moves(mon)


def summary_row() -> int:
    """Row index of "Summary" — always 0."""
    return 0
