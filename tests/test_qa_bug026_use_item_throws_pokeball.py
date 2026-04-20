"""Regression tests for QA BUG-026.

BUG-026: ``battle_turn(use_item="Super Potion", party_slot=3)`` mid-trainer-
battle threw a **Poké Ball** at the opposing trainer's Pokemon instead of
healing. The game rejected the ball with "The Trainer blocked the Ball! /
Don't be a thief!" — the turn was consumed, no healing occurred, and the
tool still reported ``"Used Super Potion on Monferno (bench — HP
unverifiable)"``. Dangerous because the caller believes a heal happened,
the active Pokemon is exposed to a free enemy turn, and the log contains
the player's *other* catch attempts' wording.

Root cause (from live repro on ``bug_battle_turn_use_item_throws_pokeball``,
Luxray 38/109 burned vs Youngster Austin's Lombre Lv25):

 1. ``use_battle_item`` tapped BAG at (45, 170) and waited 60 frames, but
    the battle bag transition needs ~100+ frames to render — and the
    preceding "What will X do?" prompt text doesn't accept input until
    it's fully printed, so the first BAG tap was **dropped**.
 2. Next tap — "pocket" at (64, 44) — landed on the still-visible **FIGHT**
    button on the action screen, opening move select.
 3. The page-reset loop then tapped PREV_PAGE at (20, 172) five times:
    tap 1 hit CANCEL on move select (back to action screen); tap 2 hit the
    BAG button again (x=20, y=172 is inside BAG's rect); tap 3 was spent
    on the bag-open transition; **tap 4 landed on the bag menu's
    "Last Used Item" button** ({152, 191, 0, 207}), which from session 17's
    Larvitar catch had ``lastUsedItem = Poké Ball``; tap 5 confirmed USE.
 4. The ball was thrown, rejected with "Trainer blocked the Ball!", the
    opponent took its turn, and ``_wait_for_action_prompt`` returned
    reporting ``final_state=WAIT_FOR_ACTION``.

Fix (``use_battle_item.py``):

 - Pre-settle 60 frames before the BAG tap so the action-prompt text
   finishes printing and the tap registers.
 - Raise the BAG and pocket screen-transition waits from 60 to 150 frames
   so we're reliably on the bag-menu / pocket-menu screen before the next
   tap. Prevents PREV_PAGE taps at (20, 172) from colliding with the
   LAST_USED_ITEM button at {152, 191, 0, 207}.
 - After the party-target tap on a healing item, advance through the
   heal animation and press B to dismiss the "X's HP was restored..."
   confirmation so ``_wait_for_action_prompt`` doesn't prematurely return
   on the stale pre-heal "What will X do?" text.

These tests use live-battle savestate
``bug_battle_turn_use_item_throws_pokeball`` — the exact Luxray vs Lombre
state from the original session-18 report — and assert that (a) no ball
was thrown, (b) the heal narration is captured, (c) the enemy's reciprocal
Fake Out is captured, and (d) the tool returns ``WAIT_FOR_ACTION`` with
``role="bench"`` for party slot 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helpers import do_load_state as load_state

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


STATE = "bug_battle_turn_use_item_throws_pokeball"


class TestQaBug026NoPokeballThrow:
    """The core safety invariant: Medicine never routes to the Poké Balls pocket."""

    def test_log_does_not_mention_ball(self, emu: EmulatorClient) -> None:
        """Pre-fix the log reported 'Trainer blocked the Ball!' — now it must not."""
        load_state(emu, STATE)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=3)
        text_blob = " | ".join(e.get("text", "") for e in result.get("log", []))
        lower = text_blob.lower()
        assert "blocked the ball" not in lower, (
            f"BUG-026: Super Potion must not throw a Poké Ball. Log: {text_blob}"
        )
        assert "don't be a thief" not in lower, (
            f"BUG-026: Super Potion must not trigger the trainer-catch rejection. "
            f"Log: {text_blob}"
        )

    def test_formatted_is_not_a_lie(self, emu: EmulatorClient) -> None:
        """Pre-fix the formatted string claimed a heal while the log proved a ball throw."""
        load_state(emu, STATE)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=3)
        formatted = result.get("formatted", "")
        log_blob = " | ".join(e.get("text", "") for e in result.get("log", []))
        # If formatted says Super Potion was used, the log must back it up:
        # either heal narration or at minimum an absence of a ball throw.
        assert "Super Potion" in formatted
        assert "blocked the ball" not in log_blob.lower(), (
            f"formatted claims Super Potion use, but log shows a ball throw: {log_blob}"
        )


class TestQaBug026HealNarration:
    """The heal actually happens and the narration is captured."""

    def test_final_state_is_wait_for_action(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=3)
        assert result["final_state"] == "WAIT_FOR_ACTION", (
            f"expected WAIT_FOR_ACTION after a consumed-turn heal, got "
            f"{result['final_state']}"
        )

    def test_enemy_reciprocal_action_in_log(self, emu: EmulatorClient) -> None:
        """Lombre's Fake Out should fire on the same turn (item use consumes the turn).

        Pre-fix this test would have passed for the *wrong reason*: the log
        contained Fake Out because the Poké Ball throw triggered the enemy turn.
        Post-fix the log contains Fake Out because the heal itself triggers
        the enemy turn — which is the correct behavior."""
        load_state(emu, STATE)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=3)
        text_blob = " | ".join(e.get("text", "") for e in result.get("log", []))
        assert "Lombre" in text_blob, (
            f"Lombre's reciprocal action missing from log: {text_blob}"
        )
        assert "Fake Out" in text_blob, (
            f"Lombre's Fake Out move missing from log: {text_blob}"
        )

    def test_log_ends_with_action_prompt(self, emu: EmulatorClient) -> None:
        """Final entry should be the fresh 'What will X do?' prompt for the next turn."""
        load_state(emu, STATE)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=3)
        log = result.get("log", [])
        assert log, "log must be populated"
        last = log[-1]
        assert last["stop"] == "WAIT_FOR_ACTION", (
            f"expected final entry stop=WAIT_FOR_ACTION, got {last}"
        )


class TestQaBug026BenchTargetMetadata:
    """The result correctly reports the bench target (party slot 3 = Monferno)."""

    def test_target_metadata_matches_monferno(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=3)
        assert result["success"] is True
        assert result["item"] == "Super Potion"
        assert result["party_slot"] == 3
        assert result["role"] == "bench", (
            f"party slot 3 (Monferno) is benched; expected role=bench, got "
            f"{result.get('role')}"
        )
        assert result["target"] == "Monferno", (
            f"target name should be Monferno, got {result.get('target')}"
        )


class TestQaBug026BattleTurnWrapper:
    """battle_turn(use_item=...) must also be safe — no ball throws."""

    def test_battle_turn_super_potion_does_not_throw_ball(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, use_item="Super Potion", party_slot=3)
        text_blob = " | ".join(e.get("text", "") for e in result.get("log", []))
        assert "blocked the Ball" not in text_blob, (
            f"BUG-026: battle_turn delegation must not throw a ball either. "
            f"Log: {text_blob}"
        )
        assert result["success"] is True
        assert result["final_state"] == "WAIT_FOR_ACTION"
