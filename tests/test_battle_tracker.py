"""Tests for battle_tracker internals: poll loop, orphan-name filter.

QA BUG-011: the battle text poll picks the memory slot with the most decoded
chars each tick. Between a macro clearing and the next macro populating, a
short name-cache buffer ("Slowpoke", "Makuhita", "Bug Catcher") briefly
becomes the top match and leaks into the log. Real narrative lines always
contain either a newline or terminal punctuation; bare name caches contain
neither, so we filter AUTO_ADVANCE entries with neither property and
<=24 chars.

Save states used:
  forest_exit_route205_north_post_cheryl — Route 205 grass, pre-Slowpoke
    encounter. Used to repro the BUG-011 orphan leak scenario.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestQaBug011OrphanNameFilter:
    """Short bare-name scratch buffers no longer leak into battle log."""

    def test_bare_species_name_is_orphan(self):
        from renegade_mcp.battle_tracker import _is_orphan_name_text
        assert _is_orphan_name_text("Slowpoke") is True
        assert _is_orphan_name_text("Makuhita") is True
        assert _is_orphan_name_text("Monferno") is True

    def test_bare_trainer_class_is_orphan(self):
        from renegade_mcp.battle_tracker import _is_orphan_name_text
        assert _is_orphan_name_text("Bug Catcher") is True
        assert _is_orphan_name_text("Ace Trainer") is True

    def test_bare_move_name_is_orphan(self):
        from renegade_mcp.battle_tracker import _is_orphan_name_text
        # The Cheryl level-up repro leaked "Water Pulse" as a bare move name.
        assert _is_orphan_name_text("Water Pulse") is True

    def test_real_lines_are_not_orphan(self):
        """Every AUTO_ADVANCE macro observed in QA logs carries a newline
        or terminal punctuation — they must never be filtered."""
        from renegade_mcp.battle_tracker import _is_orphan_name_text
        real_lines = [
            "Monferno used\nFlamethrower!",
            "The foe's Drifloon used\nAir Cutter!",
            "It's super effective!",
            "What will Monferno do?",
            "The foe's Drifloon fainted!\n",
            "Monferno gained\n258 Exp. Points!\n",
            "Vaporeon grew to\nLv. 17!\n",
            "A wild Slowpoke appeared!\n",
            "Go! Monferno!",
            "Pokémon Trainer Cheryl is\nabout to send in Wailmer.",
        ]
        for line in real_lines:
            assert _is_orphan_name_text(line) is False, (
                f"False positive — would filter real line: {line!r}"
            )

    def test_empty_and_edge_cases(self):
        from renegade_mcp.battle_tracker import _is_orphan_name_text
        # Empty string is not an orphan (no text to filter).
        assert _is_orphan_name_text("") is False
        # Very long strings (>24 chars) are not orphans even if no punctuation.
        assert _is_orphan_name_text("a" * 30) is False

    def test_slowpoke_orphan_dropped_from_seek_encounter_log(
        self, emu: EmulatorClient
    ):
        """Integration: the pre-BUG-011 repro from session 9 was a wild
        Slowpoke encounter whose first log entry was a bare "Slowpoke" before
        the "A wild Slowpoke appeared!" line. After the fix, the first entry
        must be the real appearance macro."""
        from renegade_mcp.fishing import seek_encounter

        load_state(emu, "forest_exit_route205_north_post_cheryl")

        result = seek_encounter(emu)
        assert result.get("result") == "encounter", (
            f"Expected wild encounter, got: {result!r}"
        )
        log = result["encounter"]["battle_log"]
        assert log, f"Expected non-empty battle_log, got: {log!r}"

        # The first AUTO_ADVANCE entry must not be a bare species name.
        first = log[0]["text"]
        assert "appeared" in first or "\n" in first or any(
            c in first for c in ".!?"
        ), (
            f"BUG-011 regression: first log entry looks like an orphan "
            f"bare name: {first!r}\nFull log: {log!r}"
        )
        # Positive spot-check: the real macro is still present.
        joined = "\n".join(e["text"] for e in log)
        assert "appeared" in joined, (
            f"Missing 'A wild X appeared!' macro in log: {joined!r}"
        )
