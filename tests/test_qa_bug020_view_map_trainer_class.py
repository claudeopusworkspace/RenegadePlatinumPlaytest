"""Regression tests for QA BUG-020.

BUG-020: ``view_map`` reported the NPC's overworld sprite class (from
``GFX_NAMES[graphics_id]``) as the ``name`` even when the real battle
class — stored in ``trdata.narc`` as a class-index byte pointing into
ROM message file 619 — was different. The concrete symptom from session
15: the Route 211 W NPC at (367, 523) used the ``Ace Trainer F`` sprite
but battles as ``Bird Keeper Alexandra``. Callers planning type matchups
from the sprite class would pick the wrong moves.

Fix (``trainer.py`` + ``map_state.py``): ship
``data/trainer_classes.json`` (pre-built from trdata.narc byte[1] cross-
referenced against file 619) and look up the authoritative class on
every resolved ``trainer_id``. When sprite class differs from trainer
class, override ``name`` with the trainer class and preserve the sprite
via a new ``sprite_name`` field. Also surfaces ``trainer_class``
explicitly so callers never have to guess.

Save state: ``qa_session15_route211_west_entry`` (player at (352, 531),
Route 211 west, Bird Keeper Alexandra at (367, 523) undefeated).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helpers import do_load_state as load_state

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


class TestQaBug020TrainerClassLookup:
    """lookup_trainer_class returns authoritative class from trdata.narc."""

    def test_bird_keeper_alexandra_resolves_to_bird_keeper(self) -> None:
        from renegade_mcp.trainer import lookup_trainer_class
        assert lookup_trainer_class(76) == "Bird Keeper"

    def test_ninja_boy_zach_resolves_to_ninja_boy(self) -> None:
        from renegade_mcp.trainer import lookup_trainer_class
        assert lookup_trainer_class(78) == "Ninja Boy"

    def test_hiker_louis_resolves_to_hiker(self) -> None:
        """Sprite class and trainer class coincide — still in the table."""
        from renegade_mcp.trainer import lookup_trainer_class
        assert lookup_trainer_class(326) == "Hiker"

    def test_unknown_trainer_id_returns_none(self) -> None:
        from renegade_mcp.trainer import lookup_trainer_class
        assert lookup_trainer_class(99999) is None

    def test_trainer_class_cache_stable_across_calls(self) -> None:
        """Lookup dict is cached as a singleton — don't rebuild on every call."""
        from renegade_mcp.trainer import _load_trainer_classes
        first = _load_trainer_classes()
        second = _load_trainer_classes()
        assert first is second, "trainer_classes cache should be a singleton"


class TestQaBug020ViewMapOverride:
    """view_map output uses the trainer class when sprite disagrees."""

    def test_alexandra_name_is_bird_keeper(self, emu: EmulatorClient) -> None:
        load_state(emu, "qa_session15_route211_west_entry")
        emu.advance_frames(120)

        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        all_entries = (
            result["interactibles"] + result.get("unreachable_interactibles", [])
        )
        alexandra = next(
            (e for e in all_entries
             if e.get("preview", {}).get("trainer_id") == 76),
            None,
        )
        assert alexandra is not None, (
            f"Expected trainer 76 in viewport interactibles, got: "
            f"{[e.get('label') for e in all_entries]}"
        )

        # Primary fix: `label` reflects the real battle class, not the sprite.
        assert alexandra["label"] == "Bird Keeper", (
            f"Expected label='Bird Keeper' (from trdata), got {alexandra['label']!r}"
        )
        assert alexandra["kind"] == "trainer"
        preview = alexandra["preview"]
        assert preview.get("trainer_class") == "Bird Keeper"
        # Sprite preserved for reference / debugging.
        assert preview.get("sprite_name") == "Ace Trainer F"
        assert preview.get("defeated") is False

    def test_ninja_boy_name_unchanged_when_sprite_matches_class(
        self, emu: EmulatorClient,
    ) -> None:
        """Sprite class == trainer class → no `sprite_name` noise in preview."""
        load_state(emu, "qa_session15_route211_west_entry")
        emu.advance_frames(120)

        from renegade_mcp.map_state import view_map
        result = view_map(emu)

        all_entries = (
            result["interactibles"] + result.get("unreachable_interactibles", [])
        )
        ninja_boy = next(
            (e for e in all_entries
             if e.get("preview", {}).get("trainer_id") == 78),
            None,
        )
        assert ninja_boy is not None
        assert ninja_boy["label"] == "Ninja Boy"
        assert ninja_boy["preview"].get("trainer_class") == "Ninja Boy"
        # When sprite matches trainer_class, sprite_name is omitted.
        assert "sprite_name" not in ninja_boy["preview"]
