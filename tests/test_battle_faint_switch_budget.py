"""Frame-budget regression guard for the faint → switch-in flow.

When the active Pokemon faints and ``battle_turn(switch_to=N)`` sends in a
replacement, the observed sequence is:
  party grid tap  →  send-out animation  →  "What will X do?" action prompt.

Empirically this stalls on the "choose Pokemon" / send-out screen, consuming
~45 sec of game time for a visually brief transition. Mirrors the trainer-
spot dialogue bug fixed in 9fa8c4f — some polling loop is waiting on a
signal that's already passed.

Save state: ``bug_qa_auto_grind_faint_switch_stuck``
  Route 202 mid-battle, Shinx fainted, party grid on bottom (FAINT_FORCED).
  Slot 1 (Eevee Lv10, 33/33 HP) is healthy — used as the switch target.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state


# 2400 frames = 40 sec at 60 fps. Current behaviour is ~2678 frames (~45s),
# so this fails today. Tighten once the waste is removed.
MAX_SWITCH_FRAMES = 2400


class TestFaintSwitchFrameBudget:
    """Send a replacement after a faint; verify the flow doesn't burn frames."""

    def test_faint_forced_switch_frame_budget(self, emu: EmulatorClient):
        from renegade_mcp.turn import battle_turn

        do_load_state(emu, "bug_qa_auto_grind_faint_switch_stuck")

        start = emu.get_frame_count()
        result = battle_turn(emu, switch_to=1)
        frames = emu.get_frame_count() - start

        assert result["final_state"] in (
            "WAIT_FOR_ACTION", "BATTLE_ENDED", "MOVE_LEARN",
        ), (
            f"Unexpected final_state={result['final_state']} after faint-switch. "
            f"Log: {result.get('log')}"
        )

        assert frames < MAX_SWITCH_FRAMES, (
            f"battle_turn(switch_to=1) burned {frames} frames "
            f"({frames / 60:.1f}s) on the faint → send-out → action-prompt "
            f"flow. Budget: {MAX_SWITCH_FRAMES} / {MAX_SWITCH_FRAMES / 60:.1f}s. "
            f"Run with --benchmark to see which phase is wasting frames — "
            f"bt_tracker_poll and bt_wait_action_prompt are the prime suspects."
        )
