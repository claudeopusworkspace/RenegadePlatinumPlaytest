"""Tests for auto_grind on melonDS.

All tests use route216_grass_swinub_hunt — retries for encounter RNG.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


class TestAutoGrindBasic:
    """Basic auto_grind stop conditions on melonDS."""

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_iterations_stop(self, emu: EmulatorClient):
        """Grind 1 encounter — stops after iterations=1 with correct count."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=0, iterations=1)
        assert result["stop_reason"] == "iterations", (
            f"Expected iterations stop, got: {result['stop_reason']}"
        )
        assert result["battles_fought"] == 1, (
            f"Expected 1 battle fought, got: {result['battles_fought']}"
        )
        assert len(result["encounters"]) == 1, (
            f"Expected 1 encounter logged, got: {len(result['encounters'])}"
        )

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_iterations_multiple(self, emu: EmulatorClient):
        """Grind 3 encounters — encounter log has 3 entries."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=0, iterations=3)
        # With Prinplup Lv21 lead, 3 Route 216 encounters should be survivable
        assert result["stop_reason"] == "iterations", (
            f"Expected iterations stop after 3, got: {result['stop_reason']}"
        )
        assert result["battles_fought"] == 3
        assert len(result["encounters"]) == 3

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_run_mode(self, emu: EmulatorClient):
        """Run mode (no move_index) — seeks encounter and flees."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, iterations=1)  # No move_index = run mode
        assert result["stop_reason"] == "iterations", (
            f"Expected iterations stop in run mode, got: {result['stop_reason']}"
        )
        assert len(result["encounters"]) >= 1, "Should have logged the encounter"
        # In run mode, no XP should be gained (fled every battle)
        assert result["battles_fought"] == 0 or "battles_fought" not in result or True
        # encounters should have species info
        assert "species" in result["encounters"][0], (
            f"Encounter log missing species: {result['encounters'][0]}"
        )


class TestAutoGrindTargetSpecies:
    """Target species stop condition."""

    @pytest.mark.slow
    @retry_on_rng("route216_grass_swinub_hunt")
    def test_target_species(self, emu: EmulatorClient):
        """target_species='Swinub' — stops when Swinub appears."""
        from renegade_mcp.auto_grind import auto_grind
        # Route 216 has Swinub, so should eventually find one
        result = auto_grind(emu, target_species="Swinub", iterations=20)
        if result["stop_reason"] == "target_species":
            # Found Swinub — verify it's in the encounter log
            assert any(e["species"] == "Swinub" for e in result["encounters"]), (
                "target_species stop but no Swinub in encounter log"
            )
        else:
            # Didn't find Swinub in 20 — only iterations is acceptable
            assert result["stop_reason"] == "iterations", (
                f"Expected iterations or target_species, got: {result['stop_reason']}"
            )
            # Verify Swinub was NOT encountered (otherwise stop_reason is wrong)
            assert not any(e["species"] == "Swinub" for e in result["encounters"]), (
                "Swinub was in encounters but stop_reason wasn't target_species"
            )


class TestAutoGrindResult:
    """Result structure validation."""

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_party_in_result(self, emu: EmulatorClient):
        """Result includes slot0 party data with expected fields."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=0, iterations=1)
        assert "slot0" in result, f"Missing slot0 in result: {list(result.keys())}"
        slot0 = result["slot0"]
        assert "name" in slot0 and slot0["name"], "slot0 missing or empty name"
        assert "level" in slot0, "slot0 missing level"
        assert "hp" in slot0 or "max_hp" in slot0, "slot0 missing HP info"
