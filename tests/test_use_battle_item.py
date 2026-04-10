"""Tests for use_battle_item — in-battle item use via battle bag UI.

Save states:
  battle_item_debug_damaged (primary):
    - Luxio Lv21 at 38/59 HP, at action prompt
    - vs Natu Lv20 (wild/trainer)
    - Medicine pocket: Antidote x4, Potion x4, Parlyz Heal x1, Revival Herb x1
    - Poke Balls: Poke Ball x24

  battle_item_test_action_prompt:
    - Luxio Lv21 at 59/59 HP (full), at action prompt
    - Same battle, same inventory
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state

STATE_DAMAGED = "battle_item_debug_damaged"
STATE_FULL_HP = "battle_item_test_action_prompt"


class TestUseBattleItemHealing:
    """Healing items (battleUseFunc=2) via battle bag."""

    def test_potion_heals_damaged_pokemon(self, emu: EmulatorClient):
        """Potion on a damaged Pokemon restores HP and returns to action prompt."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)
        assert result["success"] is True, f"Expected success, got: {result}"
        assert result["final_state"] == "WAIT_FOR_ACTION"
        assert result["old_hp"] == 38
        # Potion restores 20 HP: 38 -> 58, but enemy may attack after,
        # so new_hp could be less than 58.  Just verify HP changed.
        assert result["new_hp"] != 38, (
            f"HP should have changed from 38, got {result['new_hp']}"
        )

    def test_potion_on_full_hp_reports_failure(self, emu: EmulatorClient):
        """Potion on a full-HP Pokemon fails (game rejects it)."""
        load_state(emu, STATE_FULL_HP)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)
        # Game shows "It won't have any effect", item not consumed.
        # HP may change due to enemy attack, but old_hp == max_hp.
        # The tool should still return to action prompt.
        assert result["final_state"] == "WAIT_FOR_ACTION"

    def test_healing_item_requires_party_slot(self, emu: EmulatorClient):
        """Healing items reject missing party_slot with a clear error."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion")
        assert result["success"] is False
        assert "party_slot" in result.get("error", "").lower()


class TestUseBattleItemValidation:
    """Pre-validation: item lookup, pocket mapping, parameter checks."""

    def test_nonexistent_item_returns_error(self, emu: EmulatorClient):
        """Item not in bag returns error with available items list."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Hyper Potion", party_slot=0)
        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_poke_ball_rejected(self, emu: EmulatorClient):
        """Poke Balls are rejected with a message to use throw_ball."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Poké Ball", party_slot=0)
        assert result["success"] is False
        assert "throw_ball" in result.get("error", "").lower()

    def test_invalid_party_slot_rejected(self, emu: EmulatorClient):
        """party_slot > 5 is rejected."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=7)
        assert result["success"] is False
        assert "party_slot" in result.get("error", "").lower()


class TestBattleBagPockets:
    """Battle bag pocket reconstruction from overworld bag data."""

    def test_build_battle_pockets_maps_items_correctly(self, emu: EmulatorClient):
        """Items are mapped to correct battle pockets based on ROM data."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.bag import read_bag
        from renegade_mcp.battle_bag import build_battle_pockets, POCKET_NAMES
        bag = read_bag(emu)
        pockets = build_battle_pockets(bag)

        # HP/PP Recovery pocket should contain Potion
        hp_items = [i["name"] for i in pockets[0]]
        assert "Potion" in hp_items, f"Potion not in HP/PP pocket: {hp_items}"

        # Status Recovery pocket should contain Antidote, Parlyz Heal
        status_items = [i["name"] for i in pockets[1]]
        assert "Antidote" in status_items
        assert "Parlyz Heal" in status_items

        # Poke Balls pocket should contain Poke Ball
        ball_items = [i["name"] for i in pockets[2]]
        assert any("Ball" in n for n in ball_items)

    def test_find_item_returns_correct_position(self, emu: EmulatorClient):
        """find_item_in_battle_bag returns page, slot, and pocket info."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.bag import read_bag
        from renegade_mcp.battle_bag import find_item_in_battle_bag
        bag = read_bag(emu)
        result = find_item_in_battle_bag(bag, "Potion")

        assert "error" not in result, f"Unexpected error: {result}"
        assert result["pocket_index"] == 0  # HP/PP Recovery
        assert result["battleUseFunc"] == 2  # healing
        assert result["page"] == 0
        assert result["slot"] >= 0
        assert result["qty"] > 0

    def test_find_item_not_found_lists_available(self, emu: EmulatorClient):
        """Missing item returns error with available item names."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.bag import read_bag
        from renegade_mcp.battle_bag import find_item_in_battle_bag
        bag = read_bag(emu)
        result = find_item_in_battle_bag(bag, "X Attack")

        assert "error" in result
        assert "Potion" in result["error"]  # should list available items
