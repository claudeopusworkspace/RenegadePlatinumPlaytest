"""Tests for shop tools: buy_item.

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
