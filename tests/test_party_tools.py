"""Tests for party management tools: reorder_party, heal_party.

State-changing UI interactions — retries for menu timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# reorder_party
# ---------------------------------------------------------------------------

class TestReorderParty:
    """Swap party Pokemon via pause menu."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_swap_slots(self, emu: EmulatorClient):
        """Swap slot 0 (Luxio) and slot 2 (Grotle) — species move."""
        from renegade_mcp.party import read_party
        from renegade_mcp.reorder_party import reorder_party

        party_before = read_party(emu)
        name_0 = party_before[0]["name"]
        name_2 = party_before[2]["name"]

        result = reorder_party(emu, 0, 2)
        assert "error" not in result

        party_after = read_party(emu)
        assert party_after[0]["name"] == name_2, (
            f"Slot 0 should be {name_2}, got {party_after[0]['name']}"
        )
        assert party_after[2]["name"] == name_0, (
            f"Slot 2 should be {name_0}, got {party_after[2]['name']}"
        )

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_swap_preserves_data(self, emu: EmulatorClient):
        """Swap preserves Pokemon data (level, moves, etc.)."""
        from renegade_mcp.party import read_party
        from renegade_mcp.reorder_party import reorder_party

        party_before = read_party(emu)
        level_0 = party_before[0]["level"]
        moves_0 = party_before[0]["move_names"]

        reorder_party(emu, 0, 2)

        party_after = read_party(emu)
        # Old slot 0 data should now be at slot 2
        assert party_after[2]["level"] == level_0
        assert party_after[2]["move_names"] == moves_0


# ---------------------------------------------------------------------------
# heal_party
# ---------------------------------------------------------------------------

class TestHealParty:
    """Heal at Pokemon Center."""

    @retry_on_rng("debug_heal_party_dialogue_stuck")
    def test_heal_damaged_party(self, emu: EmulatorClient):
        """Heal party at Pokemon Center — completes without error."""
        from renegade_mcp.heal_party import heal_party

        result = heal_party(emu)
        assert "error" not in result

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_heal_already_healed(self, emu: EmulatorClient):
        """Healing already-healed party completes without error."""
        from renegade_mcp.heal_party import heal_party
        result = heal_party(emu)
        assert "error" not in result

    @retry_on_rng("debug_heal_party_dialogue_stuck")
    def test_heal_from_inside_pc(self, emu: EmulatorClient):
        """Heal from inside Pokemon Center building."""
        from renegade_mcp.heal_party import heal_party
        result = heal_party(emu)
        assert "error" not in result
