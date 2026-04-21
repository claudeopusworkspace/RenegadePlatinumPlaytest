"""Tests for party tools: read_party, format_party, reorder_party, heal_party.

State-changing UI interactions — retries for menu timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# read_party: fainted Pokemon HP (BUG-004 regression)
# ---------------------------------------------------------------------------

class TestFaintedPokemonHP:
    """Fainted Pokemon should show hp=0, not hp=-1.

    Regression: `decoded.get("ext_cur_hp", 0) or -1` treated 0 as falsy.
    """

    def test_format_party_fainted_shows_zero_hp(self, emu: EmulatorClient):
        """format_party renders hp=0 as 'HP 0/66', not 'HP ?/?'."""
        from renegade_mcp.party import format_party

        fainted_party = [{
            "slot": 0,
            "name": "Prinplup",
            "level": 22,
            "hp": 0,
            "max_hp": 66,
            "shiny": False,
            "nature": "Lax",
            "ability": "Vital Spirit",
            "status_conditions": [],
            "moves": [{"name": "Bubble Beam", "pp": 15}],
            "partial": False,
        }]
        output = format_party(fainted_party)
        assert "HP 0/66" in output, f"Expected 'HP 0/66', got: {output}"
        assert "HP ?/?" not in output, f"Should not show 'HP ?/?': {output}"

    def test_format_party_fainted_shows_fainted_status(self, emu: EmulatorClient):
        """format_party adds Fainted indicator when hp=0."""
        from renegade_mcp.party import format_party

        fainted_party = [{
            "slot": 0,
            "name": "Prinplup",
            "level": 22,
            "hp": 0,
            "max_hp": 66,
            "shiny": False,
            "nature": "Lax",
            "ability": "Vital Spirit",
            "status_conditions": [],
            "moves": [{"name": "Bubble Beam", "pp": 15}],
            "partial": False,
        }]
        output = format_party(fainted_party)
        assert "Fainted" in output, f"Expected 'Fainted' in output: {output}"

    def test_read_party_hp_never_negative(self, emu: EmulatorClient):
        """read_party should never return hp=-1 for any Pokemon."""
        load_state(emu, "test_damaged_party_overworld")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        for mon in party:
            assert mon["hp"] >= 0, (
                f"{mon['name']} has hp={mon['hp']} — should never be negative"
            )
            assert mon["max_hp"] >= 0, (
                f"{mon['name']} has max_hp={mon['max_hp']} — should never be negative"
            )
            assert mon["level"] >= 0, (
                f"{mon['name']} has level={mon['level']} — should never be negative"
            )


# ---------------------------------------------------------------------------
# reorder_party
# ---------------------------------------------------------------------------

class TestReorderParty:
    """Swap party Pokemon via pause menu."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_swap_slots(self, emu: EmulatorClient):
        """Swap slot 0 (Luxio) and slot 2 (Grotle) — species move."""
        from renegade_mcp.party import read_party
        from renegade_mcp.reorder_party import reorder_party

        party_before = read_party(emu)
        name_0 = party_before[0]["name"]
        name_2 = party_before[2]["name"]

        result = reorder_party(emu, 0, 2)
        assert "error" not in result

        party_after = read_party(emu)
        assert party_after[0]["name"] == name_2, (
            f"Slot 0 should be {name_2}, got {party_after[0]['name']}"
        )
        assert party_after[2]["name"] == name_0, (
            f"Slot 2 should be {name_0}, got {party_after[2]['name']}"
        )

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_swap_preserves_data(self, emu: EmulatorClient):
        """Swap preserves Pokemon data (level, moves, etc.)."""
        from renegade_mcp.party import read_party
        from renegade_mcp.reorder_party import reorder_party

        party_before = read_party(emu)
        level_0 = party_before[0]["level"]
        moves_0 = party_before[0]["move_names"]

        reorder_party(emu, 0, 2)

        party_after = read_party(emu)
        # Old slot 0 data should now be at slot 2
        assert party_after[2]["level"] == level_0
        assert party_after[2]["move_names"] == moves_0

    def test_swap_when_source_knows_field_move(self, emu: EmulatorClient):
        """Source Pokemon knows a field move (Cut) — sub-menu row for Switch
        is pushed down by 1. Repro for the bug where reorder_party silently
        reported success while nothing actually swapped.
        """
        from renegade_mcp.party import read_party
        from renegade_mcp.reorder_party import reorder_party
        from renegade_mcp.party_submenu import FIELD_MOVES

        load_state(emu, "bug_reorder_party_fails_silently_with_field_move")

        party_before = read_party(emu)
        assert len(party_before) > 3, "Save state should have >=4 Pokemon"

        # Confirm the precondition the bug depends on: slot 0 knows at least
        # one field move. If this ever changes, update the save state.
        slot0_moves = [m.lower() for m in party_before[0]["move_names"]]
        assert any(m in FIELD_MOVES for m in slot0_moves), (
            f"Slot 0 ({party_before[0]['name']}) must know a field move for "
            f"this regression test to exercise the bug. Moves: {slot0_moves}"
        )

        species_0 = party_before[0]["species_id"]
        species_3 = party_before[3]["species_id"]
        assert species_0 != species_3, "Slots must hold different species"

        result = reorder_party(emu, 0, 3)

        assert result.get("success") is True, (
            f"reorder_party should succeed; got: {result.get('formatted')}"
        )

        party_after = read_party(emu)
        assert party_after[0]["species_id"] == species_3, (
            f"Slot 0 should hold species {species_3}, got {party_after[0]['species_id']}"
        )
        assert party_after[3]["species_id"] == species_0, (
            f"Slot 3 should hold species {species_0}, got {party_after[3]['species_id']}"
        )


# ---------------------------------------------------------------------------
# heal_party
# ---------------------------------------------------------------------------

class TestHealParty:
    """Heal at Pokemon Center."""

    @retry_on_rng("debug_heal_party_dialogue_stuck")
    def test_heal_damaged_party(self, emu: EmulatorClient):
        """Heal party at Pokemon Center — completes without error."""
        from renegade_mcp.heal_party import heal_party

        result = heal_party(emu)
        assert "error" not in result

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_heal_already_healed(self, emu: EmulatorClient):
        """Healing already-healed party completes without error."""
        from renegade_mcp.heal_party import heal_party
        result = heal_party(emu)
        assert "error" not in result

    @retry_on_rng("debug_heal_party_dialogue_stuck")
    def test_heal_from_inside_pc(self, emu: EmulatorClient):
        """Heal from inside Pokemon Center building."""
        from renegade_mcp.heal_party import heal_party
        result = heal_party(emu)
        assert "error" not in result


# ---------------------------------------------------------------------------
# QA BUG-010: read_party reports garbled max_hp for freshly-loaded savestates
# ---------------------------------------------------------------------------
# read_party reports garbled max_hp for freshly-loaded savestates where a slot
# contains a previously-PC-round-tripped Pokémon. The extension bytes are
# captured mid-recompute: the first 8 bytes (status/level/cur_hp) are in one
# encryption state while the next 2 bytes (max_hp) are in the opposite state.
# Neither "fully primary" nor "fully secondary" passes _ext_sane, so the old
# fallback returned primary's garbage max_hp (e.g. 37988 for Shinx slot 3).
# Fix: field-level composition picks the sane value for each field.
#
# Save state: eterna_forest_entered_south — pre-first-battle savestate with
# PC-round-tripped Shinx in slot 3.

class TestQaBug010MaxHpMixedStateRecovery:
    """_resolve_party_extension composes field-by-field when neither source
    is fully sane, so max_hp in a mixed-encryption slot reads correctly."""

    def test_mixed_state_field_composition(self):
        """Unit: craft an extension buffer with level/hp plaintext at bytes
        0-7 and a sane max_hp at bytes 8-9. The composer picks max_hp from
        whichever source has a sane range and level/hp from the other."""
        import struct
        from renegade_mcp.party import _prng_decrypt, _resolve_party_extension

        # Fake PID for PRNG stream
        pid = 0xE01037C3
        # Build a plaintext extension: level=6, cur_hp=21, max_hp=21.
        plain = bytearray(100)
        struct.pack_into("<I", plain, 0, 0)  # status 0
        plain[4] = 6                          # level 6
        struct.pack_into("<H", plain, 6, 21)  # cur_hp 21
        struct.pack_into("<H", plain, 8, 21)  # max_hp 21

        # Simulate the observed mixed state: bytes 0-7 are encrypted (the
        # PRNG-XOR of plain), bytes 8+ are plaintext. Applying _prng_decrypt
        # again on the header flips it back; bytes 8+ become garbage.
        enc_header = _prng_decrypt(bytes(plain[:8]), pid)
        mixed = bytearray(enc_header) + plain[8:]

        # `flag_says_decrypted=False` because flags == 0 (what the live
        # Shinx save reported). Primary = prng_decrypt(mixed) — header
        # recovers, tail garbles. Secondary = mixed — header garbage, tail
        # (max_hp @ 8) plaintext.
        status, level, cur_hp, max_hp = _resolve_party_extension(
            bytes(mixed), pid, flag_says_decrypted=False
        )
        assert level == 6, f"level compose: got {level}"
        assert cur_hp == 21, f"cur_hp compose: got {cur_hp}"
        assert max_hp == 21, f"max_hp compose: got {max_hp} (expected 21 from raw tail)"

    def test_shinx_slot_reads_21_21_on_fresh_load(self, emu: EmulatorClient):
        """Integration: loading `eterna_forest_entered_south` (a pre-first-
        battle savestate with PC-round-tripped Shinx in slot 3) returns
        Shinx's max_hp as 21, matching the in-game party menu."""
        from renegade_mcp.party import read_party
        load_state(emu, "eterna_forest_entered_south")

        party = read_party(emu)
        shinx = next((p for p in party if p["name"] == "Shinx"), None)
        assert shinx is not None, f"Shinx not in party: {[p['name'] for p in party]}"
        assert shinx["level"] == 6, f"Shinx level: {shinx['level']}"
        assert shinx["hp"] == 21, f"Shinx hp: {shinx['hp']}"
        assert shinx["max_hp"] == 21, (
            f"Shinx max_hp: {shinx['max_hp']} — expected 21 "
            "(BUG-010 regression: mixed-state extension read)"
        )

    def test_other_slots_unaffected_on_fresh_load(self, emu: EmulatorClient):
        """Sanity: the mixed-state recovery path doesn't corrupt already-sane
        slots. Monferno/Vaporeon/Burmy still read at their expected values."""
        from renegade_mcp.party import read_party
        load_state(emu, "eterna_forest_entered_south")

        party = read_party(emu)
        expected = {
            "Monferno": {"level": 27, "max_hp": 82},
            "Vaporeon": {"level": 16, "max_hp": 72},
            "Burmy": {"level": 18, "max_hp": 45},
        }
        for name, wants in expected.items():
            mon = next((p for p in party if p["name"] == name), None)
            assert mon is not None, f"{name} missing from party"
            assert mon["level"] == wants["level"], (
                f"{name} level: got {mon['level']}, expected {wants['level']}"
            )
            assert mon["max_hp"] == wants["max_hp"], (
                f"{name} max_hp: got {mon['max_hp']}, expected {wants['max_hp']}"
            )


# ---------------------------------------------------------------------------
# QA BUG-015 — read_party battle enrichment (UI slot / role / live HP)
# ---------------------------------------------------------------------------
# Pre-fix: read_party returned the persistent party slot order with stale
# HP during battle, with no signal that the UI ordering had been remapped
# by BattleContext.partyOrder. Callers had to consult battle_turn's
# enriched party array to learn where each mon sat in the battle grid.
# Fix: read_party now adds `battle_ui_slot`, `battle_role`, and refreshes
# the active battler's hp/status from the BattleMon struct.

class TestQaBug015ReadPartyBattleEnrichment:
    """Battle enrichment fields on read_party."""

    def test_overworld_read_party_has_no_battle_fields(
        self, emu: EmulatorClient
    ):
        """Outside battle there's no partyOrder to read — read_party must
        not invent battle_ui_slot/battle_role fields."""
        from renegade_mcp.party import read_party
        load_state(emu, "qa_session12_route216_entry")

        party = read_party(emu)
        assert party, "Expected non-empty party from session12 save"
        for p in party:
            assert "battle_ui_slot" not in p, (
                f"Overworld read leaked battle_ui_slot on {p['name']!r}: "
                f"{p.get('battle_ui_slot')}"
            )
            assert "battle_role" not in p, (
                f"Overworld read leaked battle_role on {p['name']!r}"
            )

    def test_in_battle_read_party_tags_active_and_bench(
        self, emu: EmulatorClient
    ):
        """After switching Vaporeon in vs Ace Trainer Blake, read_party must
        tag Vaporeon (persistent slot 1) as battle_ui_slot=0/role=active
        and Monferno (persistent slot 0) as battle_ui_slot=1/role=bench —
        matching the post-switch partyOrder [1,0,...]."""
        from renegade_mcp.party import read_party
        from renegade_mcp.interaction import interact_with
        from renegade_mcp.turn import battle_turn

        load_state(emu, "qa_session12_route216_entry")
        enc = interact_with(emu, object_index=1)
        assert enc.get("encounter", {}).get("encounter") == "battle"

        switch = battle_turn(emu, switch_to=1)
        assert switch["final_state"] == "WAIT_FOR_ACTION"

        party = read_party(emu)
        by_name = {p["name"]: p for p in party}

        vap = by_name.get("Vaporeon")
        mon = by_name.get("Monferno")
        assert vap is not None and mon is not None, (
            f"Expected Vaporeon + Monferno in party: {[p['name'] for p in party]}"
        )
        # Persistent slot numbers remain the same (stable identifier).
        assert vap["slot"] == 1, f"Vaporeon persistent slot: {vap['slot']}"
        assert mon["slot"] == 0, f"Monferno persistent slot: {mon['slot']}"
        # UI slot must flip post-switch.
        assert vap["battle_ui_slot"] == 0, (
            f"Vaporeon battle_ui_slot: {vap['battle_ui_slot']} (expected 0 "
            f"— active after switch_to=1)"
        )
        assert mon["battle_ui_slot"] == 1, (
            f"Monferno battle_ui_slot: {mon['battle_ui_slot']} (expected 1 "
            f"— bench after switch_to=1)"
        )
        # Roles reflect on-field status.
        assert vap["battle_role"] == "active"
        assert mon["battle_role"] == "bench"

    def test_in_battle_active_hp_is_live_not_stale(
        self, emu: EmulatorClient
    ):
        """The active battler's HP in read_party must match the BattleMon
        struct — the pre-BUG-015 bug surfaced the stale party-block HP."""
        from renegade_mcp.party import read_party
        from renegade_mcp.interaction import interact_with
        from renegade_mcp.turn import battle_turn
        from renegade_mcp.battle import read_battle

        load_state(emu, "qa_session12_route216_entry")
        enc = interact_with(emu, object_index=1)
        assert enc.get("encounter", {}).get("encounter") == "battle"

        # Switch in Vaporeon so Porygon's free Charge Beam hits her.
        switch = battle_turn(emu, switch_to=1)
        assert switch["final_state"] == "WAIT_FOR_ACTION"

        battlers = read_battle(emu)
        active = next((b for b in battlers if b.get("side") == "player"
                       and b.get("slot") == 0), None)
        assert active is not None, "No player-active battler"
        live_hp = active["hp"]

        party = read_party(emu)
        vap = next((p for p in party if p["name"] == "Vaporeon"), None)
        assert vap is not None and vap["battle_role"] == "active"
        assert vap["hp"] == live_hp, (
            f"BUG-015 regression: active Vaporeon read_party hp={vap['hp']}, "
            f"BattleMon hp={live_hp}."
        )

    def test_in_battle_formatted_shows_ui_slot_and_role(
        self, emu: EmulatorClient
    ):
        """format_party's output must surface battle_ui_slot + role when the
        entries carry them — callers and users rely on the formatted
        string for quick disambiguation."""
        from renegade_mcp.party import read_party, format_party
        from renegade_mcp.interaction import interact_with
        from renegade_mcp.turn import battle_turn

        load_state(emu, "qa_session12_route216_entry")
        enc = interact_with(emu, object_index=1)
        assert enc.get("encounter", {}).get("encounter") == "battle"
        battle_turn(emu, switch_to=1)

        party = read_party(emu)
        formatted = format_party(party)
        assert "[in battle" in formatted, (
            f"Expected in-battle header in formatted output:\n{formatted}"
        )
        assert "UI 0 · active" in formatted, (
            f"Expected 'UI 0 · active' label on active battler:\n{formatted}"
        )
        assert "UI 1 · bench" in formatted, (
            f"Expected 'UI 1 · bench' on the swapped-out mon:\n{formatted}"
        )


# ---------------------------------------------------------------------------
# QA BUG-023: is_egg flag in read_party (prerequisite for egg-hatch classifier)
# ---------------------------------------------------------------------------

class TestIsEggFlag:
    """read_party exposes is_egg, extracted from Block B bit 30 of the IV u32."""

    @retry_on_rng("route206_pre_togepi_hatch")
    def test_is_egg_true_for_unhatched_egg(self, emu: EmulatorClient):
        """Togepi egg in slot 5 should report is_egg=True."""
        from renegade_mcp.party import read_party

        result = read_party(emu)
        members = result if isinstance(result, list) else result["party"]
        slot5 = next(m for m in members if m["slot"] == 5)
        assert slot5.get("is_egg") is True, (
            f"Expected is_egg=True for Togepi egg, got: {slot5}"
        )

    @retry_on_rng("route206_pre_togepi_hatch")
    def test_is_egg_false_for_regular_pokemon(self, emu: EmulatorClient):
        """Non-egg party members should report is_egg=False."""
        from renegade_mcp.party import read_party

        result = read_party(emu)
        members = result if isinstance(result, list) else result["party"]
        for member in members:
            if member["slot"] == 5:
                continue  # Togepi egg — skip
            assert member.get("is_egg") is False, (
                f"Expected is_egg=False for slot {member['slot']} "
                f"({member['name']}), got: {member.get('is_egg')}"
            )
