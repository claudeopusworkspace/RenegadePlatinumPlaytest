"""Heal the party at a Pokemon Center by talking to Nurse Joy.

Finds the Pokecenter Nurse on the current map, walks up, interacts,
advances through the healing dialogue, and verifies HP restored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.dialogue import (
    OVERWORLD_REGION,
    _decode_values,
    _find_active_slots,
    read_dialogue,
)
from renegade_mcp.map_state import get_map_state
from renegade_mcp.navigation import interact_with
from renegade_mcp.party import read_party

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Timing ──
TEXT_WAIT = 120       # frames to let a dialogue line render
HEAL_ANIM_WAIT = 300  # frames for the Pokeball healing animation
SETTLE_WAIT = 120     # frames after final dialogue dismissal

# ── Expected dialogue ──
NURSE_GREETING = "would you like to rest your"


def _press(emu: EmulatorClient, buttons: list[str], wait: int = TEXT_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _dialogue_contains(emu: EmulatorClient, needle: str) -> bool:
    """Check if ANY active dialogue slot contains the given text (case-insensitive)."""
    start_addr, size, _ = OVERWORLD_REGION
    raw = emu.read_memory_range(start_addr, size="byte", count=size)
    if not raw:
        return False
    data = bytes(raw)
    slots = _find_active_slots(data, start_addr)
    for _, values, _ in slots:
        lines = _decode_values(values)
        text = " ".join(lines).lower()
        if needle in text:
            return True
    return False


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


def heal_party(emu: EmulatorClient) -> dict[str, Any]:
    """Heal the party at a Pokemon Center.

    1. Scans objects for Pokecenter Nurse (by graphicsID name).
    2. Walks up and interacts via interact_with.
    3. Validates the greeting dialogue before committing.
    4. Advances through Yes → healing animation → post-heal text.
    5. Verifies all party HP is restored.
    """
    # ── Find Nurse Joy ──
    state = get_map_state(emu)
    if state is None:
        return _error("Could not read map state.")

    nurse = next(
        (obj for obj in state["objects"] if obj.get("name") == "Pokecenter Nurse"),
        None,
    )
    if nurse is None:
        names = [obj.get("name", "?") for obj in state["objects"] if obj["index"] != 0]
        return _error(
            f"No Pokecenter Nurse found on this map. "
            f"NPCs: {', '.join(names)}"
        )

    # ── Interact ──
    result = interact_with(emu, nurse["index"])

    if result.get("interrupted") or result.get("encounter"):
        return _error(
            "Navigation to Nurse Joy was interrupted by an encounter or event. "
            f"Details: {result.get('encounter') or result}"
        )

    if result.get("stopped_early"):
        return _error("Could not reach Nurse Joy — path was blocked.")

    # ── Validate greeting dialogue ──
    dialogue = result.get("dialogue")
    dialogue_text = (dialogue.get("text", "") if dialogue else "").lower()

    if NURSE_GREETING not in dialogue_text:
        # interact_with may have picked up an active dialogue box left over from
        # a previous interaction (e.g. save state created mid-dialogue). Dismiss
        # it with B-presses (B won't re-trigger the nurse), then talk to her.
        for _ in range(6):
            _press(emu, ["b"], wait=60)

        # Now press A to actually talk to nurse
        _press(emu, ["a"])
        found_greeting = _dialogue_contains(emu, NURSE_GREETING)

        if not found_greeting:
            actual = dialogue.get("text", "(none)") if dialogue else "(none)"
            return _error(
                f"Unexpected dialogue from Nurse Joy: \"{actual}\". "
                "An event may be active — aborting heal to avoid misclicks."
            )

    # ── Dialogue is confirmed. Advance through healing flow. ──
    # State: "Would you like to rest your Pokémon?" visible, waiting for input.

    # Press A → text finishes rendering, Yes/No prompt appears
    _press(emu, ["a"])

    # Press A → selects YES (default cursor position)
    _press(emu, ["a"])

    # "OK, I'll take your Pokémon for a few seconds." + healing animation
    _press(emu, ["a"], wait=HEAL_ANIM_WAIT)

    # "Thank you for waiting." / "We've restored..." / "We hope to see you again!"
    # Mash through remaining lines — typically 3-4 A-presses to clear all text.
    for _ in range(4):
        _press(emu, ["a"])

    # Wait for dialogue box to fully dismiss
    emu.advance_frames(SETTLE_WAIT)

    # ── Verify dialogue is gone (back to free movement) ──
    leftover = read_dialogue(emu, region="overworld")
    if leftover.get("region") != "none" and leftover.get("text"):
        # Still in dialogue — press A a few more times
        for _ in range(3):
            _press(emu, ["a"])
        emu.advance_frames(SETTLE_WAIT)

    # ── Verify healing ──
    party = read_party(emu)
    all_healed = all(
        p.get("hp", 0) == p.get("max_hp", 0)
        for p in party
        if not p.get("partial")  # Skip stale-data slots
    )

    formatted_lines = ["=== Pokemon Center Heal ==="]
    for p in party:
        hp = p.get("hp", "?")
        max_hp = p.get("max_hp", "?")
        name = p.get("name", "???")
        level = p.get("level", "?")
        partial = " [stale data]" if p.get("partial") else ""
        formatted_lines.append(f"  {name} Lv{level}  HP {hp}/{max_hp}{partial}")

    if all_healed:
        formatted_lines.append("\nAll Pokemon restored to full health!")
    else:
        formatted_lines.append("\nWarning: some Pokemon may not be fully healed.")

    return {
        "success": all_healed,
        "party": party,
        "formatted": "\n".join(formatted_lines),
    }
