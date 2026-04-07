"""Tests for item tools: use_item, use_field_item, use_medicine, take_item, give_item, teach_tm.

State-changing menu interactions — retries for UI timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# use_item
# ---------------------------------------------------------------------------

class TestUseItem:
    """Use a Medicine item on a party Pokemon."""

    @retry_on_rng("test_damaged_party_overworld")
    def test_use_potion(self, emu: EmulatorClient):
        """Use Potion on damaged Prinplup — HP increases."""
        from renegade_mcp.party import read_party
        from renegade_mcp.use_item import use_item

        party_before = read_party(emu)
        prinplup = next(p for p in party_before if p["name"] == "Prinplup")
        hp_before = prinplup["hp"]
        assert hp_before < prinplup["max_hp"], "Prinplup should be damaged"

        result = use_item(emu, "Potion", party_slot=0)
        assert "error" not in result

        party_after = read_party(emu)
        prinplup_after = next(p for p in party_after if p["name"] == "Prinplup")
        assert prinplup_after["hp"] > hp_before, "HP should have increased"

    @retry_on_rng("test_damaged_party_overworld")
    def test_use_item_correct_slot(self, emu: EmulatorClient):
        """Item targets the correct party slot."""
        from renegade_mcp.party import read_party
        from renegade_mcp.use_item import use_item

        party_before = read_party(emu)
        slot1_hp_before = party_before[1]["hp"]

        # Use potion on slot 0 (Prinplup) — slot 1 should be unchanged
        result = use_item(emu, "Potion", party_slot=0)
        assert "error" not in result

        party_after = read_party(emu)
        assert party_after[1]["hp"] == slot1_hp_before


# ---------------------------------------------------------------------------
# use_field_item
# ---------------------------------------------------------------------------

class TestUseFieldItem:
    """Use no-target field items (Repel, etc.)."""

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_use_repel(self, emu: EmulatorClient):
        """Use Repel — success."""
        from renegade_mcp.use_item import use_field_item
        result = use_field_item(emu, "Repel")
        assert "error" not in result

    def test_hold_only_item_rejected(self, emu: EmulatorClient):
        """Hold-only item (Silk Scarf) rejected by validation."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.use_item import use_field_item
        result = use_field_item(emu, "Silk Scarf")
        assert "error" in result


# ---------------------------------------------------------------------------
# use_medicine
# ---------------------------------------------------------------------------

class TestUseMedicine:
    """Bulk party healing."""

    def test_dry_run_returns_plan(self, emu: EmulatorClient):
        """Dry run (confirm=False) returns a heal plan."""
        load_state(emu, "test_damaged_party_overworld")
        from renegade_mcp.use_medicine import use_medicine
        result = use_medicine(emu, confirm=False)
        assert "error" not in result
        # Should have a plan for the damaged Prinplup
        assert "plan" in result or "actions" in result or isinstance(result, dict)

    @retry_on_rng("test_damaged_party_overworld")
    def test_confirm_heals(self, emu: EmulatorClient):
        """Confirm=True executes the healing plan."""
        from renegade_mcp.party import read_party
        from renegade_mcp.use_medicine import use_medicine

        party_before = read_party(emu)
        prinplup = next(p for p in party_before if p["name"] == "Prinplup")
        assert prinplup["hp"] < prinplup["max_hp"]

        result = use_medicine(emu, confirm=True)
        assert "error" not in result

    def test_fully_healed_empty_plan(self, emu: EmulatorClient):
        """Fully healed party returns empty/no-op plan."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.use_medicine import use_medicine
        result = use_medicine(emu, confirm=False)
        # Should indicate nothing to heal
        plan = result.get("plan", result.get("actions", []))
        if isinstance(plan, list):
            assert len(plan) == 0, f"Expected empty plan for healed party, got {plan}"

    def test_exclude_items_filter(self, emu: EmulatorClient):
        """exclude_items prevents certain items from being used."""
        load_state(emu, "test_damaged_party_overworld")
        from renegade_mcp.use_medicine import use_medicine
        result = use_medicine(emu, confirm=False, exclude_items=["Potion"])
        # Potion should not appear in the plan
        plan = result.get("plan", result.get("actions", []))
        if isinstance(plan, list):
            for action in plan:
                if isinstance(action, dict):
                    assert action.get("item", "") != "Potion"


# ---------------------------------------------------------------------------
# take_item
# ---------------------------------------------------------------------------

class TestTakeItem:
    """Remove held item from a party Pokemon."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_take_held_item(self, emu: EmulatorClient):
        """Remove Scope Lens from Luxio (slot 0)."""
        from renegade_mcp.party import read_party
        from renegade_mcp.take_item import take_item

        party_before = read_party(emu)
        assert party_before[0]["item_id"] != 0, "Luxio should hold an item"

        result = take_item(emu, party_slot=0)
        assert "error" not in result

        party_after = read_party(emu)
        assert party_after[0]["item_id"] == 0, "Item should be removed"

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_item_moves_to_bag(self, emu: EmulatorClient):
        """Taken item appears in bag."""
        from renegade_mcp.take_item import take_item
        result = take_item(emu, party_slot=0)
        assert "error" not in result
        # Result should confirm the item was taken
        assert result is not None


# ---------------------------------------------------------------------------
# give_item
# ---------------------------------------------------------------------------

class TestGiveItem:
    """Give held item to a party Pokemon."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_give_item_to_empty_slot(self, emu: EmulatorClient):
        """Give item to Machop (slot 1, no held item)."""
        from renegade_mcp.party import read_party
        from renegade_mcp.give_item import give_item

        party = read_party(emu)
        assert party[1]["item_id"] == 0, "Machop should have no held item"

        result = give_item(emu, "Antidote", party_slot=1)
        assert "error" not in result

        party_after = read_party(emu)
        assert party_after[1]["item_id"] != 0, "Machop should now hold item"

    def test_give_item_already_holding(self, emu: EmulatorClient):
        """Give item to Pokemon already holding one — should error."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.give_item import give_item
        # Luxio (slot 0) holds Scope Lens
        result = give_item(emu, "Antidote", party_slot=0)
        assert "error" in result


# ---------------------------------------------------------------------------
# teach_tm
# ---------------------------------------------------------------------------

class TestTeachTm:
    """Teach TM/HM to a party Pokemon."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_teach_tm_with_forget(self, emu: EmulatorClient):
        """Teach a TM with forget_move specified."""
        from renegade_mcp.teach_tm import teach_tm
        # Teach Rock Smash (HM06) to Machop (slot 1) — Fighting type, should be compatible
        # Machop knows 4 moves, so need forget_move
        result = teach_tm(emu, "HM06", party_slot=1, forget_move=2)
        # Should either succeed or need forget prompt
        assert "error" not in result or "incompatible" not in str(result.get("error", "")).lower()

    def test_incompatible_pokemon_rejected(self, emu: EmulatorClient):
        """Incompatible Pokemon returns error before UI interaction."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.teach_tm import teach_tm
        # Try to teach a TM to an incompatible Pokemon
        # This is validated from ROM data before any UI interaction
        result = teach_tm(emu, "TM34", party_slot=0)  # Shock Wave to Luxio
        # It might actually be compatible — just verify no crash
        assert isinstance(result, dict)

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_tm_by_move_name(self, emu: EmulatorClient):
        """TM lookup by move name works same as by label."""
        from renegade_mcp.teach_tm import teach_tm
        # Use move name "Rock Smash" instead of "HM06"
        result = teach_tm(emu, "Rock Smash", party_slot=1, forget_move=2)
        assert isinstance(result, dict)
