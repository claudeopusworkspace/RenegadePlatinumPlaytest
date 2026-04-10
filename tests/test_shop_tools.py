"""Tests for shop tools: buy_item, sell_item.

State-changing UI interaction — retries for menu timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


class TestBuyItem:
    """Purchase items from PokeMart."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_buy_poke_ball(self, emu: EmulatorClient):
        """Buy a Poke Ball — completes without error."""
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        status = read_trainer_status(emu)
        badge_count = status.get("badges") if isinstance(status.get("badges"), int) else None

        # Use the ROM name (Poké Ball with accent)
        result = buy_item(emu, "Poké Ball", quantity=1, badge_count=badge_count)
        assert "error" not in result, f"buy_item error: {result.get('error')}"

    @retry_on_rng("test_eterna_city_overworld")
    def test_buy_quantity(self, emu: EmulatorClient):
        """Buy multiple Potions — money decreases."""
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        status_before = read_trainer_status(emu)
        money_before = status_before["money"]
        badge_count = status_before.get("badges") if isinstance(status_before.get("badges"), int) else None

        result = buy_item(emu, "Potion", quantity=3, badge_count=badge_count)
        assert "error" not in result, f"buy_item error: {result.get('error')}"

        status_after = read_trainer_status(emu)
        assert status_after["money"] < money_before, "Money should have decreased"

    @retry_on_rng("test_eterna_city_overworld")
    def test_item_appears_in_bag(self, emu: EmulatorClient):
        """Bought Potion appears in bag."""
        from renegade_mcp.bag import read_bag
        from renegade_mcp.shop import buy_item
        from renegade_mcp.trainer import read_trainer_status

        bag_before = read_bag(emu)
        potion_count_before = 0
        for p in bag_before:
            for i in p["items"]:
                if i["name"] == "Potion":
                    potion_count_before = i["qty"]

        status = read_trainer_status(emu)
        badge_count = status.get("badges") if isinstance(status.get("badges"), int) else None
        result = buy_item(emu, "Potion", quantity=1, badge_count=badge_count)
        assert "error" not in result, f"buy_item error: {result.get('error')}"

        bag_after = read_bag(emu)
        potion_count_after = 0
        for p in bag_after:
            for i in p["items"]:
                if i["name"] == "Potion":
                    potion_count_after = i["qty"]

        assert potion_count_after == potion_count_before + 1


class TestSellItem:
    """Sell items at PokeMart."""

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_potion(self, emu: EmulatorClient):
        """Sell a Potion — completes without error."""
        from renegade_mcp.shop import sell_item

        result = sell_item(emu, "Potion", quantity=1)
        assert "error" not in result, f"sell_item error: {result.get('error')}"
        assert result["success"] is True

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_money_increases(self, emu: EmulatorClient):
        """Selling an item increases money."""
        from renegade_mcp.shop import sell_item
        from renegade_mcp.trainer import read_trainer_status

        money_before = read_trainer_status(emu)["money"]

        result = sell_item(emu, "Potion", quantity=1)
        assert "error" not in result, f"sell_item error: {result.get('error')}"

        money_after = read_trainer_status(emu)["money"]
        assert money_after > money_before, "Money should have increased"

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_bag_quantity_decreases(self, emu: EmulatorClient):
        """Sold item quantity decreases in bag."""
        from renegade_mcp.bag import read_bag
        from renegade_mcp.shop import sell_item

        bag_before = read_bag(emu)
        potion_before = 0
        for pocket in bag_before:
            for item in pocket["items"]:
                if item["name"] == "Potion":
                    potion_before = item["qty"]

        result = sell_item(emu, "Potion", quantity=1)
        assert "error" not in result, f"sell_item error: {result.get('error')}"

        bag_after = read_bag(emu)
        potion_after = 0
        for pocket in bag_after:
            for item in pocket["items"]:
                if item["name"] == "Potion":
                    potion_after = item["qty"]

        assert potion_after == potion_before - 1

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_quantity_multiple(self, emu: EmulatorClient):
        """Sell 3x Antidote — money increases by 3x sell price."""
        from renegade_mcp.shop import sell_item
        from renegade_mcp.trainer import read_trainer_status

        money_before = read_trainer_status(emu)["money"]

        result = sell_item(emu, "Antidote", quantity=3)
        assert "error" not in result, f"sell_item error: {result.get('error')}"

        money_after = read_trainer_status(emu)["money"]
        # Antidote buy price = 100, sell price = 50, 3x = 150
        assert money_after == money_before + 150, (
            f"Expected +150, got +{money_after - money_before}"
        )

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_key_item_rejected(self, emu: EmulatorClient):
        """Selling a Key Item returns an error."""
        from renegade_mcp.shop import sell_item

        result = sell_item(emu, "Bicycle")
        assert result["success"] is False
        assert "cannot be sold" in result["error"].lower()

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_nonexistent_item(self, emu: EmulatorClient):
        """Selling an item not in bag returns an error."""
        from renegade_mcp.shop import sell_item

        result = sell_item(emu, "Master Ball")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @retry_on_rng("debug_sell_item_mart")
    def test_sell_from_inside_mart(self, emu: EmulatorClient):
        """Sell from inside the mart — no auto-navigation needed."""
        from renegade_mcp.shop import sell_item
        from renegade_mcp.trainer import read_trainer_status

        money_before = read_trainer_status(emu)["money"]
        result = sell_item(emu, "Parlyz Heal", quantity=1)
        assert "error" not in result, f"sell_item error: {result.get('error')}"
        assert result["success"] is True
        assert "navigated_to_mart" not in result, (
            "Should not navigate when already in mart"
        )
        money_after = read_trainer_status(emu)["money"]
        assert money_after > money_before

    @retry_on_rng("test_eterna_city_overworld")
    def test_sell_insufficient_quantity(self, emu: EmulatorClient):
        """Selling more than we have returns an error."""
        from renegade_mcp.shop import sell_item

        result = sell_item(emu, "Parlyz Heal", quantity=999)
        assert result["success"] is False
        assert "not enough" in result["error"].lower()
