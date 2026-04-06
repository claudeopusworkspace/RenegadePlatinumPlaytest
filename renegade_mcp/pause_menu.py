"""Pause menu utilities shared by tools that interact with the overworld menu.

Provides a verified menu-open function that retries if the player doesn't
have control (e.g., during a map warp transition).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Constants ──
# PAUSE_CURSOR_ADDR resolved at runtime via addr("PAUSE_CURSOR_ADDR")
MENU_SIZE = 7
MENU_WAIT = 300       # frames after major menu transitions
NAV_WAIT = 60         # frames after D-pad navigation
MAX_OPEN_RETRIES = 5


def open_pause_menu(emu: EmulatorClient) -> bool:
    """Open the pause menu and verify it's responsive.

    Presses X, then confirms the menu actually opened by pressing down and
    checking if the cursor address changes. Retries up to 5 times, pressing
    B to dismiss between attempts.

    Returns True if menu is confirmed open (cursor responding to input).
    The cursor will be one position below wherever it started — callers
    should read it fresh before navigating.
    """
    from renegade_mcp.addresses import addr
    cursor_addr = addr("PAUSE_CURSOR_ADDR")
    for _ in range(MAX_OPEN_RETRIES):
        emu.press_buttons(["x"], frames=8)
        emu.advance_frames(MENU_WAIT)

        c1 = emu.read_memory(cursor_addr, size="byte")
        emu.press_buttons(["down"], frames=8)
        emu.advance_frames(NAV_WAIT)
        c2 = emu.read_memory(cursor_addr, size="byte")

        if c1 != c2:
            return True

        # Menu didn't open — dismiss whatever state we're in and retry
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(MENU_WAIT)

    return False
