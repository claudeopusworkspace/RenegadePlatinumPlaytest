"""Regression tests for QA BUG-018.

BUG-018: Mid-battle ``MOVE_LEARN`` returned ``learning_pokemon`` for the
wrong party slot when an earlier mon in the party had already leveled up
in the same battle.

Repro (from session 14 Gardenia): Monferno (slot 0) leveled to 31, then
fainted. Mothim (slot 2) was switched in and finished off the remaining
opponents. Mothim hit Lv29 → Poison Powder prompt. Tool reported
``learning_pokemon: slot 0, Monferno`` — because ``levelUpMons`` is a
cumulative OR mask that's *only ever* set via ``|= FlagIndex(slot)``
(ref/pokeplatinum/src/battle/battle_script.c:10090), never cleared after a
level-up. With bits 0 and 2 both lingering, the old "lowest set bit >=
scan index" heuristic returned slot 0.

Fix: ``_get_move_learn_info`` now cross-references each candidate slot's
species learnset — only the mon whose learnset has (current_level,
move_id) can be in the move-learn flow. The scan-index heuristic stays as
a fallback for cases where the ROM learnset data is incomplete.

These tests mock memory reads + ``read_party`` so we can construct the
exact state where levelUpMons has two bits set. A live-save repro would
require replaying the Gardenia battle end-to-end, which is fragile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def _install_memory_mock(monkeypatch, task_ptr_val, move_id, slot_lower,
                          level_up_mask):
    """Stub out emu.read_memory for addresses used by _get_move_learn_info."""
    from renegade_mcp import turn as turn_mod
    from renegade_mcp.addresses import addr

    task_data_move_off = turn_mod.TASK_DATA_MOVE_OFF
    task_data_slot_off = turn_mod.TASK_DATA_SLOT_OFF
    task_ptr_addr = addr("TASK_DATA_PTR_ADDR")
    level_up_addr = addr("LEVEL_UP_MONS_ADDR")

    responses = {
        task_ptr_addr: task_ptr_val,
        task_ptr_val + task_data_move_off: move_id,
        task_ptr_val + task_data_slot_off: slot_lower,
        level_up_addr: level_up_mask,
    }

    class _StubEmu:
        def read_memory(self, address, size="long"):
            return responses.get(address, 0)

    return _StubEmu()


def _patch_read_party(monkeypatch, party):
    """Replace read_party with a stub returning party.

    get_move_learn_info was extracted from turn.py into move_learning.py;
    patch both bindings so the underlying call resolves to our stub
    regardless of which module's binding Python hits first.
    """
    stub = lambda emu: party  # noqa: E731
    monkeypatch.setattr("renegade_mcp.turn.read_party", stub)
    monkeypatch.setattr("renegade_mcp.move_learning.read_party", stub)


class TestQaBug018MoveLearnLearnsetMatch:
    """_get_move_learn_info disambiguates via species learnset."""

    def test_mothim_learns_poison_powder_not_monferno(self, monkeypatch):
        """Canonical BUG-018 repro: two bits set, only Mothim's learnset matches."""
        from renegade_mcp.turn import _get_move_learn_info

        # Monferno (slot 0, Lv31) fainted, Mothim (slot 2, Lv29) is learning
        # Poison Powder (move id 77).
        party = [
            {"slot": 0, "species_id": 391, "level": 31, "name": "Monferno"},
            {"slot": 1, "species_id": 134, "level": 17, "name": "Vaporeon"},
            {"slot": 2, "species_id": 414, "level": 29, "name": "Mothim"},
            {"slot": 3, "species_id": 403, "level": 6,  "name": "Shinx"},
        ]
        emu = _install_memory_mock(
            monkeypatch,
            task_ptr_val=0x0220_0100,
            move_id=77,         # Poison Powder
            slot_lower=0,       # Stale scan index still at 0
            level_up_mask=0b00000101,  # bits 0 and 2 both set
        )
        _patch_read_party(monkeypatch, party)

        info = _get_move_learn_info(emu)
        assert info is not None
        slot, mid = info
        assert slot == 2, (
            f"Expected Mothim slot 2 via learnset cross-check, got slot {slot}"
        )
        assert mid == 77

    def test_single_level_up_learnset_match(self, monkeypatch):
        """Single bit set still returns the correct slot."""
        from renegade_mcp.turn import _get_move_learn_info

        party = [
            {"slot": 0, "species_id": 391, "level": 30, "name": "Monferno"},
            {"slot": 1, "species_id": 134, "level": 17, "name": "Vaporeon"},
        ]
        emu = _install_memory_mock(
            monkeypatch,
            task_ptr_val=0x0220_0100,
            move_id=77,          # Poison Powder — Monferno does NOT learn this
            slot_lower=0,
            level_up_mask=0b00000001,  # only slot 0
        )
        _patch_read_party(monkeypatch, party)

        # No learnset match for Monferno — falls back to scan heuristic →
        # slot 0 (the only bit set).
        info = _get_move_learn_info(emu)
        assert info == (0, 77)

    def test_fallback_when_no_species_matches_move(self, monkeypatch):
        """No species in party learns the move — fall back to scan heuristic.

        move_id=1 (Pound) is valid per the 1-467 range guard but no
        party-slot species learns it at its current level, so the learnset
        cross-check yields zero matches and the scan fallback kicks in.
        """
        from renegade_mcp.turn import _get_move_learn_info

        party = [
            {"slot": 0, "species_id": 391, "level": 30, "name": "Monferno"},
            {"slot": 1, "species_id": 134, "level": 20, "name": "Vaporeon"},
            {"slot": 2, "species_id": 414, "level": 28, "name": "Mothim"},
        ]
        emu = _install_memory_mock(
            monkeypatch,
            task_ptr_val=0x0220_0100,
            move_id=1,          # Pound — valid, but not in any party species' Lv ___ entry
            slot_lower=1,
            level_up_mask=0b00000101,
        )
        _patch_read_party(monkeypatch, party)

        info = _get_move_learn_info(emu)
        # Fallback path: lowest set bit >= slot_lower (1) → slot 2.
        assert info == (2, 1)

    def test_null_task_ptr_returns_none(self, monkeypatch):
        """No active EXP task → None, don't touch party."""
        from renegade_mcp.turn import _get_move_learn_info

        # read_party must not be called when task_ptr is null.
        def _explode(_emu):
            raise AssertionError("read_party should not be called when task_ptr=0")
        monkeypatch.setattr("renegade_mcp.turn.read_party", _explode)

        emu = _install_memory_mock(
            monkeypatch, task_ptr_val=0, move_id=0, slot_lower=0,
            level_up_mask=0,
        )
        assert _get_move_learn_info(emu) is None

    def test_zero_level_up_mask_returns_none(self, monkeypatch):
        """No leveled-up mons → None regardless of task data."""
        from renegade_mcp.turn import _get_move_learn_info

        emu = _install_memory_mock(
            monkeypatch,
            task_ptr_val=0x0220_0100,
            move_id=77, slot_lower=0,
            level_up_mask=0,
        )
        _patch_read_party(monkeypatch, [])
        assert _get_move_learn_info(emu) is None

    def test_invalid_move_id_returns_none(self, monkeypatch):
        """Move ID outside valid range (1-467) → None (guard against garbage)."""
        from renegade_mcp.turn import _get_move_learn_info

        emu = _install_memory_mock(
            monkeypatch,
            task_ptr_val=0x0220_0100,
            move_id=0,  # invalid
            slot_lower=0,
            level_up_mask=0b00000001,
        )
        _patch_read_party(monkeypatch, [{"slot": 0, "species_id": 1, "level": 5}])
        assert _get_move_learn_info(emu) is None

    def test_fainted_earlier_leveler_ignored(self, monkeypatch):
        """Even when slot_lower=0 and earlier bit is set, pick the right slot."""
        # This is the exact QA scenario, phrased as an explicit assertion
        # that slot_lower staleness does NOT cause misattribution.
        from renegade_mcp.turn import _get_move_learn_info

        party = [
            {"slot": 0, "species_id": 391, "level": 31, "name": "Monferno"},
            {"slot": 1, "species_id": 134, "level": 17, "name": "Vaporeon"},
            {"slot": 2, "species_id": 414, "level": 29, "name": "Mothim"},
        ]
        emu = _install_memory_mock(
            monkeypatch,
            task_ptr_val=0x0220_0100,
            move_id=77,      # Mothim's Poison Powder
            slot_lower=0,    # maximally stale — scan would pick slot 0
            level_up_mask=0b00000101,
        )
        _patch_read_party(monkeypatch, party)

        slot, _ = _get_move_learn_info(emu)
        assert slot != 0, (
            "Fainted earlier leveler must not shadow the real learning mon"
        )
        assert slot == 2


class TestQaBug018LevelUpMaskAccumulation:
    """levelUpMons is cumulative — document the root cause as a test."""

    def test_level_up_mons_is_or_accumulated(self):
        """Decomp audit: levelUpMons is |=-set and never cleared.

        The only write in battle_script.c is::

            data->battleCtx->levelUpMons |= FlagIndex(slot);

        There is no paired ``&= ~FlagIndex(slot)`` or ``= 0`` after a mon's
        move-learn completes. This test is a grep-style assertion to catch a
        future decomp upgrade that silently changes the semantics.
        """
        from pathlib import Path
        bs = Path(
            "/workspace/RenegadePlatinumPlaytest/ref/pokeplatinum/"
            "src/battle/battle_script.c"
        )
        if not bs.exists():
            pytest.skip("Decomp source not present")
        text = bs.read_text()
        assignments = [
            line for line in text.splitlines()
            if "levelUpMons" in line and "=" in line
               and "//" not in line.split("levelUpMons")[0]
        ]
        # Exactly one write: |= FlagIndex(slot).
        assert len(assignments) == 1, (
            f"Expected one levelUpMons write in battle_script.c, got "
            f"{len(assignments)}: {assignments}"
        )
        assert "|=" in assignments[0], (
            f"levelUpMons write should still be |=, got: {assignments[0]!r}"
        )
