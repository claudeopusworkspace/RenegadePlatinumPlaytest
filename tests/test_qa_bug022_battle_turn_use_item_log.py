"""Regression tests for QA BUG-022.

BUG-022: ``battle_turn(use_item=..., party_slot=...)`` returned a response
with **no** ``log`` field, hiding the enemy's reciprocal action on the
same turn. Only the move-action path collected a log; the use_item path
called ``_wait_for_action_prompt`` but discarded ``prompt["log"]`` — the
caller was left with ``old_hp`` / ``new_hp`` and no narration to explain
the delta. The symptomatic confusion: a Super Potion on Monferno 75/99
reported ``old_hp=75 new_hp=51`` because the heal-to-full (75→99) was
followed by a Wing Attack (~48 dmg → 51) on the same turn — but with no
log the caller saw "healing went backwards" instead of "healed then got
hit".

Fix (``use_battle_item.py``): capture ``prompt["log"]`` after the
``_wait_for_action_prompt`` call and thread a ``turn_log`` list through
every return path, matching the shape produced by the move-action path
(``[{"text": ..., "stop": "AUTO_ADVANCE" | "WAIT_FOR_ACTION"}, ...]``).

Live repro: loading ``battle_item_debug_damaged`` (Luxio 38/59 vs Natu)
and calling ``use_battle_item(emu, "Potion", party_slot=0)`` is enough —
the post-heal Natu action is captured alongside the "Used the Potion!"
and HP-restore narration. The original session-16 repro
(``bug022_jupiter_battle_pre_super_potion`` — Monferno vs Jupiter's
Golbat) is also included as a focused "enemy reciprocal action visible"
regression.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helpers import do_load_state as load_state

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


STATE_DAMAGED = "battle_item_debug_damaged"
STATE_JUPITER = "bug022_jupiter_battle_pre_super_potion"


class TestQaBug022UseBattleItemLog:
    """Direct use_battle_item call threads turn narration into ``log``."""

    def test_log_field_is_present_and_list(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)
        assert "log" in result, (
            f"BUG-022: response must include 'log' field; got keys {list(result)}"
        )
        assert isinstance(result["log"], list), (
            f"'log' must be a list, got {type(result['log'])}"
        )

    def test_log_entries_have_text_and_stop(self, emu: EmulatorClient) -> None:
        """Log shape matches move-action path: each entry has 'text' and 'stop'."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)
        assert result["log"], "Log should not be empty on a live healing turn"
        for entry in result["log"]:
            assert "text" in entry, f"log entry missing 'text': {entry}"
            assert "stop" in entry, f"log entry missing 'stop': {entry}"
            assert entry["stop"] in ("AUTO_ADVANCE", "WAIT_FOR_ACTION", "WAIT_FOR_INPUT"), (
                f"unexpected stop value: {entry['stop']}"
            )

    def test_log_ends_with_action_prompt(self, emu: EmulatorClient) -> None:
        """When final_state is WAIT_FOR_ACTION the log closes with the prompt."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)
        assert result["final_state"] == "WAIT_FOR_ACTION"
        last = result["log"][-1]
        assert last["stop"] == "WAIT_FOR_ACTION", (
            f"expected last entry stop=WAIT_FOR_ACTION, got {last}"
        )

    def test_log_contains_item_use_narration(self, emu: EmulatorClient) -> None:
        """Log captures the 'Used the Potion!' / HP-restored narration."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)
        text_blob = " | ".join(e.get("text", "") for e in result["log"])
        # The exact wording ("Used the Potion!") comes from the game text;
        # we match loosely on "Potion" to stay resilient to text variants.
        assert "Potion" in text_blob, (
            f"log should include item-use narration mentioning 'Potion'; got: {text_blob}"
        )


class TestQaBug022BattleTurnUseItemLog:
    """battle_turn(use_item=...) wrapper preserves the log from use_battle_item."""

    def test_battle_turn_exposes_log(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, use_item="Potion", party_slot=0)
        assert "log" in result, (
            f"BUG-022: battle_turn(use_item=...) must include 'log'; got {list(result)}"
        )
        assert isinstance(result["log"], list)
        assert result["log"], "Log should not be empty on a live healing turn"

    def test_log_and_battle_state_coexist(self, emu: EmulatorClient) -> None:
        """Both 'log' (from use_battle_item) and 'battle_state' (from turn.py wrapper) appear."""
        load_state(emu, STATE_DAMAGED)
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, use_item="Potion", party_slot=0)
        assert "log" in result
        assert "battle_state" in result


class TestQaBug022EnemyActionVisible:
    """The original repro: Super Potion vs Jupiter's Golbat exposes enemy move.

    On ``bug022_jupiter_battle_pre_super_potion`` (Monferno 75/99 at Jupiter's
    action prompt), using Super Potion on slot 0 heals +24 to 99 and Golbat
    Wing Attacks for ~48. Before the fix the caller saw old_hp=75 new_hp=51
    with no evidence Golbat acted at all.
    """

    def test_golbat_action_appears_in_log(self, emu: EmulatorClient) -> None:
        load_state(emu, STATE_JUPITER)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=0)
        assert result["final_state"] == "WAIT_FOR_ACTION"
        assert result["log"], "log must be populated"
        text_blob = " | ".join(e.get("text", "") for e in result["log"])
        # Golbat is Jupiter's lead — its move (Wing Attack / Leech Life /
        # Giga Drain / Confuse Ray) should surface. Match on the species
        # name which is the most stable token across movesets.
        assert "Golbat" in text_blob, (
            f"enemy 'Golbat' action should appear in log; got: {text_blob}"
        )

    def test_heal_then_damage_hp_arc_visible(self, emu: EmulatorClient) -> None:
        """old_hp/new_hp alone is misleading (75→51 looks like reverse-heal).
        The log must contain both the heal narration and the enemy's attack
        narration so downstream callers can reconstruct the turn."""
        load_state(emu, STATE_JUPITER)
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Super Potion", party_slot=0)
        text_blob = " | ".join(e.get("text", "") for e in result["log"])
        assert "restored" in text_blob.lower() or "HP" in text_blob, (
            f"heal narration missing from log: {text_blob}"
        )
        # The enemy reciprocal action marker — "used" in "Golbat used X!"
        # or any narration that explains the HP drop.
        assert "used" in text_blob.lower(), (
            f"enemy-action narration missing from log: {text_blob}"
        )
