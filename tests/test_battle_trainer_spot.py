"""Frame-budget regression guard for spotted-trainer battle intros.

When the player walks into a trainer's line of sight, the game plays:
  !-bubble  →  trainer walks up  →  pre-battle dialogue  →  battle transition
  →  send-out animations  →  "What will X do?" prompt.

The realistic trigger path is via ``navigate`` / ``navigate_to``: nav detects
the interrupt, ``_post_nav_check`` drives ``read_dialogue`` through the intro,
then calls ``_wait_for_action_prompt`` to reach the first action prompt.
Empirically this stalls for ~50 sec at that first waiting-for-input point.
``battle_turn`` is then called and re-enters the same poll, compounding the
cost. This test exists to flag the slowdown until the waste is fixed.

Save state: ``route211_west_pre_trainer``
  Route 211 west, Bird Keeper Alexandra 1 tile left. ``navigate_manual("l")``
  attempts the westward step, which trips her sight cone and routes through
  the nav-events path that Woj reproduces in live play.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state


# Budget covers the whole user-observed sequence: navigate_manual (which
# swallows the spot cutscene + intro + first _wait_for_action_prompt) plus
# the subsequent battle_turn call. 3600 frames = 60 sec at 60 fps. Current
# behaviour blows past this; tighten once the waste is removed.
MAX_SPOT_FRAMES = 3600


class TestTrainerSpotFrameBudget:
    """Walk into a trainer via navigate, fight, check we didn't burn frames."""

    def test_spotted_trainer_navigate_then_turn_frame_budget(self, emu: EmulatorClient):
        from renegade_mcp.navigation import navigate_manual
        from renegade_mcp.turn import battle_turn

        do_load_state(emu, "route211_west_pre_trainer")

        # Attempt to step west — Alexandra is 1 tile left. navigate_manual
        # invokes _post_nav_check which should advance through the intro
        # dialogue and land on the first action prompt.
        start = emu.get_frame_count()
        nav_result = navigate_manual(emu, "l")
        nav_frames = emu.get_frame_count() - start

        # battle_turn from the action prompt submits the move and returns
        # once the first exchange resolves.
        turn_result = battle_turn(emu, move_index=0)
        total_frames = emu.get_frame_count() - start

        # Any post-first-turn state is acceptable — we're measuring intro
        # cost, not RNG outcome. NO_ACTION_PROMPT means we timed out inside
        # the poll loop, which is itself a failure mode of the same bug.
        assert turn_result["final_state"] in (
            "SWITCH_PROMPT", "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
        ), (
            f"Unexpected final_state={turn_result['final_state']} after "
            f"spotted-trainer battle_turn. nav_result={nav_result!r} "
            f"turn_log={turn_result.get('log')}"
        )

        assert total_frames < MAX_SPOT_FRAMES, (
            f"Spotted-trainer flow burned {total_frames} frames "
            f"({total_frames / 60:.1f}s; nav={nav_frames} / "
            f"{nav_frames / 60:.1f}s, turn={total_frames - nav_frames} / "
            f"{(total_frames - nav_frames) / 60:.1f}s). Budget: "
            f"{MAX_SPOT_FRAMES} / {MAX_SPOT_FRAMES / 60:.1f}s. Run with "
            f"--benchmark to see which phase is wasting frames — "
            f"bt_wait_action_prompt (re-entered after nav already reached "
            f"the prompt) is the prime suspect."
        )
