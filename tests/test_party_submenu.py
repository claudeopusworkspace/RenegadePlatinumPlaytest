"""Unit tests for renegade_mcp.party_submenu — row offsets in the overworld
party context menu.

No emulator needed: these exercise the pure-Python helper that consumes a
`read_party` Pokemon dict and returns the correct sub-menu row index.
"""

from __future__ import annotations

from renegade_mcp.party_submenu import (
    FIELD_MOVES,
    count_field_moves,
    count_field_moves_before,
    item_row,
    switch_row,
)


def _mon(*move_names: str) -> dict:
    """Build a minimal mon dict in the shape read_party returns."""
    return {"moves": [{"name": n} for n in move_names]}


class TestFieldMoveSet:
    def test_contains_all_gen4_field_moves(self):
        expected = {
            "cut", "fly", "surf", "strength", "defog",
            "rock smash", "waterfall", "rock climb",
            "flash", "teleport", "dig", "sweet scent", "chatter",
            "milk drink", "softboiled",
        }
        assert expected == set(FIELD_MOVES)

    def test_lowercase_only(self):
        for name in FIELD_MOVES:
            assert name == name.lower()


class TestCountFieldMoves:
    def test_no_moves(self):
        assert count_field_moves({"moves": []}) == 0

    def test_no_field_moves(self):
        mon = _mon("Tackle", "Growl", "Ember", "Scratch")
        assert count_field_moves(mon) == 0

    def test_single_field_move(self):
        # Grotle from the bug repro: Bulldoze, Cut, Bullet Seed, Razor Leaf.
        mon = _mon("Bulldoze", "Cut", "Bullet Seed", "Razor Leaf")
        assert count_field_moves(mon) == 1

    def test_multiple_field_moves(self):
        mon = _mon("Cut", "Surf", "Rock Smash", "Strength")
        assert count_field_moves(mon) == 4

    def test_case_insensitive(self):
        mon = _mon("CUT", "Rock SMASH", "tackle")
        assert count_field_moves(mon) == 2

    def test_ignores_missing_name(self):
        mon = {"moves": [{}, {"name": "Cut"}]}
        assert count_field_moves(mon) == 1


class TestCountFieldMovesBefore:
    def test_target_first(self):
        mon = _mon("Fly", "Cut", "Surf")
        assert count_field_moves_before(mon, "Fly") == 0

    def test_target_last(self):
        mon = _mon("Cut", "Surf", "Rock Smash", "Fly")
        assert count_field_moves_before(mon, "fly") == 3

    def test_target_missing_returns_total_field_moves(self):
        # When target isn't in the moveset the loop falls through and
        # returns the running count — the caller shouldn't rely on this,
        # but document the behavior.
        mon = _mon("Cut", "Surf")
        assert count_field_moves_before(mon, "Fly") == 2

    def test_non_field_moves_don_t_count(self):
        mon = _mon("Tackle", "Cut", "Growl", "Fly")
        assert count_field_moves_before(mon, "Fly") == 1


class TestSwitchRow:
    """Switch lives after Summary + all field moves."""

    def test_no_field_moves(self):
        # Summary(0) -> Switch(1)
        assert switch_row(_mon("Tackle")) == 1

    def test_one_field_move(self):
        # Summary(0) -> Cut(1) -> Switch(2). This is the bug repro case.
        assert switch_row(_mon("Bulldoze", "Cut", "Bullet Seed", "Razor Leaf")) == 2

    def test_max_field_moves(self):
        # 4 field moves -> Switch at row 5.
        assert switch_row(_mon("Cut", "Surf", "Fly", "Strength")) == 5


class TestItemRow:
    """Item is one row below Switch."""

    def test_no_field_moves(self):
        assert item_row(_mon("Tackle")) == 2

    def test_with_field_move(self):
        assert item_row(_mon("Cut", "Tackle")) == 3

    def test_switch_and_item_adjacent(self):
        for moves in [(), ("Cut",), ("Cut", "Surf"), ("Cut", "Surf", "Fly", "Strength")]:
            mon = _mon(*moves)
            assert item_row(mon) - switch_row(mon) == 1
