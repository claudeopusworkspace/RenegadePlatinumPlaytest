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
        """Grind 1 encounter — stops after iterations=1."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=0, iterations=1)
        assert result["stop_reason"] in (
            "iterations", "fainted", "move_learn", "pp_depleted", "shiny",
        )
        if result["stop_reason"] == "iterations":
            assert result["battles_fought"] == 1
            assert len(result["encounters"]) == 1

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_iterations_multiple(self, emu: EmulatorClient):
        """Grind 3 encounters — encounter log has up to 3 entries."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=0, iterations=3)
        if result["stop_reason"] == "iterations":
            assert result["battles_fought"] == 3
            assert len(result["encounters"]) == 3
        else:
            # Early stop is acceptable
            assert result["stop_reason"] in (
                "fainted", "move_learn", "pp_depleted", "shiny",
            )

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_run_mode(self, emu: EmulatorClient):
        """Run mode (no move_index) — seeks and flees."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, iterations=1)  # No move_index = run mode
        assert result["stop_reason"] in (
            "iterations", "shiny", "seek_failed", "unexpected",
        )
        if result["stop_reason"] == "iterations":
            assert len(result["encounters"]) >= 1


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
            assert any(e["species"] == "Swinub" for e in result["encounters"])
        else:
            # May not find Swinub in 20 iterations — that's OK
            assert result["stop_reason"] in (
                "iterations", "fainted", "shiny", "seek_failed",
            )


class TestAutoGrindResult:
    """Result structure validation."""

    @retry_on_rng("route216_grass_swinub_hunt")
    def test_party_in_result(self, emu: EmulatorClient):
        """Result includes slot0 party data."""
        from renegade_mcp.auto_grind import auto_grind
        result = auto_grind(emu, move_index=0, iterations=1)
        assert "slot0" in result
        assert result["slot0"]["name"], "slot0 should have a Pokemon name"
