"""Regression tests for QA BUG-021.

BUG-021: ``view_map`` reported the Hiker at Route 211 W (377, 529) as
``trainer=true defeated=true`` on first-ever map entry, before the player
had fought any Route 211 W trainers. The NPC is functionally flavor-only
— interacting just emits ``"Mt. Coronet has long been known as an
ancient and mysterious mountain."`` with no battle — but the zone_event
header still declares ``trainer_type=TRAINER_TYPE_NORMAL`` + a trainer
script pointing at real ``trdata.narc`` entry 326 (Hiker Louis, Graveler/
Onix/Golem Lv19 per vanilla Platinum). Renegade Platinum pre-sets this
trainer's defeat flag via a story script, so our flag-bit probe
faithfully returns ``defeated=true`` without the player ever doing
anything. The combination misleads completionist logic (``trainer=true``
implies a runnable battle).

Fix (``trainer.py`` + ``map_state.py``): added
``data/rp_flavor_trainers.json`` enumerating known (map_id, trainer_id)
pairs that are flavor-only. ``view_map`` suppresses the ``trainer`` /
``trainer_id`` / ``defeated`` fields for matching NPCs and sets
``flavor_npc: true`` instead. The allowlist is intentionally narrow
(starts with the session-15 repro); additional NPCs are added as QA
discovers them.

Save state: ``qa_session15_route211_west_entry``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helpers import do_load_state as load_state

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


class TestQaBug021FlavorTrainerRegistry:
    """is_flavor_trainer exposes the (map_id, trainer_id) allowlist."""

    def test_hiker_louis_route211_is_flavor(self) -> None:
        from renegade_mcp.trainer import is_flavor_trainer
        assert is_flavor_trainer(365, 326) is True

    def test_other_route211_trainers_not_flavor(self) -> None:
        from renegade_mcp.trainer import is_flavor_trainer
        # Alexandra (76) and Zach (78) are real trainers.
        assert is_flavor_trainer(365, 76) is False
        assert is_flavor_trainer(365, 78) is False

    def test_hiker_326_on_other_maps_not_flavor(self) -> None:
        """Flavor allowlist is keyed on (map, trainer) — not trainer alone."""
        from renegade_mcp.trainer import is_flavor_trainer
        assert is_flavor_trainer(1, 326) is False
        assert is_flavor_trainer(67, 326) is False

    def test_flavor_cache_is_singleton(self) -> None:
        from renegade_mcp.trainer import _load_flavor_trainers
        assert _load_flavor_trainers() is _load_flavor_trainers()


class TestQaBug021ViewMapSuppression:
    """view_map drops trainer metadata for flavor NPCs."""

    def test_hiker_louis_appears_as_flavor_npc(self, emu: EmulatorClient) -> None:
        load_state(emu, "qa_session15_route211_west_entry")
        emu.advance_frames(120)

        # Walk east so Louis enters the 32x32 viewport. Start state is at
        # (352, 531); Louis is at (377, 529). Navigate bumps player far
        # enough right that (377, 529) falls inside origin (358, 517).
        from renegade_mcp.navigation import navigate_to
        navigate_to(emu, 374, 533, flee_encounters=True)
        emu.advance_frames(60)

        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        louis = next(
            (o for o in result["objects"] if o.get("x") == 377 and o.get("y") == 529),
            None,
        )
        assert louis is not None, (
            f"Expected Hiker at (377, 529) in viewport objects, got: "
            f"{[(o.get('x'), o.get('y'), o.get('name')) for o in result['objects']]}"
        )
        assert louis.get("flavor_npc") is True, (
            f"Expected flavor_npc=True, got: {louis}"
        )
        # Trainer metadata must be fully suppressed — callers keying off
        # `trainer` / `defeated` should not see stale values.
        assert "trainer" not in louis
        assert "trainer_id" not in louis
        assert "defeated" not in louis
        # Sprite-class name is still informative for display.
        assert louis.get("name") == "Hiker"

    def test_real_trainers_still_report_trainer_metadata(
        self, emu: EmulatorClient,
    ) -> None:
        """Alexandra (76) is a real trainer — not in the flavor allowlist."""
        load_state(emu, "qa_session15_route211_west_entry")
        emu.advance_frames(120)

        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        alexandra = next(
            (o for o in result["objects"] if o.get("trainer_id") == 76),
            None,
        )
        assert alexandra is not None, "Alexandra should still be a trainer"
        assert alexandra.get("trainer") is True
        assert alexandra.get("defeated") is False
        assert "flavor_npc" not in alexandra
