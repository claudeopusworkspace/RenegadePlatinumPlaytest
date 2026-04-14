"""HM field move obstacle clearing.

Handles the interaction sequence for Rock Smash, Cut, Surf, Rock Climb,
and Waterfall field moves during navigation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from renegade_mcp.nav_constants import (
    HM_INTERACT_WAIT,
    HM_POST_CONFIRM_WAIT,
    HM_SETTLE_WAIT,
    WAIT_FRAMES,
)
from renegade_mcp.dialogue import read_dialogue

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


def _clear_hm_obstacle(
    emu: EmulatorClient,
    direction: str,
    obstacle_info: dict,
) -> bool:
    """Execute the HM field move interaction to clear/traverse an obstacle.

    Handles Rock Smash, Cut, Surf, Rock Climb, and Waterfall.
    Assumes the player is adjacent to the obstacle and facing the right direction
    (the initial movement press turned the player to face the obstacle).
    Returns True if the obstacle was cleared/traversed, False if the interaction didn't trigger.
    """
    # Ensure player is fully facing the obstacle before interacting.
    # The directional press that caused the block may have only started
    # the turn animation — settle before pressing A.
    emu.advance_frames(WAIT_FRAMES)

    # Press A to interact with the obstacle
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(HM_INTERACT_WAIT)

    # Check if dialogue appeared ("Would you like to use X?")
    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] == "none":
        # No dialogue — maybe not facing correctly. Try waiting longer.
        emu.advance_frames(HM_INTERACT_WAIT)
        dialogue = read_dialogue(emu, region="overworld")
        if dialogue["region"] == "none":
            return False

    # Press A to confirm "Yes" (selected by default on the top-screen prompt)
    emu.press_buttons(["a"], frames=8)

    # Wait for "[Mon] used X!" text to appear, auto-dismiss, and animation to play.
    emu.advance_frames(HM_POST_CONFIRM_WAIT)

    # Dismiss any remaining text (some HM animations leave a text box open)
    emu.press_buttons(["b"], frames=8)
    emu.advance_frames(HM_SETTLE_WAIT)

    # Verify we're back in overworld by checking no dialogue is active
    dialogue = read_dialogue(emu, region="overworld")
    if dialogue["region"] != "none":
        # Still showing text — press B a few more times to clear it
        for _ in range(3):
            emu.press_buttons(["b"], frames=8)
            emu.advance_frames(60)
            dialogue = read_dialogue(emu, region="overworld")
            if dialogue["region"] == "none":
                break

    return True
