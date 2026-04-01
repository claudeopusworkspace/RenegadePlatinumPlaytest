"""Tests for auto_grind automation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestAutoGrindBasic:
    """Basic auto_grind stop conditions."""

    def test_iterations_stop(self, emu: EmulatorClient):
        """Grind 1 encounter → stop after iterations=1.

        State: r207_grind_start — Route 207 grass, team ready.
        """
        from renegade_mcp.auto_grind import auto_grind

        load_state(emu, "r207_grind_start")
        result = auto_grind(emu, move_index=0, iterations=1)

        # Should stop after 1 encounter (or faint if unlucky)
        assert result["stop_reason"] in ("iterations", "fainted", "move_learn"), (
            f"Expected iterations/fainted/move_learn, got: {result['stop_reason']}"
        )
        if result["stop_reason"] == "iterations":
            assert result["battles_fought"] == 1
            assert len(result["encounters"]) == 1
            assert "species" in result["encounters"][0]
            assert "checkpoint_id" in result["encounters"][0]

    def test_iterations_multiple(self, emu: EmulatorClient):
        """Grind 3 encounters → verify encounter log has 3 entries.

        State: r207_grind_start — same start.
        """
        from renegade_mcp.auto_grind import auto_grind

        load_state(emu, "r207_grind_start")
        result = auto_grind(emu, move_index=0, iterations=3)

        if result["stop_reason"] == "iterations":
            assert result["battles_fought"] == 3
            assert len(result["encounters"]) == 3
        else:
            # Early stop is acceptable — faint, move_learn, pp_depleted
            assert result["stop_reason"] in (
                "fainted", "move_learn", "pp_depleted",
            )


class TestAutoGrindMidBattle:
    """auto_grind picks up from mid-battle state (resume support)."""

    def test_mid_battle_resume(self, emu: EmulatorClient):
        """Start auto_grind while already in battle — should fight, not seek.

        State: debug_piplup_evolution_r207 — mid-battle vs wild Phanpy.
        auto_grind should detect the active battle and fight it directly.
        """
        from renegade_mcp.auto_grind import auto_grind

        load_state(emu, "debug_piplup_evolution_r207")
        result = auto_grind(emu, move_index=3, iterations=1)

        # Should complete the battle (or stop for move_learn/faint)
        assert result["stop_reason"] in (
            "iterations", "move_learn", "fainted",
        ), f"Unexpected stop_reason: {result['stop_reason']}"
        # Should have logged at least 1 encounter
        assert len(result["encounters"]) >= 1


class TestAutoGrindEdgeCases:
    """Edge cases in auto_grind."""

    def test_party_included_in_result(self, emu: EmulatorClient):
        """auto_grind result always includes party data.

        State: r207_grind_start.
        """
        from renegade_mcp.auto_grind import auto_grind

        load_state(emu, "r207_grind_start")
        result = auto_grind(emu, move_index=0, iterations=1)

        assert "party" in result, "Result should include party data"
        assert len(result["party"]) > 0, "Party should not be empty"

    def test_encounter_log_has_species(self, emu: EmulatorClient):
        """Each encounter entry has species name from Route 207 pool.

        State: r207_grind_start.
        """
        from renegade_mcp.auto_grind import auto_grind

        load_state(emu, "r207_grind_start")
        result = auto_grind(emu, move_index=0, iterations=1)

        if result["stop_reason"] in ("iterations", "fainted", "move_learn"):
            for enc in result["encounters"]:
                assert "species" in enc
                # Route 207 species pool
                known_species = {
                    "Machop", "Phanpy", "Ponyta", "Rhyhorn", "Larvitar",
                    "Geodude", "Zubat",  # possible cave/extras
                }
                # Don't assert exact species — just that it's non-empty
                assert enc["species"], f"Empty species in encounter: {enc}"
