"""Tests for pure data tools: type_matchup, move_info, decode_rom_message, search_rom_messages.

These tools are deterministic ROM lookups — no emulator state needed, no retries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


# ---------------------------------------------------------------------------
# type_matchup
# ---------------------------------------------------------------------------

class TestTypeMatchup:
    """Type effectiveness calculations."""

    def test_super_effective(self, emu: EmulatorClient):
        """Fire vs Grass = 2x."""
        from renegade_mcp.type_chart import effectiveness
        assert effectiveness("Fire", "Grass") == 2.0

    def test_double_super_effective(self, emu: EmulatorClient):
        """Fire vs Grass/Steel = 4x."""
        from renegade_mcp.type_chart import effectiveness
        assert effectiveness("Fire", "Grass", "Steel") == 4.0

    def test_immune(self, emu: EmulatorClient):
        """Normal vs Ghost = 0x."""
        from renegade_mcp.type_chart import effectiveness
        assert effectiveness("Normal", "Ghost") == 0.0

    def test_not_very_effective(self, emu: EmulatorClient):
        """Fire vs Water = 0.5x."""
        from renegade_mcp.type_chart import effectiveness
        assert effectiveness("Fire", "Water") == 0.5

    def test_neutral(self, emu: EmulatorClient):
        """Normal vs Normal = 1x."""
        from renegade_mcp.type_chart import effectiveness
        assert effectiveness("Normal", "Normal") == 1.0

    def test_by_move_name(self, emu: EmulatorClient):
        """Spark is Electric → vs Water/Flying = 4x."""
        from renegade_mcp.data import move_data, move_names
        from renegade_mcp.type_chart import effectiveness

        mv_names = move_names()
        spark_id = next(mid for mid, name in mv_names.items() if name == "Spark")
        spark_type = move_data()[spark_id]["type"]
        assert spark_type == "Electric"
        assert effectiveness(spark_type, "Water", "Flying") == 4.0

    def test_invalid_type(self, emu: EmulatorClient):
        """Invalid type is not in VALID_TYPES."""
        from renegade_mcp.type_chart import VALID_TYPES, _normalize_type
        assert _normalize_type("Plasma") is None
        assert "Fire" in VALID_TYPES


# ---------------------------------------------------------------------------
# move_info
# ---------------------------------------------------------------------------

class TestMoveInfo:
    """Move data lookups from ROM."""

    def _lookup(self, name: str) -> dict:
        """Helper: find move by name in move_data."""
        from renegade_mcp.data import move_data, move_names
        mv_names = move_names()
        name_lower = name.strip().lower()
        for mid, mname in mv_names.items():
            if mname.lower() == name_lower:
                return move_data().get(mid, {})
        return {}

    def test_physical_move(self, emu: EmulatorClient):
        """Tackle: Normal, Physical, 40 power."""
        result = self._lookup("Tackle")
        assert result["name"] == "Tackle"
        assert result["type"] == "Normal"
        assert result["class"] == "Physical"
        assert result["power"] == 40
        assert result["accuracy"] == 100
        assert result["pp"] > 0

    def test_special_move(self, emu: EmulatorClient):
        """Bubble Beam: Water, Special, 75 power."""
        result = self._lookup("Bubble Beam")
        assert result["name"] == "Bubble Beam"
        assert result["type"] == "Water"
        assert result["class"] == "Special"
        assert result["power"] == 75

    def test_status_move(self, emu: EmulatorClient):
        """Growl: Normal, Status, no power."""
        result = self._lookup("Growl")
        assert result["class"] == "Status"
        assert result["power"] is None or result["power"] == 0

    def test_priority_move(self, emu: EmulatorClient):
        """Quick Attack has positive priority."""
        result = self._lookup("Quick Attack")
        assert result["priority"] > 0

    def test_invalid_move(self, emu: EmulatorClient):
        """Unknown move name returns empty dict."""
        result = self._lookup("Definitely Not A Move")
        assert result == {}


# ---------------------------------------------------------------------------
# decode_rom_message
# ---------------------------------------------------------------------------

class TestDecodeRomMessage:
    """ROM message file decoding."""

    def test_species_names(self, emu: EmulatorClient):
        """File 0412 (species) returns recognizable Pokemon names."""
        from renegade_mcp.rom_messages import decode_file
        results = decode_file(412)
        assert len(results) > 0
        names = [s["text"] for s in results]
        assert "Bulbasaur" in names

    def test_invalid_file_index(self, emu: EmulatorClient):
        """Non-existent file index returns empty list."""
        from renegade_mcp.rom_messages import decode_file
        results = decode_file(99999)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# search_rom_messages
# ---------------------------------------------------------------------------

class TestSearchRomMessages:
    """ROM message search."""

    def test_search_pikachu(self, emu: EmulatorClient):
        """Searching 'Pikachu' finds results."""
        from renegade_mcp.rom_messages import search_all
        matches = search_all("Pikachu")
        assert len(matches) > 0
        texts = [m["text"] for m in matches]
        assert any("Pikachu" in t for t in texts)

    def test_search_no_results(self, emu: EmulatorClient):
        """Gibberish search returns zero matches."""
        from renegade_mcp.rom_messages import search_all
        matches = search_all("xyzzy12345notaword")
        assert len(matches) == 0
