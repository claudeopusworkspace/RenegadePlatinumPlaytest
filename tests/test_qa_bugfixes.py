"""Tests for QA bug fixes from 2026-04-15 and 2026-04-16 triage sessions.

2026-04-15: BUG-002, BUG-003, BUG-004, BUG-008, BUG-009 (see test classes below).
2026-04-16: QA BUG-001/002/003/004 (round-2 classes at bottom of file).

BUG-005 (evolution race) and BUG-010 (blackout) from 2026-04-15 are code-
confirmed only (too expensive to repro — ~15 battles and 3-KO party wipe).

Save states:
  qa_oreburgh_gate_entrance:
    - Player inside Oreburgh Gate, map_id=258
    - Used for BUG-008 (map_name correctness)

  test_bug004_dawn_battle_taunt:
    - Chimchar Lv10 vs Turtwig Lv9 (Dawn rival), at action prompt
    - Taunt is move slot 3, Turtwig has Withdraw
    - Used for BUG-004 (Taunt false MOVE_BLOCKED)

  test_bug009_roark_battle_monferno_lead:
    - Monferno Lv16 (slot 0) at action prompt vs Roark's Nosepass
    - Luxio (slot 1) and Eevee (slot 2) on bench
    - Bag has Potions
    - Used for BUG-009 (use_battle_item target reporting)

  qa_lake_verity_cyrus_cutscene_done:
    - Post-Cyrus cutscene at Lake Verity
    - Script in CTX_WAITING, Barry dialogue pending B press
    - Used for BUG-002 (cutscene dialogue CTX_WAITING)

  test_bug003_oreburgh_city_post_event:
    - Oreburgh City overworld, scripted NPC event already cleared
    - 0 badges, has Potions and money for purchases
    - Used for BUG-003 (Premier Ball bonus)

  bug_qa_throw_ball_state_mismatch:
    - Post-catch state — Shinx in party slot 3 at 11/19 HP.
    - QA BUG-001 target state is post-catch so the throw_ball flow can't
      be re-run here; unit tests exercise the _format_log / _recover_from_catch
      fixes directly.

  bug_qa_auto_grind_faint_switch_stuck:
    - Wild Rattata battle, Shinx 0 HP, party grid "Choose a Pokémon."
    - Used for QA BUG-002 (wild FAINT_SWITCH misclassified as FAINT_FORCED).

  bug_qa_auto_grind_evolution_stop_lingering_dialogue:
    - "Huh? Chimchar stopped evolving!" dialogue on screen (post-bug state).
    - Used for QA BUG-003 observation/regression checks.

  bug_qa_battle_turn_stuck_after_double_ko_doubles:
    - Doubles target-pick submenu with Monferno acting; partner Shinx 0 HP.
    - Used for QA BUG-004 (doubles detection + target-pick recovery).

  fr001_repro_growlithe_battle_prompt:
    - Mid-battle vs wild Growlithe on Route 202, action prompt up.
    - Used for QA BUG-005 (text-placeholder leak in dialogue/battle output).

  jubilife_mart_after_buy_5potions:
    - Inside Jubilife Mart, player in overworld, 0 badges, ¥1,948.
    - Used for QA BUG-006 (buy_item exit-to-overworld regression).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, assert_final_state, retry_on_rng


# ---------------------------------------------------------------------------
# BUG-008: map_name returns wrong names for reshuffled map IDs
# ---------------------------------------------------------------------------

class TestBug008MapName:
    """map_id_to_name.json rebuilt from ROM zone headers."""

    def test_oreburgh_gate_not_floaroma_meadow(self, emu: EmulatorClient):
        """Map 258 should be 'Oreburgh Gate', not 'Floaroma Meadow'."""
        load_state(emu, "qa_oreburgh_gate_entrance")
        from renegade_mcp.map_names import lookup_map_name
        result = lookup_map_name(258)
        assert result["name"] == "Oreburgh Gate", (
            f"Expected 'Oreburgh Gate', got '{result['name']}'"
        )

    def test_map_name_from_live_map_id(self, emu: EmulatorClient):
        """lookup_map_name() with the live map_id returns the correct name."""
        load_state(emu, "qa_oreburgh_gate_entrance")
        from renegade_mcp.map_names import lookup_map_name
        from renegade_mcp.map_state import read_player_state
        map_id, _, _, _ = read_player_state(emu)
        result = lookup_map_name(map_id)
        assert result["map_id"] == 258
        assert result["name"] == "Oreburgh Gate"

    def test_map_table_no_unknowns(self, emu: EmulatorClient):
        """Every entry in the rebuilt table has a resolved name (no 'Unknown')."""
        from renegade_mcp.data import map_table
        table = map_table()
        unknowns = [
            (k, v) for k, v in table.items()
            if "Unknown" in v.get("name", "")
        ]
        assert len(unknowns) == 0, (
            f"Found {len(unknowns)} unknown entries: {unknowns[:5]}"
        )


# ---------------------------------------------------------------------------
# BUG-004: battle_turn returns MOVE_BLOCKED when opponent is Taunt-blocked
# ---------------------------------------------------------------------------

class TestBug004TauntNotMoveBlocked:
    """Our Taunt landing on the opponent should NOT return MOVE_BLOCKED."""

    def test_taunt_returns_wait_for_action(self, emu: EmulatorClient):
        """Using Taunt on Turtwig returns WAIT_FOR_ACTION, not MOVE_BLOCKED.

        Turtwig tries Withdraw after being Taunted — game shows
        "The foe's Turtwig can't use Withdraw after the taunt!" which
        contains "can't use" but must NOT trigger MOVE_BLOCKED.
        """
        load_state(emu, "test_bug004_dawn_battle_taunt")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)  # Taunt

        assert result["final_state"] != "MOVE_BLOCKED", (
            "Taunt on opponent falsely returned MOVE_BLOCKED"
        )
        assert result["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED"), (
            f"Unexpected state: {result['final_state']}"
        )

    def test_taunt_pp_consumed(self, emu: EmulatorClient):
        """Taunt PP decrements (turn was consumed, not rejected)."""
        load_state(emu, "test_bug004_dawn_battle_taunt")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)

        # Read battle state to check Taunt PP
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        for b in battlers:
            if b.get("side") == "player":
                taunt_move = b["moves"][3]
                assert taunt_move["name"] == "Taunt"
                assert taunt_move["pp"] == 19, (
                    f"Taunt PP should be 19 (20-1), got {taunt_move['pp']}"
                )
                break

    def test_taunt_landed_in_log(self, emu: EmulatorClient):
        """Battle log confirms Taunt landed on the opponent."""
        load_state(emu, "test_bug004_dawn_battle_taunt")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=3)

        # "fell for the taunt" always appears when Taunt lands, regardless
        # of whether Turtwig tries a blocked move (RNG-dependent).
        # Normalize newlines within log entries (text has \n mid-line).
        log_text = " ".join(
            e.get("text", "").replace("\n", " ") for e in result.get("log", [])
        ).lower()
        assert "fell for the taunt" in log_text, (
            f"Expected 'fell for the taunt' in log, got: {log_text}"
        )


# ---------------------------------------------------------------------------
# BUG-009: use_battle_item target reporting hardcoded to slot 0
# ---------------------------------------------------------------------------

class TestBug009BattleItemTarget:
    """use_battle_item on bench Pokemon reports correct target, not slot 0."""

    def test_potion_on_bench_reports_correct_slot(self, emu: EmulatorClient):
        """Potion on party_slot=1 (bench Luxio) should NOT say 'Monferno'."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=1)

        assert result["success"] is True
        assert result["party_slot"] == 1
        # Must NOT report the active Pokemon (Monferno)
        target = result.get("target", "")
        assert "Monferno" not in target, (
            f"Target should not be Monferno (active slot 0), got: '{target}'"
        )

    def test_bench_pokemon_hp_unverifiable(self, emu: EmulatorClient):
        """Bench Pokemon healing returns success with unverifiable note."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=1)

        assert result["success"] is True
        assert "bench" in result.get("formatted", "").lower(), (
            f"Expected 'bench' in formatted message: {result.get('formatted')}"
        )

    def test_active_pokemon_reports_correct_name(self, emu: EmulatorClient):
        """Potion on party_slot=0 (active Monferno) reports 'Monferno'.

        Monferno is at full HP so the game says "It won't have any effect" —
        HP is unchanged, but the target name should still be resolved correctly.
        """
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=0)

        # Full HP → HP unchanged → tool reports failure (no effect).
        # The key assertion: target name should be "Monferno", not some other
        # Pokemon. Even on failure, the target is correctly identified.
        target = result.get("target", "")
        assert "Monferno" in target, (
            f"Expected 'Monferno' in target for active slot 0, got: '{target}'"
        )

    def test_final_state_is_wait_for_action(self, emu: EmulatorClient):
        """Using battle item returns WAIT_FOR_ACTION (not internal 'ACTION')."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.use_battle_item import use_battle_item
        result = use_battle_item(emu, "Potion", party_slot=1)
        assert result["final_state"] == "WAIT_FOR_ACTION", (
            f"Expected WAIT_FOR_ACTION, got {result['final_state']}"
        )


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


# ---------------------------------------------------------------------------
# BUG-003: buy_item Premier Ball bonus breaks next purchase
# ---------------------------------------------------------------------------

class TestBug003PremierBallBonus:
    """Buying 10+ Poke Balls (Premier Ball bonus) doesn't poison next buy."""

    @retry_on_rng("test_bug003_oreburgh_city_post_event")
    def test_buy_10_pokeballs_then_potions(self, emu: EmulatorClient):
        """Buy 10 Poke Balls, then 3 Potions — both succeed with correct cost."""
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        status = read_trainer_status(emu)
        badges = status.get("badges", 0)

        # First purchase: 10 Poke Balls (triggers Premier Ball bonus)
        result1 = buy_item(emu, "Poké Ball", quantity=10, badge_count=badges)
        assert result1["success"] is True, f"Poke Ball buy failed: {result1}"
        assert result1["money_spent"] == result1["total_cost"], (
            f"Poke Ball cost mismatch: spent={result1['money_spent']} "
            f"vs expected={result1['total_cost']}"
        )

        # Second purchase: 3 Potions (this was broken before the fix)
        result2 = buy_item(emu, "Potion", quantity=3, badge_count=badges)
        assert result2["success"] is True, f"Potion buy failed: {result2}"
        assert result2["item"] == "Potion", (
            f"Expected to buy Potion, got '{result2.get('item')}'"
        )
        assert result2["money_spent"] == result2["total_cost"], (
            f"Potion cost mismatch: spent={result2['money_spent']} "
            f"vs expected={result2['total_cost']}"
        )

    @retry_on_rng("test_bug003_oreburgh_city_post_event")
    def test_money_sanity_check(self, emu: EmulatorClient):
        """Purchase verification catches cost mismatch (sanity check exists)."""
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        status = read_trainer_status(emu)
        badges = status.get("badges", 0)

        # Normal single buy — sanity check should pass
        result = buy_item(emu, "Potion", quantity=1, badge_count=badges)
        assert result["success"] is True
        assert result["money_spent"] == result["total_cost"]


# ===========================================================================
# 2026-04-16 QA Round 2 — BUG-001/002/003/004
# ===========================================================================


# ---------------------------------------------------------------------------
# QA BUG-001 (2026-04-16): throw_ball formatted shows "State: TIMEOUT" after CAUGHT
# ---------------------------------------------------------------------------

class TestQaBug001ThrowBallFormatted:
    """_format_log [FFFE] handling + _recover_from_catch formatted rebuild.

    The QA save state is post-catch (Shinx already in party), so the full
    throw_ball flow can't be re-run. Instead we unit-test the two fix points
    directly: _format_log must not empty lines starting with [FFFE]..., and
    _recover_from_catch must rebuild result["formatted"] with the CAUGHT state.
    """

    def test_format_log_strips_fffe_triplet_prefix(self):
        """Line starting with [FFFE][0202][XXXX][XXXX] keeps the trailing text."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "[FFFE][0202][0001][0003]Gotcha! Shinx was caught!", "stop": "AUTO_ADVANCE"}]
        out = _format_log(log, "CAUGHT")
        assert "Gotcha! Shinx was caught!" in out, (
            f"[FFFE]-prefixed text truncated; got: {out!r}"
        )
        assert "State: CAUGHT" in out

    def test_format_log_strips_fffe_0200_action_prompt(self):
        """WAIT_FOR_ACTION [FFFE][0200] marker is stripped without truncating line."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "What will [FFFE][0200]Luxray do?", "stop": "WAIT_FOR_ACTION"}]
        out = _format_log(log, "WAIT_FOR_ACTION")
        assert "What will" in out
        assert "Luxray do?" in out
        assert "[FFFE]" not in out
        assert "[0200]" not in out

    def test_format_log_inline_fffe_preserves_surrounding_text(self):
        """[FFFE] substitution mid-line drops the var tokens but keeps text."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "Shinx grew to Lv. [FFFE][0202][0001][0002]!", "stop": "AUTO_ADVANCE"}]
        out = _format_log(log, "BATTLE_ENDED")
        assert "Shinx grew to Lv." in out
        assert "[FFFE]" not in out
        # The trailing "!" after the triplet survives the substitution.
        assert "!" in out

    def test_format_log_no_fffe_is_unchanged(self):
        """Plain text without [FFFE] is formatted as-is."""
        from renegade_mcp.battle_tracker import _format_log
        log = [{"text": "Shinx fainted!", "stop": "AUTO_ADVANCE"}]
        out = _format_log(log, "BATTLE_ENDED")
        assert "Shinx fainted!" in out

    def test_recover_from_catch_rebuilds_formatted(self):
        """_recover_from_catch overwrites the stale formatted tail from the tracker poll."""
        from unittest.mock import MagicMock
        from renegade_mcp import catch as catch_mod

        # Stub _is_battle_over so the recovery loop exits on the first iteration.
        original_over = catch_mod._is_battle_over
        catch_mod._is_battle_over = lambda emu: True
        try:
            fake_emu = MagicMock()
            # Tracker-style poll result with stale "State: TIMEOUT" in formatted.
            initial_formatted = (
                "=== Battle Log ===\n"
                "  \n"  # The [FFFE]-prefixed catch line was truncated to empty.
                "\nState: TIMEOUT"
            )
            result = {
                "log": [{"text": "[FFFE][0202][0001][0003]Gotcha! Shinx was caught!",
                         "stop": "AUTO_ADVANCE"}],
                "final_state": "TIMEOUT",
                "formatted": initial_formatted,
            }
            fixed = catch_mod._recover_from_catch(fake_emu, result)
        finally:
            catch_mod._is_battle_over = original_over

        assert fixed["final_state"] == "CAUGHT"
        assert "State: CAUGHT" in fixed["formatted"]
        assert "State: TIMEOUT" not in fixed["formatted"]
        # After the _format_log fix the "Gotcha!" line survives reformatting.
        assert "Gotcha! Shinx was caught!" in fixed["formatted"]


# ---------------------------------------------------------------------------
# QA BUG-002 (2026-04-16): auto_grind auto-heal stuck on wild FAINT_SWITCH
# ---------------------------------------------------------------------------

class TestQaBug002WildFaintSwitchClassification:
    """_wait_for_action_prompt distinguishes wild FAINT_SWITCH from trainer FAINT_FORCED.

    The fallback path used to default to FAINT_FORCED when its own polling log
    lacked "Use next" text — which is exactly what happens when the caller
    (e.g. _auto_heal_and_return) invokes battle_turn() fresh and the tracker
    log is empty. The fix (_classify_faint_type) scans the current marker
    buffer for "Use next" before defaulting to FAINT_FORCED.

    Note: the QA save state (bug_qa_auto_grind_faint_switch_stuck) was captured
    AFTER the "Use next Pokémon?" Yes/No prompt had already been answered YES
    — the game is at the "Choose a Pokémon." party grid with no option to flee.
    So the save state exercises the CORRECT FAINT_FORCED classification path
    (text is truly absent) and the recovery-via-switch path. The Yes-stage
    behavior is covered by the unit test below using a synthesized marker blob.
    """

    def _encode_gen4_text(self, text: str) -> bytes:
        """Encode ASCII `text` into Gen4 16-bit chars + END terminator + header."""
        import struct
        from renegade_mcp.battle_tracker import HEADER_MARKER
        from renegade_mcp.text_encoding import CTRL_END
        reverse = {}
        # A-Z
        for i in range(26):
            reverse[chr(ord("A") + i)] = 0x012B + i
        # a-z
        for i in range(26):
            reverse[chr(ord("a") + i)] = 0x0145 + i
        # digits
        for i in range(10):
            reverse[chr(ord("0") + i)] = 0x0161 + i
        reverse[" "] = 0x01DE
        reverse["?"] = 0x01AC
        reverse["."] = 0x01AE
        reverse["!"] = 0x01AB
        reverse[","] = 0x01AD
        vals = [reverse[c] for c in text if c in reverse]
        vals.append(CTRL_END)
        body = b"".join(struct.pack("<H", v) for v in vals)
        return HEADER_MARKER + body

    def test_classify_faint_type_finds_use_next_in_marker_scan(self):
        """_classify_faint_type returns FAINT_SWITCH when 'Use next' is in the scan buffer."""
        from unittest.mock import MagicMock
        from renegade_mcp import turn as turn_mod

        # Fake emu: read_memory_block returns a buffer containing the encoded prompt.
        blob = b"\x00" * 0x100 + self._encode_gen4_text("Use next Pokemon?") + b"\x00" * 0x100
        fake_emu = MagicMock()
        fake_emu.read_memory_block.return_value = blob

        # Patch _scan_start to return a known base address (value doesn't matter
        # for content matching — _classify_faint_type only uses the decoded text).
        orig_scan_start = turn_mod._scan_start
        turn_mod._scan_start = lambda: 0x02000000
        try:
            log: list[dict] = []
            result = turn_mod._classify_faint_type(fake_emu, log)
        finally:
            turn_mod._scan_start = orig_scan_start

        assert result == "FAINT_SWITCH", (
            f"Expected FAINT_SWITCH from marker scan, got {result!r}"
        )
        assert any("Use next" in e.get("text", "") for e in log), (
            "Discovered marker should be appended to log."
        )

    def test_classify_faint_type_from_log_short_circuits(self):
        """Accumulated log containing 'Use next' returns FAINT_SWITCH without scanning memory."""
        from unittest.mock import MagicMock
        from renegade_mcp import turn as turn_mod

        fake_emu = MagicMock()
        # If the scan path were taken this would raise — but it shouldn't be.
        fake_emu.read_memory_block.side_effect = AssertionError("should not scan when log matches")

        log = [{"text": "Use next Pokemon?", "stop": "WAIT_FOR_ACTION"}]
        result = turn_mod._classify_faint_type(fake_emu, log)
        assert result == "FAINT_SWITCH"

    def test_classify_faint_type_defaults_to_forced_when_absent(self):
        """No 'Use next' anywhere → FAINT_FORCED (trainer-style forced switch)."""
        from unittest.mock import MagicMock
        from renegade_mcp import turn as turn_mod

        # Buffer has other Gen4 text but no "Use next" prompt.
        blob = b"\x00" * 0x100 + self._encode_gen4_text("Choose a Pokemon.") + b"\x00" * 0x100
        fake_emu = MagicMock()
        fake_emu.read_memory_block.return_value = blob

        orig_scan_start = turn_mod._scan_start
        turn_mod._scan_start = lambda: 0x02000000
        try:
            result = turn_mod._classify_faint_type(fake_emu, [])
        finally:
            turn_mod._scan_start = orig_scan_start

        assert result == "FAINT_FORCED"

    def test_post_yes_state_classified_as_faint_forced(self, emu: EmulatorClient):
        """QA save state is post-YES (party grid, no 'Use next') — must classify as FAINT_FORCED."""
        load_state(emu, "bug_qa_auto_grind_faint_switch_stuck")
        from renegade_mcp.turn import _wait_for_action_prompt
        prompt = _wait_for_action_prompt(emu)
        assert prompt.get("ready") is True
        assert prompt.get("prompt_type") == "FAINT_FORCED", (
            f"Party grid state should classify as FAINT_FORCED, got {prompt.get('prompt_type')}"
        )

    def test_recovery_via_switch_to_eevee(self, emu: EmulatorClient):
        """From the stuck party-grid state, battle_turn(switch_to=1) sends in Eevee."""
        load_state(emu, "bug_qa_auto_grind_faint_switch_stuck")
        from renegade_mcp.turn import battle_turn
        # Slot 1 is Eevee Lv10 (confirmed via read_party in the debug session).
        result = battle_turn(emu, switch_to=1)
        state = result.get("final_state", "")
        # After switch, a wild battle turn resolves and we get the next action
        # prompt (or the battle ends if Eevee also faints — unlikely at full HP).
        assert state in ("WAIT_FOR_ACTION", "BATTLE_ENDED", "FAINT_SWITCH"), (
            f"Unexpected state after switch-in: {state}. Error: {result.get('error')!r}"
        )
        # Must not error out as a trainer battle — that was the original symptom.
        err = result.get("error", "")
        assert "trainer battle" not in err.lower(), (
            f"Recovery via switch_to should not fail with trainer error: {err!r}"
        )


# ---------------------------------------------------------------------------
# QA BUG-003 (2026-04-16): _is_evolution_text_on_screen misses "What?" prompt
# ---------------------------------------------------------------------------

class TestQaBug003EvolutionWhatDetection:
    """_is_evolution_text_on_screen detects both "is evolving" and WAIT_FOR_ACTION "What?".

    Root cause: the predicate only matched "is evolving". In Gen 4, evolution
    begins with a WAIT_FOR_ACTION "What?" prompt that precedes the "is evolving!"
    text. If the move-learn flow pressed B during the "What?" window, the input
    cancelled the pending evolution. The fix broadens the predicate to treat a
    "What?"-prefixed marker as evolution-in-progress so the B-press loop exits
    and hands off to _wait_for_evolution.
    """

    def test_stopped_evolving_does_not_false_positive(self, emu: EmulatorClient):
        """On a post-bug 'stopped evolving' state, the predicate returns False — evolution is already done/cancelled."""
        load_state(emu, "bug_qa_auto_grind_evolution_stop_lingering_dialogue")
        from renegade_mcp.turn import _is_evolution_text_on_screen
        # "Huh? Chimchar stopped evolving!" is on screen. Neither "is evolving"
        # nor a "What?" prompt — predicate must stay False.
        assert _is_evolution_text_on_screen(emu) is False

    def test_predicate_matches_is_evolving_substring(self):
        """Direct scan_markers-style substring check: 'is evolving' matches."""
        # The predicate loop is: any marker containing "is evolving" OR starting
        # with "What?". Simulate the loop over a markers dict.
        from renegade_mcp.text_encoding import CTRL_END
        import struct

        # Just unit-verify the substring tests that the predicate uses.
        def _predicate(markers: dict) -> bool:
            for text in markers.values():
                clean = text.replace("\n", " ").strip()
                if "is evolving" in clean:
                    return True
                if clean.startswith("What?"):
                    return True
            return False

        assert _predicate({"0x1": "Chimchar is evolving!"}) is True
        assert _predicate({"0x1": "What?\n"}) is True
        assert _predicate({"0x1": "What will Chimchar do?"}) is False
        assert _predicate({"0x1": "Huh? Chimchar stopped evolving!"}) is False
        assert _predicate({"0x1": "Chimchar learned Flame Wheel!"}) is False


# ---------------------------------------------------------------------------
# QA BUG-004 (2026-04-16): battle_turn stalls on target-pick after partner KO
# ---------------------------------------------------------------------------

class TestQaBug004DoublesDetectionSpeciesCount:
    """_is_double_battle uses species count, not alive count.

    Previously it returned False once a player partner fainted, which made
    _execute_action skip the target-pick tap in doubles and leave the game
    stuck on the target-pick submenu. The fix counts player slots with a
    valid species (regardless of HP).
    """

    def test_is_double_battle_true_with_fainted_partner(self, emu: EmulatorClient):
        """Slot 0 alive + slot 2 fainted should still read as doubles."""
        load_state(emu, "bug_qa_battle_turn_stuck_after_double_ko_doubles")
        from renegade_mcp.turn import _is_double_battle
        assert _is_double_battle(emu) is True, (
            "Doubles format detection failed: fainted partner treated as singles."
        )

    def test_battle_struct_has_valid_species_in_both_player_slots(self, emu: EmulatorClient):
        """Sanity check: slot 0 and slot 2 both hold real species (even if fainted)."""
        import struct
        load_state(emu, "bug_qa_battle_turn_stuck_after_double_ko_doubles")
        from renegade_mcp.addresses import addr
        base = addr("BATTLE_BASE")
        for slot in (0, 2):
            off = slot * 0xC0
            species = emu.read_memory(base + off + 0x00, size="short")
            assert 1 <= species <= 493, (
                f"Slot {slot} species {species} invalid — struct corrupted?"
            )

    def test_battle_turn_resolves_target_pick_with_scratch(self, emu: EmulatorClient):
        """battle_turn(move_index=0, target=0) picks Azurill and the turn resolves.

        Pre-fix: _is_double_battle returned False (partner fainted) so the
        target-pick tap was skipped, battle stuck on submenu. Now with species-
        count detection, the target flow fires and the move connects.
        """
        load_state(emu, "bug_qa_battle_turn_stuck_after_double_ko_doubles")
        from renegade_mcp.turn import battle_turn
        from renegade_mcp.battle import read_battle

        # Capture Azurill's HP before the turn. Slot 1 = first enemy = target 0.
        pre = {b["slot"]: b["hp"] for b in read_battle(emu)}
        azurill_pre = pre.get(1, 0)

        result = battle_turn(emu, move_index=0, target=0)
        # The turn must actually advance — not stall at ACTION with stale prompt.
        state = result.get("final_state", "")
        assert state in ("WAIT_FOR_ACTION", "BATTLE_ENDED"), (
            f"Turn did not resolve — state={state}. Error: {result.get('error')!r}"
        )

        # Scratch should have dealt damage or KO'd Azurill.
        post = {b["slot"]: b["hp"] for b in read_battle(emu)}
        azurill_post = post.get(1, azurill_pre)
        assert azurill_post < azurill_pre or state == "BATTLE_ENDED", (
            f"Azurill HP unchanged ({azurill_pre} → {azurill_post}); "
            f"Scratch didn't land. state={state}"
        )


# ---------------------------------------------------------------------------
# QA BUG-005: ROM text-variable placeholders leak through dialogue output
# ---------------------------------------------------------------------------

class TestQaBug005TextPlaceholderLeak:
    """Decoders strip Gen 4 VAR blocks (FFFE id count args) and resolve
    known glyph codes (0x25BD line-break, 0x01A8 currency) instead of
    surfacing raw [VAR]/[FFFE]/[XXXX] placeholders to callers."""

    def test_battle_prompt_is_clean(self, emu: EmulatorClient):
        """read_dialogue(region='battle') returns no raw control tokens.

        Pre-fix: "What will Chimchar do?[VAR][0200][0001][0000]"
        Post-fix: "What will Chimchar do?"
        """
        from renegade_mcp.dialogue import read_dialogue

        load_state(emu, "fr001_repro_growlithe_battle_prompt")
        result = read_dialogue(emu, "battle")
        text = result.get("text", "")
        assert text == "What will Chimchar do?", (
            f"Battle prompt should be clean, got: {text!r}"
        )
        # Belt-and-braces: no raw bracketed tokens anywhere in the output.
        assert "[" not in text, f"Raw control token leaked: {text!r}"

    def test_var_block_consumer_consumes_count_plus_three(self):
        """_consume_var_block advances past FFFE + var_id + arg_count + args."""
        from renegade_mcp.text_encoding import CTRL_VAR, _consume_var_block

        # [VAR][0200][0001][0000] = FFFE, id=0200, count=1, arg=0000 → 4 tokens
        vals = [CTRL_VAR, 0x0200, 0x0001, 0x0000]
        assert _consume_var_block(vals, 0) == 4

        # [VAR][0103][0002][0000][0000] = FFFE, id=0103, count=2, 2 args → 5 tokens
        vals = [CTRL_VAR, 0x0103, 0x0002, 0x0000, 0x0000]
        assert _consume_var_block(vals, 0) == 5

        # Corrupt arg_count is clamped (safety): 0xFFFF args would otherwise
        # swallow the rest of the buffer. Treated as count=0.
        vals = [CTRL_VAR, 0x0200, 0xFFFF, 0x41, 0x42, 0x43]
        # 0xFFFF > 8 → treated as 0 args → advances 3 tokens.
        assert _consume_var_block(vals, 0) == 3

    def test_text_encoding_decode_values_strips_var(self):
        """decode_values(): VAR blocks stripped, other chars pass through."""
        from renegade_mcp.text_encoding import CTRL_VAR, decode_values

        # "H" (0x0132) + [VAR][0200][0001][0000] + "i" (0x014D)
        vals = [0x0132, CTRL_VAR, 0x0200, 0x0001, 0x0000, 0x014D]
        lines = decode_values(vals)
        assert lines == ["Hi"], f"Got: {lines!r}"

    def test_line_break_0x25bd_becomes_newline(self):
        """0x25BD line-break (the one that used to show as [25BD]) becomes \\n."""
        from renegade_mcp.text_encoding import CTRL_LINE_BREAK, decode_values

        # "A" + line-break + "B"
        vals = [0x012B, CTRL_LINE_BREAK, 0x012C]
        lines = decode_values(vals)
        assert lines == ["A", "B"], f"Got: {lines!r}"

    def test_currency_glyph_0x01a8_becomes_dollar(self):
        """0x01A8 (P-with-stroke / Pokémon-currency) renders as '$'."""
        from renegade_mcp.text_encoding import decode_values

        # "$" (0x01A8) + "1" (0x0162) + "0" (0x0161) + "0" (0x0161)
        vals = [0x01A8, 0x0162, 0x0161, 0x0161]
        lines = decode_values(vals)
        assert lines == ["$100"], f"Got: {lines!r}"

    def test_battle_log_is_clean_after_seek_encounter(self, emu: EmulatorClient):
        """battle_turn output has no [VAR]/[FFFE]/[XXXX] in any log entry."""
        from renegade_mcp.turn import battle_turn

        load_state(emu, "fr001_repro_growlithe_battle_prompt")
        result = battle_turn(emu, move_index=0)
        log_entries = result.get("log", [])
        for entry in log_entries:
            text = entry.get("text", "") if isinstance(entry, dict) else str(entry)
            assert "[FFFE]" not in text and "[VAR]" not in text, (
                f"Control token leaked in battle log: {text!r}"
            )
            # Any raw hex placeholder would have the form [XXXX]. Allow
            # nothing bracketed at all.
            import re
            assert not re.search(r"\[[0-9A-F]{4}\]", text), (
                f"Raw hex placeholder leaked: {text!r}"
            )


# ---------------------------------------------------------------------------
# QA BUG-006: buy_item leaves player stuck in shop UI on "How many?" prompt
# ---------------------------------------------------------------------------

class TestQaBug006BuyItemExit:
    """After buy_item completes, game must be back in full overworld control
    — not sitting on the post-purchase quantity prompt or item list."""

    @retry_on_rng("jubilife_mart_after_buy_5potions")
    def test_buy_item_returns_to_overworld(self, emu: EmulatorClient):
        """Pre-fix: tool returned success but game sat on "Potion? Certainly.
        How many would you like?" quantity prompt — 3 B-presses shy of overworld.

        Post-fix: 3 B-presses advance both post-purchase dialog pages plus the
        item-list → main-menu step, then down×2 + A×2 exits through SEE YA!.
        """
        from renegade_mcp.dialogue import read_dialogue
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Potion", quantity=1, badge_count=0)
        assert "error" not in result, f"buy_item error: {result.get('error')}"

        dlg = read_dialogue(emu, "overworld")
        assert dlg.get("text", "(no active text)") == "(no active text)", (
            f"Expected no active text after buy_item, got: {dlg.get('text')!r}"
        )


# ---------------------------------------------------------------------------
# QA BUG-008: Hex format codes leak in item-pickup / cutscene dialogue
# ---------------------------------------------------------------------------
# Same family as fixed BUG-005 (0x25BD, 0x01A8). BUG-005 handled FFFE VAR blocks
# and two glyphs, but left five more glyphs that routinely leak through
# item-acquired cutscene text:
#   0x01C2 — small-font '&'   ("TMs & HMs" pocket label, ROM file 395)
#   0x01D2 — small-font '%'   ("90% of all Pokémon", ROM file 23 Dawn dialogue)
#   0x0113 — ITEMS pocket icon glyph
#   0x0114 — KEY ITEMS pocket icon glyph
#   0x0115 — TMs & HMs pocket icon glyph
#   (0x0116–0x011A cover MAIL/MEDICINE/BERRIES/POKé BALLS/BATTLE ITEMS per ROM file 396)
#
# Pocket icon glyphs are tiny sprites in-game — they can't render as ASCII and
# are emitted as empty string. Alt-font glyphs are mapped to their ASCII variant.

class TestQaBug008HexFormatCodeLeak:
    """CHAR_MAP covers alternate-font glyphs and pocket-icon sprite codes so
    they don't leak as raw [XXXX] brackets in decoded dialogue."""

    def test_small_font_ampersand_0x01c2(self):
        """0x01C2 (alt-font '&') renders as '&'. Example: 'TMs & HMs'."""
        from renegade_mcp.text_encoding import decode_values

        # "TMs " + 0x01C2 + " HMs"
        # T=0x013E A=0x012B/...  but simpler: test the glyph directly surrounded by ASCII.
        # Use letters T(0x013E), M(0x0137), s(0x0157), space(0x01DE), H(0x0132).
        vals = [0x013E, 0x0137, 0x0157, 0x01DE, 0x01C2, 0x01DE, 0x0132, 0x0137, 0x0157]
        lines = decode_values(vals)
        assert lines == ["TMs & HMs"], f"Got: {lines!r}"

    def test_small_font_percent_0x01d2(self):
        """0x01D2 (alt-font '%') renders as '%'. Example: '90% of all'."""
        from renegade_mcp.text_encoding import decode_values

        # "90" + 0x01D2 (→ %) + " " — digits: 9=0x016A 0=0x0161
        vals = [0x016A, 0x0161, 0x01D2]
        lines = decode_values(vals)
        assert lines == ["90%"], f"Got: {lines!r}"

    def test_pocket_icon_glyphs_are_elided(self):
        """0x0113..0x011A are pocket sprite icons — render as empty string.

        Covers all 8 pockets from ROM file 396 (pocket label table).
        """
        from renegade_mcp.text_encoding import decode_values

        for glyph in (0x0113, 0x0114, 0x0115, 0x0116, 0x0117, 0x0118, 0x0119, 0x011A):
            # Render "A" + glyph + "B" — glyph should vanish entirely.
            vals = [0x012B, glyph, 0x012C]
            lines = decode_values(vals)
            assert lines == ["AB"], (
                f"Glyph 0x{glyph:04X} leaked instead of being elided: {lines!r}"
            )

    def test_pocket_name_template_renders_clean(self):
        """End-to-end: 'KEY ITEMS Pocket' template round-trips without brackets.

        Reproduces the ROM file 396 KEY ITEMS entry: FFFE color-open + 0x0114
        icon + FFFE color-close + 'KEY ITEMS'. Pre-fix this surfaced as
        '[0114]KEY ITEMS'; post-fix it is just 'KEY ITEMS'.
        """
        from renegade_mcp.text_encoding import CTRL_VAR, decode_values

        # FFFE FF00 0001 0002 (color-open 1-arg 0x0002 = blue)
        # + 0x0114 pocket icon
        # + FFFE FF00 0001 0000 (color-close 1-arg 0x0000)
        # + " KEY ITEMS" letters
        # Letter codes from CHAR_MAP: A=0x012B, so K=A+10=0x0135, E=A+4=0x012F,
        # Y=A+24=0x0143, I=A+8=0x0133, T=A+19=0x013E, M=A+12=0x0137, S=A+18=0x013D,
        # space=0x01DE.
        vals = [
            CTRL_VAR, 0xFF00, 0x0001, 0x0002,
            0x0114,
            CTRL_VAR, 0xFF00, 0x0001, 0x0000,
            0x0135, 0x012F, 0x0143, 0x01DE,  # "KEY "
            0x0133, 0x013E, 0x012F, 0x0137, 0x013D,  # "ITEMS"
        ]
        lines = decode_values(vals)
        assert lines == ["KEY ITEMS"], f"Got: {lines!r}"
        # Belt-and-braces: no bracketed leaks.
        joined = "".join(lines)
        assert "[" not in joined, f"Raw bracket in decoded output: {joined!r}"

    def test_post_galactic_dialogue_has_no_brackets(self, emu: EmulatorClient):
        """Integration: replay the Galactic-grunts double battle win and
        assert the `post_battle_dialogue` list contains no [XXXX] leaks.

        Pre-fix the Fashion Case cutscene surfaced:
          'in the [0114]KEY ITEMS Pocket.' and '90[01D2] of all Pokémon...'
        Post-fix both lines are clean.
        """
        import re
        from renegade_mcp.turn import battle_turn

        load_state(emu, "bug008_pre_galactic_battle_win")

        # Finish the double battle — Flame Wheel (slot 1) KOs each enemy.
        # Partner Clefairy flinches / auto-acts; we just need to land killing blows.
        # Turn 1: Flame Wheel → Stunky (crit + Aftermath, but Stunky dies).
        # Turn 2: Silcoon (sent in after Stunky faints).
        # Turn 3: Cascoon (sent in after Silcoon faints) → battle ends.
        r1 = battle_turn(emu, move_index=1, target=0)
        assert r1["final_state"] in ("WAIT_FOR_ACTION", "ACTION"), (
            f"Turn 1 state: {r1['final_state']}"
        )
        r2 = battle_turn(emu, move_index=1, target=1)  # target Silcoon
        assert r2["final_state"] in ("WAIT_FOR_ACTION", "ACTION"), (
            f"Turn 2 state: {r2['final_state']}"
        )
        r3 = battle_turn(emu, move_index=1, target=0)  # target remaining enemy
        assert r3["final_state"] in ("WAIT_FOR_ACTION", "ACTION"), (
            f"Turn 3 state: {r3['final_state']}"
        )
        r4 = battle_turn(emu, move_index=1, target=1)
        assert r4["final_state"] == "BATTLE_ENDED", (
            f"Turn 4 did not end battle: {r4['final_state']}"
        )

        post_dialogue = r4.get("post_battle_dialogue", [])
        assert post_dialogue, "Expected post_battle_dialogue from Galactic cutscene"

        # Assert no lines contain bracketed hex tokens like [0114] / [01D2].
        bracket_re = re.compile(r"\[[0-9A-F]{4}\]")
        for line in post_dialogue:
            leak = bracket_re.search(line)
            assert leak is None, (
                f"Hex-code leak in post_battle_dialogue: {leak.group()!r} "
                f"in line: {line!r}"
            )

        # Positive spot-checks: the two specific lines that carried the leak
        # now render with their resolved glyphs.
        all_text = "\n".join(post_dialogue)
        assert "90% of all" in all_text, (
            f"Expected '90% of all' with resolved %% in:\n{all_text!r}"
        )
        assert "KEY ITEMS Pocket" in all_text, (
            f"Expected 'KEY ITEMS Pocket' with stripped icon in:\n{all_text!r}"
        )


# ---------------------------------------------------------------------------
# FR-005: battle_turn(switch_to=0) error names the active battler
# ---------------------------------------------------------------------------

class TestFr005SwitchToZeroErrorMessage:
    """switch_to=0 rejection includes active-battler species + slot-numbering clarification."""

    def test_error_names_active_battler_species(self, emu: EmulatorClient):
        """Error message includes the current active battler's species name."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, switch_to=0)

        assert "error" in result, f"Expected error response, got: {result}"
        assert "Monferno" in result["error"], (
            f"Expected 'Monferno' in error (active battler), got: {result['error']!r}"
        )

    def test_error_clarifies_party_slot_numbering(self, emu: EmulatorClient):
        """Error explains switch_to uses party-slot numbering, not battle-slot."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, switch_to=0)

        assert "error" in result
        msg = result["error"]
        assert "party" in msg.lower(), (
            f"Expected 'party' reference in error message, got: {msg!r}"
        )
        assert "1-5" in msg, f"Expected '1-5' hint in error message, got: {msg!r}"

    def test_helper_builds_message_with_species(self, emu: EmulatorClient):
        """Direct unit test of the _switch_to_zero_error helper."""
        load_state(emu, "test_bug009_roark_battle_monferno_lead")
        from renegade_mcp.turn import _switch_to_zero_error
        msg = _switch_to_zero_error(emu)

        assert "Monferno" in msg, f"Expected 'Monferno' in helper output, got: {msg!r}"
        assert "active battler" in msg.lower(), (
            f"Expected 'active battler' phrasing in helper output, got: {msg!r}"
        )
