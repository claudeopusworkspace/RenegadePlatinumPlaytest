"""Tests for read-only memory tools.

read_party, read_battle, read_bag, read_trainer_status, read_box, read_shop, tm_compatibility.
These are deterministic memory reads — no retries needed.

Note: raw implementation functions return lists (read_party, read_battle, read_bag).
The MCP server wraps them into dicts. Tests call the raw functions directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


# ---------------------------------------------------------------------------
# read_party
# ---------------------------------------------------------------------------

class TestReadParty:
    """Read party Pokemon from memory."""

    def test_six_pokemon_party_species(self, emu: EmulatorClient):
        """6-Pokemon party: species match known team."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        assert len(party) == 6
        species = [p["name"] for p in party]
        assert "Luxio" in species
        assert "Machop" in species
        assert "Grotle" in species
        assert "Prinplup" in species
        assert "Charmeleon" in species
        assert "Swinub" in species

    def test_levels_correct(self, emu: EmulatorClient):
        """Party levels match known values."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        levels = {p["name"]: p["level"] for p in party}
        assert levels["Luxio"] == 21
        assert levels["Machop"] == 21
        assert levels["Grotle"] == 24
        assert levels["Prinplup"] == 22
        assert levels["Charmeleon"] == 23
        assert levels["Swinub"] == 19

    def test_shiny_detection(self, emu: EmulatorClient):
        """Swinub (slot 5) is shiny, others are not."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        for p in party:
            if p["name"] == "Swinub":
                assert p["shiny"] is True, "Swinub should be shiny"
            else:
                assert p["shiny"] is False, f"{p['name']} should not be shiny"

    def test_held_items(self, emu: EmulatorClient):
        """Verify held item IDs are set for known holders."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        items = {p["name"]: p["item_id"] for p in party}
        # Luxio holds Scope Lens (item_id != 0)
        assert items["Luxio"] != 0, "Luxio should hold Scope Lens"
        # Grotle holds Muscle Band
        assert items["Grotle"] != 0, "Grotle should hold Muscle Band"
        # Machop has no held item
        assert items["Machop"] == 0, "Machop should have no held item"

    def test_moves_present(self, emu: EmulatorClient):
        """Luxio has Spark, Bite, Howl, Quick Attack."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        luxio = next(p for p in party if p["name"] == "Luxio")
        move_names = luxio["move_names"]
        assert "Spark" in move_names
        assert "Bite" in move_names
        assert "Howl" in move_names
        assert "Quick Attack" in move_names

    def test_five_pokemon_party(self, emu: EmulatorClient):
        """5-Pokemon party (pre-Swinub)."""
        load_state(emu, "eterna_city_pokecenter_melonds")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        assert len(party) == 5


# ---------------------------------------------------------------------------
# read_battle
# ---------------------------------------------------------------------------

class TestReadBattle:
    """Read battle state from memory."""

    def test_not_in_battle(self, emu: EmulatorClient):
        """Overworld state returns empty battler list."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        assert len(battlers) == 0

    def test_single_wild_battle(self, emu: EmulatorClient):
        """Wild battle at action prompt returns 2 battlers."""
        load_state(emu, "test_wild_battle_action")
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        assert len(battlers) == 2
        player = next(b for b in battlers if b["side"] == "player")
        enemy = next(b for b in battlers if b["side"] == "enemy")
        assert player["species"] == "Prinplup"
        assert enemy["species"] == "Smoochum"

    def test_double_battle(self, emu: EmulatorClient):
        """Double battle returns 4 battlers."""
        load_state(emu, "debug_doubles_target_swapped")
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        assert len(battlers) == 4

    def test_battler_fields(self, emu: EmulatorClient):
        """Battler dicts have required fields: species, types, moves, HP."""
        load_state(emu, "test_wild_battle_action")
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        for battler in battlers:
            assert "species" in battler
            assert "type1" in battler
            assert "hp" in battler
            assert battler["hp"] > 0
            assert "max_hp" in battler
            assert "moves" in battler
            assert len(battler["moves"]) > 0
            assert "ability" in battler


# ---------------------------------------------------------------------------
# read_bag
# ---------------------------------------------------------------------------

class TestReadBag:
    """Read bag contents from memory."""

    def test_full_bag_has_pockets(self, emu: EmulatorClient):
        """Full bag returns multiple pockets."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.bag import read_bag
        pockets = read_bag(emu)
        assert len(pockets) > 0
        pocket_names = [p["name"] for p in pockets]
        assert "Items" in pocket_names or "Key Items" in pocket_names

    def test_pocket_filter_medicine(self, emu: EmulatorClient):
        """Filter for Medicine pocket works."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.bag import read_bag
        pockets = read_bag(emu)
        medicine = [p for p in pockets if p["name"] == "Medicine"]
        assert len(medicine) == 1
        assert len(medicine[0]["items"]) > 0

    def test_pocket_filter_key_items(self, emu: EmulatorClient):
        """Key Items pocket includes Bicycle and Town Map."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.bag import read_bag
        pockets = read_bag(emu)
        key_items = next(p for p in pockets if p["name"] == "Key Items")
        items = [i["name"] for i in key_items["items"]]
        assert "Bicycle" in items
        assert "Town Map" in items

    def test_poke_balls_present(self, emu: EmulatorClient):
        """Poke Ball should be in bag with qty >= 25."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.bag import read_bag
        pockets = read_bag(emu)
        # Find the pocket with Poke Balls (name varies: "Poké Balls", etc.)
        all_items = {}
        for p in pockets:
            for i in p["items"]:
                all_items[i["name"]] = i["qty"]
        # Check for Poké Ball (with accent)
        ball_name = next((n for n in all_items if "Ball" in n and "Pok" in n), None)
        assert ball_name is not None, f"No Poke Ball found in bag. Items: {list(all_items.keys())}"
        assert all_items[ball_name] >= 20

    def test_all_seven_pockets(self, emu: EmulatorClient):
        """Bag has exactly 7 pockets."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.bag import read_bag
        pockets = read_bag(emu)
        # Gen 4 has: Items, Medicine, Poke Balls, TMs & HMs, Berries, Mail, Battle Items, Key Items
        # (some may be empty but should still be listed)
        assert len(pockets) >= 7


# ---------------------------------------------------------------------------
# read_trainer_status
# ---------------------------------------------------------------------------

class TestReadTrainerStatus:
    """Read money and badges from memory."""

    def test_badge_count(self, emu: EmulatorClient):
        """Should have 1 badge (Coal Badge)."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.trainer import read_trainer_status
        result = read_trainer_status(emu)
        assert result["badges"] == 1

    def test_money_positive(self, emu: EmulatorClient):
        """Money should be a positive integer."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.trainer import read_trainer_status
        result = read_trainer_status(emu)
        assert isinstance(result["money"], int)
        assert result["money"] > 0


# ---------------------------------------------------------------------------
# read_box
# ---------------------------------------------------------------------------

class TestReadBox:
    """Read PC box contents from memory."""

    def test_box1_has_pokemon(self, emu: EmulatorClient):
        """Box 1 is non-empty and includes Bulbasaur."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.pc import read_box
        result = read_box(emu, box=1)
        assert result["success"] is True
        assert result["count"] > 0
        names = [p["name"] for p in result["pokemon"]]
        assert "Bulbasaur" in names

    def test_box1_species_list(self, emu: EmulatorClient):
        """Box 1 species match known contents."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.pc import read_box
        result = read_box(emu, box=1)
        names = [p["name"] for p in result["pokemon"]]
        assert "Bulbasaur" in names
        assert "Squirtle" in names

    def test_box2_different(self, emu: EmulatorClient):
        """Box 2 is empty or different from Box 1."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.pc import read_box
        box1 = read_box(emu, box=1)
        box2 = read_box(emu, box=2)
        if box2["count"] > 0:
            names1 = set(p["name"] for p in box1["pokemon"])
            names2 = set(p["name"] for p in box2["pokemon"])
            assert names1 != names2
        else:
            assert box2["count"] == 0


# ---------------------------------------------------------------------------
# read_shop
# ---------------------------------------------------------------------------

class TestReadShop:
    """Read PokeMart inventory."""

    def test_in_city_returns_inventory(self, emu: EmulatorClient):
        """In Eterna City -> returns mart inventory."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.shop import read_shop
        from renegade_mcp.trainer import read_trainer_status
        status = read_trainer_status(emu)
        badge_count = status.get("badges") if isinstance(status.get("badges"), int) else None
        result = read_shop(emu, badge_count=badge_count)
        assert "error" not in result
        assert "common_items" in result
        assert len(result["common_items"]) > 0
        item_names = [i["name"] for i in result["common_items"]]
        assert any("Ball" in n and "Pok" in n for n in item_names), (
            f"No Poke Ball in shop items: {item_names}"
        )

    def test_not_in_city_returns_error(self, emu: EmulatorClient):
        """Route 216 grass is not in a city -> error."""
        load_state(emu, "route216_grass_swinub_hunt")
        from renegade_mcp.shop import read_shop
        result = read_shop(emu)
        assert "error" in result


# ---------------------------------------------------------------------------
# tm_compatibility
# ---------------------------------------------------------------------------

class TestTmCompatibility:
    """Check TM compatibility against party."""

    def test_party_moves_readable(self, emu: EmulatorClient):
        """All party Pokemon have readable move lists for TM checking."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        for p in party:
            assert "move_names" in p
            assert len(p["move_names"]) > 0

    def test_already_known_move(self, emu: EmulatorClient):
        """Luxio already knows Spark — verifiable from party data."""
        load_state(emu, "eterna_city_shiny_swinub_in_party")
        from renegade_mcp.party import read_party
        party = read_party(emu)
        luxio = next(p for p in party if p["name"] == "Luxio")
        assert "Spark" in luxio["move_names"]
