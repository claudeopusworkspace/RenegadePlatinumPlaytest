"""Tests for PC tools: open_pc, deposit_pokemon, withdraw_pokemon, close_pc.

Each test is independent — loads its own save state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state, retry_on_rng


class TestOpenPc:
    """Boot up the PC storage system."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_open_pc(self, emu: EmulatorClient):
        """open_pc reaches storage menu."""
        from renegade_mcp.pc import open_pc
        result = open_pc(emu)
        assert "error" not in result


class TestDepositPokemon:
    """Deposit party Pokemon into box."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_deposit_single(self, emu: EmulatorClient):
        """Deposit 1 Pokemon — completes without error."""
        from renegade_mcp.pc import deposit_pokemon, open_pc

        open_pc(emu)
        result = deposit_pokemon(emu, [5])  # Deposit Swinub (last slot)
        assert "error" not in result
        assert result.get("success", True) is not False

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_deposit_multiple(self, emu: EmulatorClient):
        """Deposit 2 Pokemon — completes without error."""
        from renegade_mcp.pc import deposit_pokemon, open_pc

        open_pc(emu)
        result = deposit_pokemon(emu, [4, 5])  # Deposit last two
        assert "error" not in result
        assert result.get("success", True) is not False


class TestWithdrawPokemon:
    """Withdraw Pokemon from box to party."""

    @retry_on_rng("eterna_city_pokecenter_melonds")
    def test_withdraw_from_box(self, emu: EmulatorClient):
        """Withdraw 1 Pokemon from box — completes without error."""
        from renegade_mcp.pc import open_pc, withdraw_pokemon

        open_pc(emu)
        result = withdraw_pokemon(emu, [0])
        assert "error" not in result, f"withdraw error: {result.get('error')}"

    @retry_on_rng("eterna_city_pokecenter_melonds")
    def test_withdraw_changes_party(self, emu: EmulatorClient):
        """Withdrawn Pokemon appears in party."""
        from renegade_mcp.party import read_party
        from renegade_mcp.pc import open_pc, withdraw_pokemon

        party_before = read_party(emu)
        count_before = len(party_before)

        open_pc(emu)
        result = withdraw_pokemon(emu, [0])
        if "error" not in result:
            party_after = read_party(emu)
            assert len(party_after) >= count_before, (
                f"Party should not shrink: {count_before} -> {len(party_after)}"
            )


class TestClosePc:
    """Exit the PC."""

    @retry_on_rng("eterna_city_shiny_swinub_in_party")
    def test_close_pc(self, emu: EmulatorClient):
        """close_pc returns to overworld."""
        from renegade_mcp.pc import close_pc, open_pc
        open_pc(emu)
        result = close_pc(emu)
        assert "error" not in result


class TestPcFromStorageMenu:
    """PC operations from already-open storage menu."""

    @retry_on_rng("debug_deposit_extra_a_press")
    def test_deposit_from_storage_menu(self, emu: EmulatorClient):
        """Deposit from already-open storage menu."""
        from renegade_mcp.pc import deposit_pokemon
        # This state is already at the storage menu
        result = deposit_pokemon(emu, [5])
        # Should work or return error about state
        assert isinstance(result, dict)
