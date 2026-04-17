"""Tests for dialogue tools: read_dialogue, advance_dialogue.

Save states used:
  test_npc_dialogue_active — Galactic Grunt NPC with active dialogue on screen.
  eterna_city_shiny_swinub_in_party — Overworld with no active dialogue.
  qa_lake_verity_cyrus_cutscene_done — Post-Cyrus cutscene at Lake Verity;
    script in CTX_WAITING, Barry dialogue pending B press (BUG-002 repro).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestReadDialogue:
    """Dialogue reading and advancement."""

    def test_active_dialogue_has_text(self, emu: EmulatorClient):
        """Active dialogue returns non-empty text from the Galactic Grunt."""
        load_state(emu, "test_npc_dialogue_active")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu)
        assert "text" in result, f"Missing 'text' in result: {list(result.keys())}"
        assert len(result["text"]) > 0, "Text should not be empty for active dialogue"

    def test_no_dialogue_returns_empty(self, emu: EmulatorClient):
        """No active dialogue returns placeholder text."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.dialogue import read_dialogue
        result = read_dialogue(emu)
        # read_dialogue returns "(no active text)" when nothing is on screen
        assert result["region"] == "none" or "no active" in result.get("text", ""), (
            f"Expected no-dialogue indicator, got region={result.get('region')}, text={result.get('text', '')[:50]}"
        )

    def test_advance_dialogue_completes(self, emu: EmulatorClient):
        """advance_dialogue processes full conversation and returns status."""
        load_state(emu, "test_npc_dialogue_active")
        from renegade_mcp.dialogue import advance_dialogue
        result = advance_dialogue(emu)
        assert "status" in result, f"Missing 'status' in result: {list(result.keys())}"
        assert "conversation" in result, f"Missing 'conversation' in result"
        assert len(result["conversation"]) > 0, "Should have captured dialogue text"
        assert result["status"] in ("completed", "yes_no_prompt", "multi_choice_prompt")


# ---------------------------------------------------------------------------
# BUG-002: read_dialogue bails on cutscene CTX_WAITING state
# ---------------------------------------------------------------------------

class TestBug002CutsceneDialogue:
    """advance_dialogue handles CTX_WAITING (cutscene waiting for B press)."""

    def test_lake_verity_cutscene_not_no_dialogue(self, emu: EmulatorClient):
        """Post-Cyrus cutscene at Lake Verity should find dialogue, not bail."""
        load_state(emu, "qa_lake_verity_cyrus_cutscene_done")
        emu.advance_frames(30)
        from renegade_mcp.dialogue import advance_dialogue
        result = advance_dialogue(emu)

        assert result["status"] != "no_dialogue", (
            "advance_dialogue bailed with no_dialogue on CTX_WAITING cutscene"
        )
        assert result["status"] == "completed"

    def test_barry_dialogue_collected(self, emu: EmulatorClient):
        """Barry's dialogue lines are collected from the cutscene."""
        load_state(emu, "qa_lake_verity_cyrus_cutscene_done")
        emu.advance_frames(30)
        from renegade_mcp.dialogue import advance_dialogue
        result = advance_dialogue(emu)

        conversation = result.get("conversation", [])
        all_text = " ".join(conversation).lower()
        assert "did you hear that" in all_text, (
            f"Expected Barry's 'Did you hear that' in conversation: {conversation}"
        )
