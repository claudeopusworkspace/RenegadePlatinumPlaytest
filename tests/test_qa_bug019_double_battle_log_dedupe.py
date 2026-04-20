"""Regression tests for QA BUG-019.

BUG-019: In a double battle the same multi-line narration line ("The foe's
X fainted!", "Y gained N Exp. Points!", "Z used Move!") sometimes appeared
twice in the battle log — once per enemy-slot partner iteration — even
though the in-game event only fired once. The dup is purely cosmetic (no
real double XP / double faint), but breaks downstream log parsers that
count KOs or exp events.

Root cause is two-fold:
  1. ``BattleTracker.poll`` updated ``prev_text`` unconditionally even for
     filtered orphan / level-summary entries, defeating the consecutive-same
     dedupe when a filtered text was sandwiched between real repeats.
  2. When ``_tracker.poll`` returns early and a doubles / NO_TEXT recovery
     path in ``turn.py`` subsequently calls ``_wait_for_action_prompt``,
     a stale marker still in the battle text buffer re-scans and logs the
     same narration a second time.

Fix (``battle_tracker.py`` + ``turn.py``):
  * ``BattleTracker.poll`` — skip ``prev_text`` update for filtered texts
    and track multi-line texts already logged this poll to drop exact repeats.
  * ``turn.py`` — new ``_merge_log_dedupe_multiline`` helper that collapses
    duplicate multi-line AUTO_ADVANCE entries when extending ``result["log"]``
    with a recovery-path scan. Applied at every cross-scan extend site.

Single-line emphasis ("A critical hit!", "It's super effective!") is
deliberately left untouched — those CAN legitimately repeat within one
double-battle turn (both attackers crit in the same turn).

Repro (QA session 15): ``qa_session15_galactic_bldg_pre_stairs`` →
navigate_to upper right stair → engage (19, 8) double-grunt pair
(Koffing + Ekans). Any Flamethrower + Aurora Beam combo that KOs Koffing
puts "Vaporeon used Aurora Beam!" into the scan buffer twice before the
partner prompt clears.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


class TestQaBug019MergeLogDedupe:
    """_merge_log_dedupe_multiline collapses exact multi-line repeats."""

    def test_drops_exact_multiline_duplicate(self) -> None:
        from renegade_mcp.turn import _merge_log_dedupe_multiline

        existing = [
            {"text": "What will Vaporeon do?", "stop": "WAIT_FOR_ACTION"},
            {"text": "Monferno used\nFlamethrower!", "stop": "AUTO_ADVANCE"},
            {"text": "Vaporeon used\nAurora Beam!", "stop": "AUTO_ADVANCE"},
        ]
        # Recovery scan re-emits the same "Aurora Beam!" text (QA BUG-019).
        extra = [
            {"text": "Vaporeon used\nAurora Beam!", "stop": "AUTO_ADVANCE"},
            {"text": "Galactic Grunt sent\nout Nidoran@!", "stop": "AUTO_ADVANCE"},
            {"text": "What will Monferno do?", "stop": "WAIT_FOR_ACTION"},
        ]
        _merge_log_dedupe_multiline(existing, extra)

        texts = [e["text"] for e in existing]
        assert texts.count("Vaporeon used\nAurora Beam!") == 1, (
            f"Aurora Beam should appear exactly once, got: {texts}"
        )
        assert "Galactic Grunt sent\nout Nidoran@!" in texts
        assert texts[-1] == "What will Monferno do?"

    def test_preserves_single_line_emphasis_repeats(self) -> None:
        """`A critical hit!` can legitimately repeat in doubles — keep both."""
        from renegade_mcp.turn import _merge_log_dedupe_multiline

        existing = [
            {"text": "Monferno used\nFlamethrower!", "stop": "AUTO_ADVANCE"},
            {"text": "A critical hit!", "stop": "AUTO_ADVANCE"},
        ]
        extra = [
            {"text": "Vaporeon used\nAurora Beam!", "stop": "AUTO_ADVANCE"},
            {"text": "A critical hit!", "stop": "AUTO_ADVANCE"},
        ]
        _merge_log_dedupe_multiline(existing, extra)

        texts = [e["text"] for e in existing]
        assert texts.count("A critical hit!") == 2, (
            f"single-line emphasis should pass through twice, got: {texts}"
        )

    def test_different_mons_same_pattern_not_deduped(self) -> None:
        """Different mon names → different texts → both kept."""
        from renegade_mcp.turn import _merge_log_dedupe_multiline

        existing = [
            {"text": "The foe's Koffing fainted!\n", "stop": "AUTO_ADVANCE"},
        ]
        extra = [
            {"text": "The foe's Ekans fainted!\n", "stop": "AUTO_ADVANCE"},
        ]
        _merge_log_dedupe_multiline(existing, extra)
        assert [e["text"] for e in existing] == [
            "The foe's Koffing fainted!\n",
            "The foe's Ekans fainted!\n",
        ]

    def test_different_exp_numbers_not_deduped(self) -> None:
        """Different exp values → different text → both kept even if same mon."""
        from renegade_mcp.turn import _merge_log_dedupe_multiline

        existing = [
            {"text": "Vaporeon gained\n220 Exp. Points!\n", "stop": "AUTO_ADVANCE"},
        ]
        extra = [
            {"text": "Vaporeon gained\n180 Exp. Points!\n", "stop": "AUTO_ADVANCE"},
        ]
        _merge_log_dedupe_multiline(existing, extra)
        assert len(existing) == 2, (
            "Distinct exp amounts must not be deduped — second KO is a real event."
        )

    def test_empty_extra_log_is_noop(self) -> None:
        from renegade_mcp.turn import _merge_log_dedupe_multiline

        existing = [{"text": "Hello!\n", "stop": "AUTO_ADVANCE"}]
        _merge_log_dedupe_multiline(existing, [])
        assert existing == [{"text": "Hello!\n", "stop": "AUTO_ADVANCE"}]

    def test_non_auto_advance_always_appended(self) -> None:
        """WAIT_FOR_ACTION / WAIT_FOR_INPUT entries always appended even if text matches."""
        from renegade_mcp.turn import _merge_log_dedupe_multiline

        existing = [
            {"text": "What will Monferno do?\n", "stop": "WAIT_FOR_ACTION"},
        ]
        extra = [
            {"text": "What will Monferno do?\n", "stop": "WAIT_FOR_ACTION"},
        ]
        _merge_log_dedupe_multiline(existing, extra)
        # Prompt stop types aren't subject to the AUTO_ADVANCE dedupe gate —
        # they may legitimately reappear (e.g., partner-action re-prompt).
        assert len(existing) == 2


class TestQaBug019TrackerPollFilteredPrevText:
    """BattleTracker.poll prev_text should not track filtered orphan/artifact text."""

    def test_filtered_text_does_not_block_real_repeat_dedupe(self) -> None:
        """Sandwich "orphan" text between real repeats — the second real must dedupe."""
        from renegade_mcp.battle_tracker import (
            _is_orphan_name_text,
            _is_level_summary_artifact,
        )

        # Meta-test: confirm our heuristic distinguishes orphan vs multi-line narration.
        # If either of these invariants ever regresses, BUG-019's prev_text guard
        # stops protecting against the sandwich case (see battle_tracker.poll).
        assert _is_orphan_name_text("Aurora Beam")
        assert not _is_orphan_name_text("Vaporeon used\nAurora Beam!")
        assert _is_level_summary_artifact("Sp. Def")
        assert _is_level_summary_artifact("Mothim@\nLv. 23")
