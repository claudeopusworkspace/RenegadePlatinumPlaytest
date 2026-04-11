"""Integration tests for Move Relearner and Move Deleter tools."""

from __future__ import annotations

import pytest

from helpers import do_load_state
from renegade_mcp.move_services import relearn_move, delete_move
from renegade_mcp.party import read_party


# ── Save states (E4 save, Wayne's team) ──
RELEARNER_STATE = "move_relearner_pastoria"  # map 129, Pastoria City relearner house
DELETER_STATE = "move_deleter_oreburgh"      # map 58, Oreburgh City deleter house


# ══════════════════════════════════════════════════════════════════════
#  Move Relearner
# ══════════════════════════════════════════════════════════════════════


class TestMoveRelearnerBasic:
    """Core relearn_move flow — inside the building, standard cases."""

    def test_relearn_with_forget(self, emu):
        """Relearn a move by forgetting slot 0 (4-move Pokemon)."""
        do_load_state(emu, RELEARNER_STATE)
        party = read_party(emu)
        old_move = party[0]["move_names"][0]  # Confuse Ray

        result = relearn_move(emu, "Future Sight", party_slot=0, forget_move=0)

        assert result["success"] is True
        assert result["action"] == "learned"
        assert result["move"] == "Future Sight"
        assert result["forgot"] == old_move
        assert "Future Sight" in result["new_moves"]
        assert old_move not in result["new_moves"]

    def test_relearn_with_forget_last_slot(self, emu):
        """Relearn by forgetting slot 3 (last move)."""
        do_load_state(emu, RELEARNER_STATE)
        party = read_party(emu)
        old_move = party[0]["move_names"][3]  # Will-O-Wisp

        result = relearn_move(emu, "Fire Punch", party_slot=0, forget_move=3)

        assert result["success"] is True
        assert result["action"] == "learned"
        assert result["move"] == "Fire Punch"
        assert result["forgot"] == old_move
        assert "Fire Punch" in result["new_moves"]

    def test_relearn_cancel(self, emu):
        """forget_move=-1 cancels without changing moves."""
        do_load_state(emu, RELEARNER_STATE)
        party_before = read_party(emu)
        moves_before = party_before[0]["move_names"]

        result = relearn_move(emu, "Future Sight", party_slot=0, forget_move=-1)

        assert result["success"] is True
        assert result["action"] == "skipped"
        # Moves unchanged
        party_after = read_party(emu)
        assert party_after[0]["move_names"] == moves_before

    def test_relearn_different_party_slot(self, emu):
        """Relearn for a non-lead party member (slot 1 = Swampert)."""
        do_load_state(emu, RELEARNER_STATE)
        result = relearn_move(emu, "Mud Shot", party_slot=1, forget_move=0)

        assert result["success"] is True
        assert result["action"] == "learned"
        assert result["target"] == "Swampert"
        assert "Mud Shot" in result["new_moves"]


class TestMoveRelearnerValidation:
    """Pre-check errors — bad input caught before NPC interaction."""

    def test_already_knows_move(self, emu):
        """Error when Pokemon already knows the move."""
        do_load_state(emu, RELEARNER_STATE)
        # Dusknoir knows Confuse Ray
        result = relearn_move(emu, "Confuse Ray", party_slot=0, forget_move=0)
        assert result["success"] is False
        assert "already knows" in result["error"]

    def test_missing_forget_move(self, emu):
        """Error when forget_move not provided for 4-move Pokemon."""
        do_load_state(emu, RELEARNER_STATE)
        result = relearn_move(emu, "Future Sight", party_slot=0)
        assert result["success"] is False
        assert "forget_move" in result["error"]

    def test_invalid_party_slot(self, emu):
        """Error for out-of-range party slot."""
        do_load_state(emu, RELEARNER_STATE)
        result = relearn_move(emu, "Future Sight", party_slot=9, forget_move=0)
        assert result["success"] is False
        assert "invalid" in result["error"].lower()

    def test_move_not_in_learnset(self, emu):
        """Error when target move isn't in the relearnable list."""
        do_load_state(emu, RELEARNER_STATE)
        result = relearn_move(emu, "Surf", party_slot=0, forget_move=0)
        assert result["success"] is False
        assert "not in the relearnable" in result["error"]

    def test_wrong_city(self, emu):
        """Error when not in Pastoria City."""
        do_load_state(emu, DELETER_STATE)  # Oreburgh, not Pastoria
        result = relearn_move(emu, "Future Sight", party_slot=0, forget_move=0)
        assert result["success"] is False
        assert "Pastoria" in result["error"]


# ══════════════════════════════════════════════════════════════════════
#  Move Deleter
# ══════════════════════════════════════════════════════════════════════


class TestMoveDeleterBasic:
    """Core delete_move flow — inside the building, standard cases."""

    def test_delete_first_move(self, emu):
        """Delete move in slot 0."""
        do_load_state(emu, DELETER_STATE)
        party = read_party(emu)
        target_move = party[0]["move_names"][0]

        result = delete_move(emu, target_move, party_slot=0)

        assert result["success"] is True
        assert result["action"] == "deleted"
        assert result["move"] == target_move
        assert target_move not in result["new_moves"]
        assert len(result["new_moves"]) == 3

    def test_delete_last_move_slot(self, emu):
        """Delete move in slot 3 (last position)."""
        do_load_state(emu, DELETER_STATE)
        party = read_party(emu)
        target_move = party[0]["move_names"][3]

        result = delete_move(emu, target_move, party_slot=0)

        assert result["success"] is True
        assert target_move not in result["new_moves"]

    def test_delete_different_party_slot(self, emu):
        """Delete a move from slot 1 (Swampert)."""
        do_load_state(emu, DELETER_STATE)
        party = read_party(emu)
        target_move = party[1]["move_names"][0]

        result = delete_move(emu, target_move, party_slot=1)

        assert result["success"] is True
        assert result["target"] == "Swampert"
        assert target_move not in result["new_moves"]


class TestMoveDeleterValidation:
    """Pre-check errors — bad input caught before NPC interaction."""

    def test_move_not_known(self, emu):
        """Error when Pokemon doesn't know the move."""
        do_load_state(emu, DELETER_STATE)
        result = delete_move(emu, "Splash", party_slot=0)
        assert result["success"] is False
        assert "doesn't know" in result["error"]

    def test_invalid_party_slot(self, emu):
        """Error for out-of-range party slot."""
        do_load_state(emu, DELETER_STATE)
        result = delete_move(emu, "Confuse Ray", party_slot=9)
        assert result["success"] is False
        assert "invalid" in result["error"].lower()

    def test_wrong_city(self, emu):
        """Error when not in Oreburgh City."""
        do_load_state(emu, RELEARNER_STATE)  # Pastoria, not Oreburgh
        result = delete_move(emu, "Confuse Ray", party_slot=0)
        assert result["success"] is False
        assert "Oreburgh" in result["error"]
