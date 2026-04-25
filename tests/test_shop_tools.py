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
# Veilstone Department Store
# ---------------------------------------------------------------------------


class TestDeptStoreData:
    """Per-floor cashier inventory tables resolve to known item names."""

    def test_floors_indexed(self):
        from renegade_mcp.shop import DEPT_STORE_CASHIERS, DEPT_STORE_FLOOR_NAMES

        assert set(DEPT_STORE_CASHIERS) == {
            "C07R0201", "C07R0202", "C07R0203", "C07R0207",
        }
        # Floor labels also cover the unsupported interiors so read_shop
        # can speak to them by name.
        assert "C07R0204" in DEPT_STORE_FLOOR_NAMES
        assert "C07R0205" in DEPT_STORE_FLOOR_NAMES

    def test_1f_left_counter_sells_repels(self):
        from renegade_mcp.data import item_names
        from renegade_mcp.shop import DEPT_STORE_CASHIERS

        names = item_names()
        cashier_m = next(c for c in DEPT_STORE_CASHIERS["C07R0201"] if c["x"] == 2)
        sold = {names[i] for i in cashier_m["items"]}
        assert {"Poké Ball", "Great Ball", "Ultra Ball", "Repel", "Max Repel"} <= sold

    def test_1f_right_counter_sells_potions(self):
        from renegade_mcp.data import item_names
        from renegade_mcp.shop import DEPT_STORE_CASHIERS

        names = item_names()
        cashier_f = next(c for c in DEPT_STORE_CASHIERS["C07R0201"] if c["x"] == 3)
        sold = {names[i] for i in cashier_f["items"]}
        assert {"Potion", "Super Potion", "Hyper Potion", "Max Potion", "Revive"} <= sold

    def test_2f_two_cashier_f_disambiguated_by_coords(self):
        from renegade_mcp.shop import DEPT_STORE_CASHIERS

        cashiers = DEPT_STORE_CASHIERS["C07R0202"]
        # Two NPCs share the "Cashier F" name; tile y disambiguates them.
        assert [c["npc"] for c in cashiers] == ["Cashier F", "Cashier F"]
        assert sorted(c["y"] for c in cashiers) == [4, 6]

    def test_3f_top_counter_sells_evolution_stones(self):
        # Renegade Platinum replaces vanilla's TM list with evolution stones.
        from renegade_mcp.data import item_names
        from renegade_mcp.shop import DEPT_STORE_CASHIERS

        top = DEPT_STORE_CASHIERS["C07R0203"][0]
        assert top["x"] == 3 and top["y"] == 4
        sold = {item_names()[i] for i in top["items"]}
        assert {"Fire Stone", "Water Stone", "Leaf Stone"} <= sold

    def test_3f_bottom_counter_sells_special_stones(self):
        # Bottom counter sells the "special" stones; reached via talk-across-
        # counter from (3, 9). view_map BFS calls Cashier M unreachable but
        # `interact_with` has the across-counter fallback.
        from renegade_mcp.data import item_names
        from renegade_mcp.shop import DEPT_STORE_CASHIERS

        bottom = DEPT_STORE_CASHIERS["C07R0203"][1]
        assert bottom["npc"] == "Cashier M"
        assert bottom["x"] == 3 and bottom["y"] == 11
        sold = {item_names()[i] for i in bottom["items"]}
        assert {"Dawn Stone", "Dusk Stone", "Everstone", "Shiny Stone"} <= sold


class TestDeptStoreLookup:
    """_find_dept_store_cashier_for_item routes items to the right counter."""

    def test_finds_potion_on_1f(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        result = _find_dept_store_cashier_for_item("C07R0201", "Potion")
        assert result is not None
        cashier, menu_idx, item_id = result
        assert cashier["npc"] == "Cashier F"
        assert cashier["x"] == 3 and cashier["y"] == 5
        assert menu_idx == 0
        assert item_id == 17

    def test_finds_max_repel_on_1f_other_counter(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        result = _find_dept_store_cashier_for_item("C07R0201", "Max Repel")
        assert result is not None
        cashier, _menu_idx, _item_id = result
        assert cashier["x"] == 2 and cashier["y"] == 5

    def test_case_insensitive(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        assert _find_dept_store_cashier_for_item("C07R0201", "POTION") is not None

    def test_finds_protein_on_2f_middle(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        result = _find_dept_store_cashier_for_item("C07R0202", "Protein")
        assert result is not None
        cashier, menu_idx, _ = result
        assert cashier["y"] == 6
        assert menu_idx == 0

    def test_finds_x_attack_on_2f_top(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        result = _find_dept_store_cashier_for_item("C07R0202", "X Attack")
        assert result is not None
        cashier, _, _ = result
        assert cashier["y"] == 4

    def test_returns_none_for_wrong_floor(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        # Potion is sold on 1F, not 3F (TMs only).
        assert _find_dept_store_cashier_for_item("C07R0203", "Potion") is None

    def test_returns_none_for_unknown_item(self):
        from renegade_mcp.shop import _find_dept_store_cashier_for_item

        assert _find_dept_store_cashier_for_item("C07R0201", "Master Ball") is None


class TestFindNpcAt:
    """_find_npc_at picks the right NPC when multiple share a name."""

    def test_picks_correct_cashier_by_coords(self):
        from renegade_mcp.shop import _find_npc_at

        state = {
            "objects": [
                {"index": 1, "name": "Cashier F", "x": 2, "y": 4},
                {"index": 2, "name": "Cashier F", "x": 2, "y": 6},
                {"index": 3, "name": "Receptionist", "x": 18, "y": 6},
            ]
        }
        north = _find_npc_at(state, "Cashier F", 2, 4)
        south = _find_npc_at(state, "Cashier F", 2, 6)
        assert north is not None and north["index"] == 1
        assert south is not None and south["index"] == 2

    def test_returns_none_when_no_match(self):
        from renegade_mcp.shop import _find_npc_at

        state = {"objects": [{"index": 1, "name": "Cashier F", "x": 2, "y": 4}]}
        assert _find_npc_at(state, "Cashier F", 2, 6) is None
        assert _find_npc_at(state, "Cashier M", 2, 4) is None


class TestReadShopDeptStore:
    """read_shop branch dispatch for dept-store maps and Veilstone overworld."""

    def test_read_dept_store_1f_lists_both_counters(self):
        from renegade_mcp.shop import _read_dept_store

        result = _read_dept_store(map_id=137, code="C07R0201")
        assert result["floor"] == "1F"
        assert result["map_code"] == "C07R0201"
        assert len(result["cashiers"]) == 2
        labels = {c["label"] for c in result["cashiers"]}
        assert "Potions & status healing" in labels
        assert "Balls, repels & mail" in labels
        # Each cashier exposes priced items.
        for c in result["cashiers"]:
            assert all("price" in it and "item_id" in it for it in c["items"])
        assert "Veilstone Dept Store" in result["formatted"]
        assert "1F" in result["formatted"]

    def test_read_dept_store_4f_decoration_message(self):
        from renegade_mcp.shop import _read_dept_store

        result = _read_dept_store(map_id=140, code="C07R0204")
        # 4F is intentionally not in DEPT_STORE_CASHIERS (decoration UI).
        assert result["cashiers"] == []
        assert "decoration" in result["formatted"].lower()

    def test_veilstone_overworld_summary_lists_floors(self):
        from renegade_mcp.shop import (
            VEILSTONE_DEPT_STORE_ENTRANCE,
            _veilstone_overworld_summary,
        )

        result = _veilstone_overworld_summary(map_id=132)
        assert result["dept_store"] is True
        assert result["city_code"] == "C07"
        floors = {c["floor"] for c in result["cashiers"]}
        assert {"1F", "2F", "3F", "B1F"} <= floors
        # Formatted includes the entry-warp coords so the player can navigate.
        ex, ey = VEILSTONE_DEPT_STORE_ENTRANCE
        assert str(ex) in result["formatted"]
        assert str(ey) in result["formatted"]


class TestIsDeptStoreMap:
    """_is_dept_store_map matches Veilstone interior code prefix."""

    def test_matches_dept_store_floors(self):
        from renegade_mcp.shop import _is_dept_store_map

        assert _is_dept_store_map("C07R0201") is True  # 1F
        assert _is_dept_store_map("C07R0207") is True  # B1F

    def test_rejects_other_veilstone_maps(self):
        from renegade_mcp.shop import _is_dept_store_map

        # Veilstone overworld (C07), gym (C07GYM0101), Pokémon Center (C07PC0101)
        # — only C07R02xx is the dept store.
        assert _is_dept_store_map("C07") is False
        assert _is_dept_store_map("C07GYM0101") is False
        assert _is_dept_store_map("C07PC0101") is False
        assert _is_dept_store_map("C07R0101") is False  # Game Corner


# Behavioral tests — drive the actual UI via Wayne's E4 save (8 badges,
# Garchomp can Fly, Veilstone Dept Store reachable from overworld).


class TestDeptStore1F:
    """Cashier F (potions) and Cashier M (balls/repels) on Veilstone Dept 1F."""

    @retry_on_rng("e4_dept_store_1f")
    def test_buy_potion_from_cashier_f(self, emu: EmulatorClient):
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Potion", quantity=1)
        assert result["success"] is True
        assert result["floor"] == "1F"
        assert result["counter"] == "Potions & status healing"
        assert result["money_spent"] == 300

    @retry_on_rng("e4_dept_store_1f")
    def test_buy_repel_from_cashier_m(self, emu: EmulatorClient):
        # Repel sits on the OTHER counter (Cashier M @ 2,5) — verifies that
        # the dept-store cashier dispatch routes to the correct NPC by coords.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Repel", quantity=1)
        assert result["success"] is True
        assert result["counter"] == "Balls, repels & mail"
        assert result["money_spent"] == 350

    @retry_on_rng("e4_dept_store_1f")
    def test_buy_repel_quantity_two(self, emu: EmulatorClient):
        # Regression for the qty>1 bug: dept-store cashier dialog renders
        # text + qty selector on one screen, so the press flow had to drop
        # one A press to avoid silently confirming qty=1.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Repel", quantity=2)
        assert result["success"] is True
        assert result["money_spent"] == 700, (
            f"qty=2 should spend ¥700; spent ¥{result['money_spent']}"
        )


class TestDeptStore2F:
    """2F has two Cashier F NPCs at different tiles (X items vs vitamins)."""

    @retry_on_rng("e4_dept_store_2f")
    def test_buy_x_attack_from_top_counter(self, emu: EmulatorClient):
        # Cashier F at y=4 — must not fall through to the y=6 vitamin counter.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "X Attack", quantity=1)
        assert result["success"] is True
        assert result["counter"] == "Battle X items"
        assert result["money_spent"] == 500

    @retry_on_rng("e4_dept_store_2f")
    def test_buy_protein_from_middle_counter(self, emu: EmulatorClient):
        # Cashier F at y=6 — coord-based dispatch picks this counter, not y=4.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Protein", quantity=1)
        assert result["success"] is True
        assert result["counter"] == "Vitamins (stat boosters)"
        assert result["money_spent"] == 9800


class TestDeptStore3F:
    """3F counters — Renegade replaced both vanilla TM lists with evolution
    stones. Both cashiers are reached via talk-across-counter."""

    @retry_on_rng("e4_dept_store_3f")
    def test_buy_fire_stone(self, emu: EmulatorClient):
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Fire Stone", quantity=1)
        assert result["success"] is True
        assert result["counter"] == "Evolution stones"
        assert result["money_spent"] == 2100

    @retry_on_rng("e4_dept_store_3f")
    def test_buy_dawn_stone_from_bottom_counter(self, emu: EmulatorClient):
        # Cashier M at (3, 11) — reached by walking to (3, 9) and pressing A
        # down through the counter strip. Confirms the across-counter fallback
        # in `interact_with` drives the navigation.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Dawn Stone", quantity=1)
        assert result["success"] is True
        assert result["counter"] == "Special evolution stones"
        assert result["money_spent"] == 2100

    @retry_on_rng("e4_dept_store_3f")
    def test_old_tm_not_available(self, emu: EmulatorClient):
        # Vanilla 3F sold TM83 — Renegade replaced the inventory.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "TM83", quantity=1)
        assert result["success"] is False
        assert "not sold" in result["error"].lower()


class TestDeptStoreB1F:
    """B1F berry vendor — only the berry counter is automated; lava-cookie
    and poffin counters use custom UIs and aren't supported."""

    @retry_on_rng("e4_dept_store_b1f")
    def test_buy_figy_berry(self, emu: EmulatorClient):
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Figy Berry", quantity=1)
        assert result["success"] is True
        assert result["counter"] == "Berries"
        assert result["money_spent"] == 20


class TestVeilstoneOverworldShopping:
    """Auto-navigation from city overworld → Dept Store 1F → buy."""

    @retry_on_rng("e4_veilstone_city_overworld")
    def test_read_shop_returns_dept_store_summary(self, emu: EmulatorClient):
        from renegade_mcp.shop import read_shop

        result = read_shop(emu)
        assert result["dept_store"] is True
        floors = {c["floor"] for c in result["cashiers"]}
        assert {"1F", "2F", "3F", "B1F"} <= floors

    @retry_on_rng("e4_veilstone_city_overworld")
    def test_buy_from_overworld_auto_warps_to_1f(self, emu: EmulatorClient):
        # Auto-nav: walks to entrance warp at (701, 603), enters 1F, finds
        # Cashier F, buys Potion. Single round-trip.
        from renegade_mcp.shop import buy_item

        result = buy_item(emu, "Potion", quantity=1)
        assert result["success"] is True
        assert result.get("navigated_to_mart") is True
        assert result["floor"] == "1F"
        assert result["money_spent"] == 300


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
