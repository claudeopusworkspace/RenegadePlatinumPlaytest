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
