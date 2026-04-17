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


# ---------------------------------------------------------------------------
# BUG-003: buy_item Premier Ball bonus breaks next purchase
# ---------------------------------------------------------------------------
# Save state: test_bug003_oreburgh_city_post_event — Oreburgh City overworld,
# 0 badges, has Potions and money for purchases.

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


# ---------------------------------------------------------------------------
# QA BUG-006: buy_item leaves player stuck in shop UI on "How many?" prompt
# ---------------------------------------------------------------------------
# Save state: jubilife_mart_after_buy_5potions — inside Jubilife Mart, player
# in overworld, 0 badges, ¥1,948.

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
