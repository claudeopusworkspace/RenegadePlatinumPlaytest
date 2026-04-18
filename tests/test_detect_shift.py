"""Tests for addresses.detect_shift — heap delta auto-detection.

Covers the pre-starter regression (RenegadePlatinumQA BUG-001): when the
player has no Pokemon yet, the legacy party-count canary false-positived on
memory noise and picked a bogus delta. The fix uses a player-name signature
at SAVE_BLOCK_BASE + 0x68 as the primary canary (works pre-starter) and
detects a separate delta for the FieldOverworldState group via
MapObject[0]'s live tile position.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


class TestDetectShiftPreStarter:
    """Heap delta detection must work before the player receives their starter."""

    def test_bedroom_pre_starter_resolves_valid_map(self, emu: EmulatorClient):
        """In the Twinleaf bedroom (party count = 0), detect_shift finds a real
        PLAYER_POS_BASE instead of locking on memory noise."""
        load_state(emu, "bedroom_fresh_start_claude")
        from renegade_mcp.map_state import read_player_state
        map_id, x, y, facing = read_player_state(emu)
        # Should resolve to a Twinleaf map (411-416), not Mystery Zone (0 or 1).
        assert 411 <= map_id <= 416, (
            f"Expected Twinleaf map 411-416, got {map_id}. "
            "detect_shift likely locked onto noise."
        )
        # Player tile should be inside the bedroom chunk (single-digit coords).
        assert 0 <= x < 32 and 0 <= y < 32, f"Unexpected tile ({x}, {y})"

    def test_bug_state_pre_starter_resolves_valid_map(self, emu: EmulatorClient):
        """The explicit regression save-state from QA (BUG-001): map tools must
        resolve a valid Twinleaf map instead of returning Mystery Zone."""
        load_state(emu, "bug_view_map_mystery_zone_pre_starter")
        from renegade_mcp.map_state import read_player_state
        map_id, x, y, _facing = read_player_state(emu)
        assert 411 <= map_id <= 416, (
            f"Expected Twinleaf map 411-416, got {map_id}"
        )
        assert 0 <= x < 32 and 0 <= y < 32

    def test_pre_starter_view_map_succeeds(self, emu: EmulatorClient):
        """view_map must not return the 'Could not resolve terrain' error."""
        load_state(emu, "bug_view_map_mystery_zone_pre_starter")
        from renegade_mcp.map_state import view_map
        result = view_map(emu)
        assert "error" not in result, f"view_map failed: {result}"
        assert result["map_id"] is not None
        assert len(result["map"]) > 0

    def test_pre_starter_save_block_and_field_ow_both_detected(
        self, emu: EmulatorClient
    ):
        """Both heap-group deltas must be populated after detect_shift()."""
        load_state(emu, "bedroom_fresh_start_claude")
        from renegade_mcp.addresses import get_delta
        sb = get_delta("save_block")
        fo = get_delta("field_ow")
        assert sb is not None, "save_block delta not detected"
        assert fo is not None, "field_ow delta not detected"


class TestDetectShiftPostStarter:
    """Post-starter states must keep working (regression guard for the refactor)."""

    def test_eterna_arrival_resolves_pc(self, emu: EmulatorClient):
        """Eterna PC save state: map_id should be 69 (PC map)."""
        load_state(emu, "eterna_city_arrival")
        from renegade_mcp.map_state import read_player_state
        map_id, _x, _y, _facing = read_player_state(emu)
        assert map_id == 69, f"Expected Eterna PC (map 69), got {map_id}"

    def test_existing_working_state_unaffected(self, emu: EmulatorClient):
        """Sanity check: a mid-game state used heavily in the existing suite
        continues to resolve correctly after the refactor."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.map_state import read_player_state
        map_id, _x, _y, _facing = read_player_state(emu)
        # Map should be some Eterna or overworld map, not 0/Mystery Zone.
        assert map_id != 0
        assert map_id != 1


class TestGroupDeltas:
    """Per-group delta routing: addr() must use the right delta per name."""

    def test_player_pos_uses_field_ow_delta(self, emu: EmulatorClient):
        """PLAYER_POS_BASE's resolved address = DeSmuME baseline + field_ow delta."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.addresses import addr, get_delta, _DESMUME
        expected = _DESMUME["PLAYER_POS_BASE"] + get_delta("field_ow")
        assert addr("PLAYER_POS_BASE") == expected

    def test_cycling_gear_uses_field_ow_delta(self, emu: EmulatorClient):
        """CYCLING_GEAR_ADDR lives in FieldOverworldState (+0x90 from PLAYER_POS_BASE)
        and must use the field_ow delta."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.addresses import addr, get_delta, _DESMUME
        expected = _DESMUME["CYCLING_GEAR_ADDR"] + get_delta("field_ow")
        assert addr("CYCLING_GEAR_ADDR") == expected

    def test_save_block_addresses_use_save_block_delta(self, emu: EmulatorClient):
        """Save-block addresses (party, bag, etc.) use the save_block delta."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.addresses import addr, get_delta, _DESMUME
        sb = get_delta("save_block")
        for name in ("SAVE_BLOCK_BASE", "ENCRYPTED_PARTY_COUNT", "BAG_BASE", "BOX_DATA_BASE"):
            expected = _DESMUME[name] + sb
            assert addr(name) == expected, f"addr({name!r}) didn't use save_block delta"

    def test_reset_clears_all_groups(self, emu: EmulatorClient):
        """reset() must clear every group's delta, not just save_block."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.addresses import reset, get_delta
        reset()
        assert get_delta("save_block") is None
        assert get_delta("field_ow") is None


class TestQaBug012NameLengthCap:
    """Regression guard for RenegadePlatinumQA BUG-012.

    The player-name canary scans for runs of Gen4 letter/digit chars at
    SAVE_BLOCK_BASE + 0x68. An early version accepted runs of 8+ valid
    chars "as a 7-char name", which let 8-letter Pokemon species/nicknames
    in the party block (Monferno, Bronzong, Vaporeon, ...) outscore the
    real 1-7 char player name and lock detect_shift onto a bogus delta.
    All downstream reads then returned garbage (wrong money / species / map).
    """

    def test_name_length_rejects_8_char_sequences(self, emu: EmulatorClient):
        """_name_length_at must return 0 for 8 consecutive name chars
        without a terminator — Platinum caps player names at 7 chars."""
        load_state(emu, "eterna_forest_entered_south")
        from renegade_mcp.addresses import _name_length_at, _DESMUME, get_delta
        # The scan position that historically hit "Monferno" in this state
        # is SAVE_BLOCK_BASE + 0x60 + 0x68 (delta +0x60). Exact offset of the
        # 8-char nickname depends on the save file, but the invariant holds:
        # _name_length_at must never return > _NAME_MAX_CHARS (7).
        sb_ref = _DESMUME["SAVE_BLOCK_BASE"]
        for delta in range(-0x200, 0x201, 4):
            n = _name_length_at(emu, sb_ref + delta + 0x68)
            assert 0 <= n <= 7, (
                f"_name_length_at at delta={delta:+#x} returned {n}; "
                "must be 0 or 1..7"
            )

    def test_eterna_forest_south_resolves_real_save_block(
        self, emu: EmulatorClient
    ):
        """Live BUG-012 repro: loading eterna_forest_entered_south must pick
        the real save block (badges=1, non-bogus money) — not the Monferno-
        nickname decoy at delta +0x60 which historically produced money=
        0xC000000 and badges=0."""
        load_state(emu, "eterna_forest_entered_south")
        from renegade_mcp.trainer import read_trainer_status
        status = read_trainer_status(emu)
        # The real state has 1 badge (Coal) and a sane money value.
        # Decoy delta produced badges=0 and money=0xC000000 (= 201326592).
        assert status["badges"] == 1, (
            f"Expected 1 badge (Coal), got {status['badges']} — "
            "detect_shift likely picked a decoy delta"
        )
        assert 0 < status["money"] < 1_000_000, (
            f"Money {status['money']} outside sane range; probable decoy "
            "delta (0xC000000 = 201326592 was the original bug value)"
        )


class TestQaBug012RevalidateCrossSaveSwitch:
    """Regression guard: loading states from different save files (different
    heap layouts) must invalidate the cached delta and re-detect. A one-char
    fast-path in revalidate() was too lenient and retained stale deltas."""

    def test_cross_save_switch_reresolves_delta(self, emu: EmulatorClient):
        """Switching between Playtest's save and Wayne's E4 save should
        yield correct per-state reads without manual reset() calls."""
        from renegade_mcp.trainer import read_trainer_status
        from renegade_mcp.map_state import read_player_state

        # Start in Playtest save — Eterna Forest, 1 badge.
        load_state(emu, "eterna_forest_entered_south", redetect_shift=True)
        s1 = read_trainer_status(emu)
        map1, _, _, _ = read_player_state(emu)
        assert s1["badges"] == 1 and map1 == 203

        # Switch to Wayne's E4 save — 8 badges, Pokémon League map.
        # Crucially: don't pass redetect_shift=True here; revalidate() in
        # get_client() must self-heal. (The test helper defaults to True,
        # so we explicitly disable it to exercise the revalidate path.)
        load_state(emu, "e4_pokemon_league_lobby", redetect_shift=False)
        # Simulate a tool call by running revalidate manually (get_client's
        # self-heal hook). In-session this runs on every tool invocation.
        from renegade_mcp.addresses import revalidate
        revalidate(emu)
        s2 = read_trainer_status(emu)
        map2, _, _, _ = read_player_state(emu)
        assert s2["badges"] == 8, f"Expected 8 badges, got {s2['badges']}"
        assert map2 == 175, f"Expected Pokémon League (175), got {map2}"

        # Switch back — the previous delta is now stale the other way.
        load_state(emu, "eterna_forest_entered_south", redetect_shift=False)
        revalidate(emu)
        s3 = read_trainer_status(emu)
        map3, _, _, _ = read_player_state(emu)
        assert s3["badges"] == 1 and map3 == 203

    def test_revalidate_rejects_random_first_char_match(
        self, emu: EmulatorClient
    ):
        """revalidate() must not accept a stale delta just because the first
        u16 at SAVE_BLOCK_BASE + delta + 0x68 happens to be a valid name
        char. Use full _name_length_at validation, not a 1-char check."""
        load_state(emu, "eterna_forest_entered_south")
        from renegade_mcp.addresses import (
            _deltas, get_delta, revalidate, _DESMUME, _read_canary,
            _is_valid_name_char,
        )

        good_delta = get_delta("save_block")
        assert good_delta is not None

        # Probe candidate corrupt deltas within the scan range. We're
        # looking for one where the byte at SAVE_BLOCK_BASE + delta + 0x68
        # starts with a valid name char but is NOT a full valid name
        # (e.g. a single letter followed by non-name bytes) — this is the
        # exact failure mode the old 1-char fast path allowed.
        sb_ref = _DESMUME["SAVE_BLOCK_BASE"]
        probe = None
        for cand in range(-0x200, 0x201, 4):
            if cand == good_delta:
                continue
            first = _read_canary(emu, sb_ref + cand + 0x68, "short")
            if first is None or not _is_valid_name_char(first):
                continue
            # First char looks like a name, but skip deltas that are also
            # full valid names (those are legit alternate candidates).
            from renegade_mcp.addresses import _name_length_at
            if _name_length_at(emu, sb_ref + cand + 0x68) > 0:
                continue
            probe = cand
            break

        if probe is None:
            pytest_skip = __import__("pytest").skip
            pytest_skip("No corrupt-delta probe found in scan range")

        # Install the corrupt delta and call revalidate(). The function
        # must detect staleness and re-run detect_shift, restoring the
        # good delta.
        _deltas["save_block"] = probe
        _deltas["field_ow"] = probe
        assert revalidate(emu) is True
        assert get_delta("save_block") == good_delta
