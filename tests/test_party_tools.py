"""Tests for party tools: read_party, format_party, reorder_party, heal_party.

State-changing UI interactions — retries for menu timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# read_party: fainted Pokemon HP (BUG-004 regression)
# ---------------------------------------------------------------------------

class TestFaintedPokemonHP:
    """Fainted Pokemon should show hp=0, not hp=-1.

    Regression: `decoded.get("ext_cur_hp", 0) or -1` treated 0 as falsy.
    """

    def test_format_party_fainted_shows_zero_hp(self, emu: EmulatorClient):
        """format_party renders hp=0 as 'HP 0/66', not 'HP ?/?'."""
        from renegade_mcp.party import format_party

        fainted_party = [{
            "slot": 0,
            "name": "Prinplup",
            "level": 22,
            "hp": 0,
            "max_hp": 66,
            "shiny": False,
            "nature": "Lax",
            "ability": "Vital Spirit",
            "status_conditions": [],
            "moves": [{"name": "Bubble Beam", "pp": 15}],
            "partial": False,
        }]
        output = format_party(fainted_party)
        assert "HP 0/66" in output, f"Expected 'HP 0/66', got: {output}"
        assert "HP ?/?" not in output, f"Should not show 'HP ?/?': {output}"

    def test_format_party_fainted_shows_fainted_status(self, emu: EmulatorClient):
        """format_party adds Fainted indicator when hp=0."""
        from renegade_mcp.party import format_party

        fainted_party = [{
            "slot": 0,
            "name": "Prinplup",
            "level": 22,
            "hp": 0,
            "max_hp": 66,
            "shiny": False,
            "nature": "Lax",
            "ability": "Vital Spirit",
            "status_conditions": [],
            "moves": [{"name": "Bubble Beam", "pp": 15}],
            "partial": False,
        }]
        output = format_party(fainted_party)
        assert "Fainted" in output, f"Expected 'Fainted' in output: {output}"

    def test_read_party_hp_never_negative(self, emu: EmulatorClient):
        """read_party should never return hp=-1 for any Pokemon."""
        load_state(emu, "test_damaged_party_overworld")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        for mon in party:
            assert mon["hp"] >= 0, (
                f"{mon['name']} has hp={mon['hp']} — should never be negative"
            )
            assert mon["max_hp"] >= 0, (
                f"{mon['name']} has max_hp={mon['max_hp']} — should never be negative"
            )
            assert mon["level"] >= 0, (
                f"{mon['name']} has level={mon['level']} — should never be negative"
            )


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
