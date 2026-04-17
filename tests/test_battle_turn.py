"""Tests for battle_turn: core turn mechanics.

Covers action submission (move/switch/run), double battles, self-targeting
moves, accuracy warnings, and several regression paths within `turn.py`:

- TestBug004TauntNotMoveBlocked: Taunt landing on opponent must not trigger
  MOVE_BLOCKED false-positive.
- TestQaBug002WildFaintSwitchClassification: `_classify_faint_type` must
  distinguish wild FAINT_SWITCH from trainer FAINT_FORCED.
- TestQaBug003EvolutionWhatDetection: `_is_evolution_text_on_screen` must
  match both "is evolving" and the leading WAIT_FOR_ACTION "What?" prompt.
- TestQaBug004DoublesDetectionSpeciesCount: `_is_double_battle` must use
  species-count (not alive-count) so target-pick still fires after a
  partner KO.
- TestFr005SwitchToZeroErrorMessage: switch_to=0 error names the active
  battler and clarifies party-slot numbering (1-5).

Save states used:
  test_wild_battle_action — Prinplup vs wild Smoochum, action prompt.
  debug_doubles_target_swapped — doubles battle, Luxio slot 0 / Machop slot 2.
  test_bug004_dawn_battle_taunt — Chimchar Lv10 vs Dawn's Turtwig (Taunt in slot 3).
  bug_qa_auto_grind_faint_switch_stuck — Wild Rattata, Shinx 0 HP, party grid open.
  bug_qa_auto_grind_evolution_stop_lingering_dialogue — Post-bug "stopped evolving" text.
  bug_qa_battle_turn_stuck_after_double_ko_doubles — Doubles target-pick, partner KO'd.
  test_bug009_roark_battle_monferno_lead — Roark fight, Monferno active, Luxio/Eevee bench.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import (
    do_load_state as load_state,
    retry_on_rng,
    assert_log_contains,
)


# ---------------------------------------------------------------------------
# Core battle_turn actions
# ---------------------------------------------------------------------------

class TestBattleTurn:
    """Core battle action tool."""

    @retry_on_rng("test_wild_battle_action")
    def test_use_move(self, emu: EmulatorClient):
        """Use move 0 — log shows the move was used."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
        ), f"Unexpected: {result['final_state']}"
        assert_log_contains(result, "used")

    @retry_on_rng("test_wild_battle_action")
    def test_run_from_battle(self, emu: EmulatorClient):
        """Run from wild battle — BATTLE_ENDED on success, WAIT_FOR_ACTION on fail."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, run=True)
        state = result["final_state"]
        assert state in ("BATTLE_ENDED", "WAIT_FOR_ACTION"), f"Unexpected: {state}"
        if state == "BATTLE_ENDED":
            assert_log_contains(result, "got away")
        else:
            assert_log_contains(result, "can't escape")

    @retry_on_rng("test_wild_battle_action")
    def test_switch_pokemon(self, emu: EmulatorClient):
        """Switch to party slot 1 mid-battle — new Pokemon is now active."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, switch_to=1)
        assert result["final_state"] == "WAIT_FOR_ACTION", (
            f"Switch should return WAIT_FOR_ACTION, got: {result['final_state']}"
        )
        # Active battler should now be slot 1's species (Machop in this state)
        player = next(b for b in result["battle_state"] if b["side"] == "player")
        assert player["species"] != "Prinplup", "Active battler should have changed from lead"

    @retry_on_rng("test_wild_battle_action")
    def test_battle_state_has_battlers(self, emu: EmulatorClient):
        """battle_turn response includes player and enemy battler data."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert "battle_state" in result, "Response missing battle_state"
        if result["final_state"] != "BATTLE_ENDED":
            bs = result["battle_state"]
            assert len(bs) >= 2, f"Expected >=2 battlers, got {len(bs)}"
            player = next((b for b in bs if b["side"] == "player"), None)
            enemy = next((b for b in bs if b["side"] == "enemy"), None)
            assert player is not None, "No player battler in battle_state"
            assert enemy is not None, "No enemy battler in battle_state"
            assert "species" in player and "hp" in player
            assert "species" in enemy and "hp" in enemy

    @retry_on_rng("test_wild_battle_action")
    def test_fight_until_ko(self, emu: EmulatorClient):
        """Fight until KO — BATTLE_ENDED with 'fainted' in log."""
        from renegade_mcp.turn import battle_turn
        # Use Bubble Beam (move 2) repeatedly — super effective vs Ice
        for _ in range(10):
            result = battle_turn(emu, move_index=2)
            state = result["final_state"]
            if state == "BATTLE_ENDED":
                break
            elif state == "MOVE_LEARN":
                result = battle_turn(emu, forget_move=-1)
                if result["final_state"] == "BATTLE_ENDED":
                    break
            elif state in ("WAIT_FOR_ACTION",):
                continue
            else:
                break
        assert result["final_state"] == "BATTLE_ENDED"

    @retry_on_rng("test_wild_battle_action")
    def test_fight_log_contains_damage(self, emu: EmulatorClient):
        """Using a damaging move produces log with move name and damage text."""
        from renegade_mcp.turn import battle_turn
        # Move 0 is Metal Claw (Steel, Physical) — should deal damage to Smoochum
        result = battle_turn(emu, move_index=0)
        assert result["final_state"] in ("WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN")
        assert_log_contains(result, "Metal Claw")

    def test_double_battle_first_action(self, emu: EmulatorClient):
        """Double battle: first action returns WAIT_FOR_PARTNER_ACTION."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0, target=0)
        # First action in doubles should prompt for partner's action
        assert result["final_state"] == "WAIT_FOR_PARTNER_ACTION", (
            f"Expected WAIT_FOR_PARTNER_ACTION, got: {result['final_state']}"
        )

    @retry_on_rng("debug_doubles_target_swapped")
    def test_double_battle_both_actions(self, emu: EmulatorClient):
        """Double battle: submit both actions — turn resolves."""
        from renegade_mcp.turn import battle_turn
        # First Pokemon's action
        result1 = battle_turn(emu, move_index=0, target=0)
        assert result1["final_state"] == "WAIT_FOR_PARTNER_ACTION", (
            f"First action: expected WAIT_FOR_PARTNER_ACTION, got {result1['final_state']}"
        )
        # Second Pokemon's action
        result2 = battle_turn(emu, move_index=0, target=0)
        assert result2["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "SWITCH_PROMPT",
            "FAINT_SWITCH", "FAINT_FORCED", "MOVE_LEARN", "LEVEL_UP",
        ), f"Second action: unexpected state {result2['final_state']}"


class TestSelfTargetingDoubles:
    """Self-targeting moves (range=16) in double battles (BUG-003).

    Uses debug_doubles_target_swapped save state where:
    - Slot 0 (player) Luxio: Spark, Bite, Howl (self-targeting), Quick Attack
    - Slot 2 (player) Machop: Low Kick, Brick Break, Focus Energy (self-targeting), Knock Off
    """

    def test_chooser_name_extraction(self, emu: EmulatorClient):
        """_chooser_name_from_prompt extracts Pokemon name from action prompt."""
        from renegade_mcp.turn import _chooser_name_from_prompt
        prompt = {"log": [{"text": "What will Luxio do?[FFFE][0200]", "stop": "WAIT_FOR_ACTION"}]}
        assert _chooser_name_from_prompt(prompt) == "Luxio"
        prompt2 = {"log": [{"text": "What will Machop do?[FFFE][0200]", "stop": "WAIT_FOR_ACTION"}]}
        assert _chooser_name_from_prompt(prompt2) == "Machop"
        assert _chooser_name_from_prompt({"log": []}) is None

    def test_is_self_targeting_howl(self, emu: EmulatorClient):
        """Howl (move index 2 on Luxio) is detected as self-targeting."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import _is_self_targeting_move
        # Luxio's Howl (index 2) = self-targeting
        assert _is_self_targeting_move(emu, 2, "Luxio") is True
        # Luxio's Spark (index 0) = NOT self-targeting
        assert _is_self_targeting_move(emu, 0, "Luxio") is False

    def test_is_self_targeting_focus_energy(self, emu: EmulatorClient):
        """Focus Energy (move index 2 on Machop) is detected as self-targeting."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import _is_self_targeting_move
        # Machop's Focus Energy (index 2) = self-targeting
        assert _is_self_targeting_move(emu, 2, "Machop") is True
        # Machop's Low Kick (index 0) = NOT self-targeting
        assert _is_self_targeting_move(emu, 0, "Machop") is False

    def test_self_target_first_action(self, emu: EmulatorClient):
        """Using a self-targeting move as first action returns WAIT_FOR_PARTNER_ACTION."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.turn import battle_turn
        # Luxio uses Howl (self-targeting, index 2)
        result = battle_turn(emu, move_index=2)
        assert result["final_state"] == "WAIT_FOR_PARTNER_ACTION", (
            f"Expected WAIT_FOR_PARTNER_ACTION, got: {result['final_state']}"
        )

    @retry_on_rng("debug_doubles_target_swapped")
    def test_self_target_both_actions(self, emu: EmulatorClient):
        """Both Pokemon use self-targeting moves — turn resolves."""
        from renegade_mcp.turn import battle_turn
        # First: Luxio uses Howl (self-targeting, index 2)
        result1 = battle_turn(emu, move_index=2)
        assert result1["final_state"] == "WAIT_FOR_PARTNER_ACTION"
        # Second: Machop uses Focus Energy (self-targeting, index 2)
        result2 = battle_turn(emu, move_index=2)
        # Turn resolves — any valid post-turn state is acceptable.
        # Machop may faint from super-effective attacks before Focus Energy fires.
        assert result2["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "SWITCH_PROMPT",
            "FAINT_SWITCH", "FAINT_FORCED", "MOVE_LEARN",
        ), f"Both self-target: unexpected state {result2['final_state']}"
        # Howl should always appear (Luxio is faster and bulkier)
        assert_log_contains(result2, "Howl")

    @retry_on_rng("debug_doubles_target_swapped")
    def test_normal_then_self_target(self, emu: EmulatorClient):
        """Normal move first, self-targeting second — turn resolves."""
        from renegade_mcp.turn import battle_turn
        # Luxio uses Bite (normal, targets enemy)
        result1 = battle_turn(emu, move_index=1, target=0)
        assert result1["final_state"] == "WAIT_FOR_PARTNER_ACTION"
        # Machop uses Focus Energy (self-targeting)
        result2 = battle_turn(emu, move_index=2)
        assert result2["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "SWITCH_PROMPT",
            "FAINT_SWITCH", "FAINT_FORCED", "MOVE_LEARN",
        )
        # Bite should always appear; Focus Energy may not if Machop fainted first
        assert_log_contains(result2, "Bite")


class TestAccuracyWarning:
    """Accuracy-drop awareness in battle_turn responses."""

    @retry_on_rng("test_wild_battle_action")
    def test_no_warning_at_normal_accuracy(self, emu: EmulatorClient):
        """No accuracy_warning when Acc stages are neutral."""
        from renegade_mcp.turn import battle_turn
        result = battle_turn(emu, move_index=0)
        assert "accuracy_warning" not in result, (
            f"Should not warn at normal accuracy, got: {result.get('accuracy_warning')}"
        )

    @retry_on_rng("test_wild_battle_action")
    def test_warning_at_minus_2(self, emu: EmulatorClient):
        """accuracy_warning appears when Acc stage is -2."""
        from renegade_mcp.turn import battle_turn

        # Write Acc stage to -2 (raw byte 4 = 6 - 2) on player slot 0
        # BattleMon[0].statBoosts: OFF_STAGES=0x18, skip HP at +0,
        # then Atk+1, Def+2, Spe+3, SpA+4, SpD+5, Acc+6
        acc_addr = 0x022C5774 + 0x18 + 6  # BATTLE_BASE + OFF_STAGES + 6
        emu.write_memory(acc_addr, 4, size="byte")  # raw 4 = stage -2

        result = battle_turn(emu, move_index=0)
        # Warning should appear if final_state is WAIT_FOR_ACTION
        if result["final_state"] == "WAIT_FOR_ACTION":
            assert "accuracy_warning" in result, (
                "Expected accuracy_warning at Acc -2"
            )
            assert "60%" in result["accuracy_warning"], (
                f"Expected 60% hit rate at -2, got: {result['accuracy_warning']}"
            )

    @retry_on_rng("test_wild_battle_action")
    def test_warning_at_minus_3(self, emu: EmulatorClient):
        """accuracy_warning shows correct hit rate at -3."""
        from renegade_mcp.turn import battle_turn

        acc_addr = 0x022C5774 + 0x18 + 6
        emu.write_memory(acc_addr, 3, size="byte")  # raw 3 = stage -3

        result = battle_turn(emu, move_index=0)
        if result["final_state"] == "WAIT_FOR_ACTION":
            assert "accuracy_warning" in result, (
                "Expected accuracy_warning at Acc -3"
            )
            assert "50%" in result["accuracy_warning"], (
                f"Expected 50% hit rate at -3, got: {result['accuracy_warning']}"
            )

    @retry_on_rng("test_wild_battle_action")
    def test_no_warning_at_minus_1(self, emu: EmulatorClient):
        """No warning at Acc -1 (only triggers at -2 or worse)."""
        from renegade_mcp.turn import battle_turn

        acc_addr = 0x022C5774 + 0x18 + 6
        emu.write_memory(acc_addr, 5, size="byte")  # raw 5 = stage -1

        result = battle_turn(emu, move_index=0)
        if result["final_state"] == "WAIT_FOR_ACTION":
            assert "accuracy_warning" not in result, (
                f"Should not warn at -1, got: {result.get('accuracy_warning')}"
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
# QA BUG-002: auto_grind auto-heal stuck on wild FAINT_SWITCH
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
# QA BUG-003: _is_evolution_text_on_screen misses "What?" prompt
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
# QA BUG-004: battle_turn stalls on target-pick after partner KO
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
