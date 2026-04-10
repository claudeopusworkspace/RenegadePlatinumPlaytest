"""Tests for bicycle features: use_key_item, cycling state, bike-aware navigation.

State-changing menu interactions — retries for UI timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


# ---------------------------------------------------------------------------
# use_key_item — Bicycle mount/dismount
# ---------------------------------------------------------------------------

class TestUseKeyItemBicycle:
    """Mount and dismount the Bicycle via use_key_item."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_mount_bicycle(self, emu: EmulatorClient):
        """Mounting bicycle outdoors sets on_bicycle=True."""
        from renegade_mcp.use_item import use_key_item

        result = use_key_item(emu, "Bicycle")
        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result["on_bicycle"] is True
        assert "Mounted" in result["formatted"]

    @retry_on_rng("test_eterna_city_overworld")
    def test_dismount_bicycle(self, emu: EmulatorClient):
        """Mounting then dismounting toggles back to walking."""
        from renegade_mcp.use_item import use_key_item

        mount = use_key_item(emu, "Bicycle")
        assert mount.get("success") is True

        dismount = use_key_item(emu, "Bicycle")
        assert dismount.get("success") is True, f"Dismount failed: {dismount}"
        assert dismount["on_bicycle"] is False
        assert "Dismounted" in dismount["formatted"]

    def test_bicycle_indoors_rejected(self, emu: EmulatorClient):
        """Using bicycle indoors returns error and cleans up menus."""
        load_state(emu, "eterna_city_post_gardenia_team_updated")  # inside PC
        from renegade_mcp.use_item import use_key_item

        result = use_key_item(emu, "Bicycle")
        assert result.get("success") is False
        assert "error" in result
        assert "indoors" in result["error"].lower() or "didn't change" in result["error"].lower()

    def test_nonexistent_key_item_rejected(self, emu: EmulatorClient):
        """Using a key item not in the bag returns error."""
        load_state(emu, "eterna_city_post_gardenia_team_updated")
        from renegade_mcp.use_item import use_key_item

        result = use_key_item(emu, "Super Rod")
        assert result.get("success") is False
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_unsupported_key_item_rejected(self, emu: EmulatorClient):
        """Using an unsupported key item (Town Map) returns error."""
        load_state(emu, "eterna_city_post_gardenia_team_updated")
        from renegade_mcp.use_item import use_key_item

        result = use_key_item(emu, "Town Map")
        assert result.get("success") is False
        assert "error" in result
        assert "not yet supported" in result["error"].lower()


# ---------------------------------------------------------------------------
# CYCLING_GEAR_ADDR — memory read
# ---------------------------------------------------------------------------

class TestCyclingGearAddr:
    """Verify CYCLING_GEAR_ADDR reflects bicycle state."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_cycling_gear_off_when_walking(self, emu: EmulatorClient):
        """CYCLING_GEAR_ADDR is 0 when walking."""
        from renegade_mcp.addresses import addr

        cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling == 0, f"Expected 0 (walking), got {cycling}"

    @retry_on_rng("test_eterna_city_overworld")
    def test_cycling_gear_on_after_mount(self, emu: EmulatorClient):
        """CYCLING_GEAR_ADDR is 1 after mounting bicycle."""
        from renegade_mcp.addresses import addr
        from renegade_mcp.use_item import use_key_item

        use_key_item(emu, "Bicycle")
        cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
        assert cycling == 1, f"Expected 1 (cycling), got {cycling}"


# ---------------------------------------------------------------------------
# read_trainer_status — on_bicycle field
# ---------------------------------------------------------------------------

class TestTrainerStatusBicycle:
    """read_trainer_status includes bicycle state."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_on_bicycle_false_when_walking(self, emu: EmulatorClient):
        """on_bicycle is False when walking."""
        from renegade_mcp.trainer import read_trainer_status

        status = read_trainer_status(emu)
        assert status["on_bicycle"] is False

    @retry_on_rng("test_eterna_city_overworld")
    def test_on_bicycle_true_when_cycling(self, emu: EmulatorClient):
        """on_bicycle is True after mounting bicycle."""
        from renegade_mcp.trainer import read_trainer_status
        from renegade_mcp.use_item import use_key_item

        use_key_item(emu, "Bicycle")
        status = read_trainer_status(emu)
        assert status["on_bicycle"] is True
        assert "Bicycle: ON" in status["formatted"]


# ---------------------------------------------------------------------------
# Bike-aware navigation timing
# ---------------------------------------------------------------------------

class TestBikeNavigation:
    """Navigation uses correct hold frames based on bicycle state."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_navigate_walk_precise(self, emu: EmulatorClient):
        """Walking navigate moves exactly the requested tiles."""
        from renegade_mcp.map_state import read_player_state
        from renegade_mcp.navigation import navigate_manual

        _, x_before, y_before, _ = read_player_state(emu)
        result = navigate_manual(emu, "d5")
        _, x_after, y_after, _ = read_player_state(emu)
        assert y_after == y_before + 5, (
            f"Walk: expected y+5={y_before + 5}, got {y_after}"
        )
        assert x_after == x_before

    @retry_on_rng("test_eterna_city_overworld")
    def test_navigate_bike_precise(self, emu: EmulatorClient):
        """Biking navigate moves exactly the requested tiles (no overshoot)."""
        from renegade_mcp.map_state import read_player_state
        from renegade_mcp.navigation import navigate_manual
        from renegade_mcp.use_item import use_key_item

        use_key_item(emu, "Bicycle")
        _, x_before, y_before, _ = read_player_state(emu)
        result = navigate_manual(emu, "d5")
        _, x_after, y_after, _ = read_player_state(emu)
        assert y_after == y_before + 5, (
            f"Bike: expected y+5={y_before + 5}, got {y_after}"
        )
        assert x_after == x_before

    @retry_on_rng("test_eterna_city_overworld")
    def test_navigate_to_bike_no_repaths(self, emu: EmulatorClient):
        """navigate_to on bike reaches target with 0 repaths."""
        from renegade_mcp.map_state import read_player_state
        from renegade_mcp.navigation import navigate_to
        from renegade_mcp.use_item import use_key_item

        use_key_item(emu, "Bicycle")
        _, _, y_before, _ = read_player_state(emu)
        target_y = y_before + 8
        result = navigate_to(emu, 305, target_y)
        assert "error" not in result, f"navigate_to error: {result.get('error')}"
        assert result.get("repaths", 0) == 0, (
            f"Expected 0 repaths on bike, got {result.get('repaths')}"
        )
        _, _, y_after, _ = read_player_state(emu)
        assert y_after == target_y, (
            f"Expected y={target_y}, got {y_after}"
        )

    @retry_on_rng("test_eterna_city_overworld")
    def test_get_move_hold_walking(self, emu: EmulatorClient):
        """_get_move_hold returns 16 when walking."""
        from renegade_mcp.navigation import _get_move_hold, HOLD_FRAMES

        hold = _get_move_hold(emu)
        assert hold == HOLD_FRAMES == 16

    @retry_on_rng("test_eterna_city_overworld")
    def test_get_move_hold_cycling(self, emu: EmulatorClient):
        """_get_move_hold returns BIKE_HOLD_FRAMES when cycling."""
        from renegade_mcp.navigation import _get_move_hold, BIKE_HOLD_FRAMES
        from renegade_mcp.use_item import use_key_item

        use_key_item(emu, "Bicycle")
        hold = _get_move_hold(emu)
        assert hold == BIKE_HOLD_FRAMES == 4
