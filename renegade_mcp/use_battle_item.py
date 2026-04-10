"""Use an item from the bag during battle.

Navigates the battle bag UI (separate from overworld bag):
  Action prompt → BAG → pocket tab → page → item → USE → target → result.

Handles three item categories:
  battleUseFunc=2: Healing items — requires party_slot for target selection.
  battleUseFunc=0: Stat boosters (X items) — auto-applies in singles, target in doubles.
  battleUseFunc=3: Escape items (Poke Doll) — auto-flees, no target.

Touch coordinates from ref/pokeplatinum/src/battle_sub_menus/battle_bag.c TouchScreenRect tables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Timing ──
TAP_WAIT = 60         # frames between taps (matches catch.py)
PAGE_WAIT = 30        # frames between page nav taps (lighter UI operation)
ANIM_WAIT = 300       # frames for item animation + text
DISMISS_WAIT = 120    # frames after B press to dismiss text

# ── Action screen (bottom screen) ──
BAG_XY = (45, 170)    # BAG button on battle action screen (from catch.py)

# ── Pocket selection screen ──
# Decomp: sMenuTouchRects[] — {y_top, y_bottom, x_left, x_right}
POCKET_TAP_XY = {
    0: (64, 44),       # Recover HP/PP  — {8, 79, 0, 127}
    1: (64, 116),      # Recover Status — {80, 151, 0, 127}
    2: (190, 44),      # Poke Balls     — {8, 79, 128, 255}
    3: (190, 116),     # Battle Items   — {80, 151, 128, 255}
}

# ── Item slots (6 per page, 2-column grid) ──
# Decomp: sPocketMenuTouchRects[]
ITEM_SLOT_XY = [
    (64, 32),          # Slot 0 — {8, 55, 0, 127}
    (190, 32),         # Slot 1 — {8, 55, 128, 255}
    (64, 80),          # Slot 2 — {56, 103, 0, 127}
    (190, 80),         # Slot 3 — {56, 103, 128, 255}
    (64, 128),         # Slot 4 — {104, 151, 0, 127}
    (190, 128),        # Slot 5 — {104, 151, 128, 255}
]

# ── Page navigation ──
PREV_PAGE_XY = (20, 172)    # {152, 191, 0, 39}
NEXT_PAGE_XY = (60, 172)    # {152, 191, 40, 79}

# ── USE screen ──
USE_XY = (104, 172)         # {152, 191, 0, 207}
CANCEL_XY = (236, 172)      # {152, 191, 216, 255}

# ── Party selection (battle party screen, same grid as switch) ──
# From turn.py PARTY_TOUCH_XY — calibrated via gameplay
PARTY_TOUCH_XY = [
    (65, 30),    # Slot 0
    (190, 30),   # Slot 1
    (65, 80),    # Slot 2
    (190, 80),   # Slot 3
    (65, 130),   # Slot 4
    (190, 130),  # Slot 5
]

MAX_PAGES = 6  # max pages per battle pocket (36 items / 6 per page)


def _tap(emu: EmulatorClient, x: int, y: int, wait: int = TAP_WAIT) -> None:
    """Tap touch screen and wait."""
    emu.tap_touch_screen(x, y, frames=8)
    emu.advance_frames(wait)


def _press(emu: EmulatorClient, buttons: list[str], wait: int = TAP_WAIT) -> None:
    """Press buttons and wait."""
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def use_battle_item(
    emu: EmulatorClient,
    item_name: str,
    party_slot: int = -1,
    target: int = -1,
) -> dict[str, Any]:
    """Use an item from the bag during battle.

    Args:
        emu: Emulator client.
        item_name: Item name (case-insensitive).
        party_slot: For healing items (battleUseFunc=2): party member to target (0-5).
        target: For X items in doubles: 0=first active, 1=second active. Ignored in singles.

    Returns dict with success, item, final_state, and formatted message.
    """
    from renegade_mcp.bag import read_bag
    from renegade_mcp.battle_bag import find_item_in_battle_bag

    # ── Pre-validation ──
    bag = read_bag(emu)
    location = find_item_in_battle_bag(bag, item_name)

    if "error" in location:
        return _error(location["error"])

    pocket_idx = location["pocket_index"]
    page = location["page"]
    slot = location["slot"]
    battle_use = location["battleUseFunc"]
    old_qty = location["qty"]

    # Reject Poke Balls — use throw_ball instead
    if battle_use == 1:
        return _error(
            f"'{item_name}' is a Poke Ball. Use throw_ball instead."
        )

    # Healing items require party_slot
    if battle_use == 2 and party_slot < 0:
        return _error(
            f"'{item_name}' is a healing item — party_slot (0-5) is required."
        )
    if party_slot > 5:
        return _error(f"party_slot must be 0-5, got {party_slot}")

    # Snapshot battle HP before item use (for healing verification)
    # NOTE: read_party reads the save block which is NOT updated during battle.
    # read_battle reads the live BattleMon structs.
    old_hp = -1
    old_max_hp = -1
    if battle_use == 2 and party_slot >= 0:
        from renegade_mcp.battle import read_battle
        battlers = read_battle(emu)
        # Player's active Pokemon is slot 0 in battlers (side=="player")
        for b in battlers:
            if b.get("side") == "player" and b.get("slot") == 0:
                old_hp = b.get("hp", -1)
                old_max_hp = b.get("max_hp", -1)
                break
        # For non-active party members, HP isn't in read_battle — fall back
        # to trusting the state (can't verify non-active HP from battle data)

    # ── Step 1: Tap BAG on action screen ──
    _tap(emu, BAG_XY[0], BAG_XY[1])

    # ── Step 2: Tap the correct pocket ──
    px, py = POCKET_TAP_XY[pocket_idx]
    _tap(emu, px, py)

    # ── Step 3: Navigate to correct page ──
    # Reset to page 0 by tapping Prev Page (MAX_PAGES-1) times
    for _ in range(MAX_PAGES - 1):
        _tap(emu, PREV_PAGE_XY[0], PREV_PAGE_XY[1], wait=PAGE_WAIT)

    # Navigate forward to target page
    for _ in range(page):
        _tap(emu, NEXT_PAGE_XY[0], NEXT_PAGE_XY[1], wait=PAGE_WAIT)

    # ── Step 4: Tap the item slot ──
    sx, sy = ITEM_SLOT_XY[slot]
    _tap(emu, sx, sy)

    # ── Step 5: Tap USE ──
    _tap(emu, USE_XY[0], USE_XY[1])

    # ── Step 6: Handle targeting ──
    if battle_use == 2:
        # Healing item — party selection screen appears
        # Wait a bit for the screen transition
        emu.advance_frames(TAP_WAIT)
        tx, ty = PARTY_TOUCH_XY[party_slot]
        _tap(emu, tx, ty)

    elif battle_use == 0:
        # X item / stat booster
        # In singles: auto-applies, no tap needed
        # In doubles: target selection needed
        if target >= 0:
            # Doubles: tap the active Pokemon
            # Active battlers in doubles are slots 0 and 2
            # The target screen uses the same party grid
            tx, ty = PARTY_TOUCH_XY[target * 2]  # slot 0 or slot 2
            emu.advance_frames(TAP_WAIT)
            _tap(emu, tx, ty)

    # battleUseFunc == 3 (escape): auto-triggers, nothing to tap

    # ── Step 7: Wait for item animation + enemy turn + return to action prompt ──
    if battle_use == 3:
        # Escape item — wait for battle to end
        emu.advance_frames(ANIM_WAIT)
        for _ in range(3):
            _press(emu, ["b"], wait=DISMISS_WAIT)
        final_state = _detect_state(emu, battle_use)
    else:
        # Healing or X item — use _wait_for_action_prompt for proper detection.
        # The item animation + enemy's turn can take 600+ frames.
        from renegade_mcp.turn import _wait_for_action_prompt
        prompt = _wait_for_action_prompt(emu)
        if prompt["ready"]:
            final_state = "WAIT_FOR_ACTION"
        else:
            final_state = prompt.get("state", "TIMEOUT")

    # ── Step 9: Verify item was used ──
    # NOTE: During battle, the overworld bag (BAG_BASE) is NOT updated —
    # the game works with a BattleSystem copy.  Qty checks are unreliable.
    # Instead, verify via party HP change (healing items) or trust the
    # final state (X items / escape items).

    if battle_use == 2 and party_slot >= 0 and old_hp >= 0:
        # Healing item on active Pokemon — check if HP changed via battle data
        from renegade_mcp.battle import read_battle
        battlers_after = read_battle(emu)
        new_hp = -1
        target_name = f"Slot {party_slot}"
        for b in battlers_after:
            if b.get("side") == "player" and b.get("slot") == 0:
                new_hp = b.get("hp", -1)
                target_name = b.get("nickname") or b.get("species", target_name)
                break
        if new_hp >= 0:
            hp_changed = new_hp != old_hp
            if hp_changed:
                msg = (
                    f"Used {item_name} on {target_name}. "
                    f"HP: {old_hp} -> {new_hp}/{old_max_hp}. State: {final_state}."
                )
                return {
                    "success": True,
                    "item": item_name,
                    "target": target_name,
                    "party_slot": party_slot,
                    "old_hp": old_hp,
                    "new_hp": new_hp,
                    "final_state": final_state,
                    "formatted": msg,
                }
            else:
                msg = (
                    f"Item use may have failed — {target_name} HP unchanged "
                    f"({old_hp}/{old_max_hp}). The item may have had no effect "
                    f"or the UI navigation missed. State: {final_state}."
                )
                return {
                    "success": False,
                    "item": item_name,
                    "target": target_name,
                    "party_slot": party_slot,
                    "hp": old_hp,
                    "final_state": final_state,
                    "formatted": msg,
                }

    # X item or escape item — trust final state
    if final_state in ("WAIT_FOR_ACTION", "BATTLE_ENDED"):
        msg = f"Used {item_name}. State: {final_state}."
        return {
            "success": True,
            "item": item_name,
            "final_state": final_state,
            "formatted": msg,
        }
    else:
        msg = f"Item use uncertain. State: {final_state}."
        return {
            "success": False,
            "item": item_name,
            "final_state": final_state,
            "formatted": msg,
        }


def _detect_state(emu: EmulatorClient, battle_use: int) -> str:
    """Detect the game state after using an item.

    For healing/X items: should be back at action prompt.
    For escape items: battle should be over.
    """
    from renegade_mcp.turn import _is_battle_over

    if battle_use == 3:
        # Escape item — should have ended the battle
        if _is_battle_over(emu):
            return "BATTLE_ENDED"
        # Give more time for flee animation
        emu.advance_frames(300)
        if _is_battle_over(emu):
            return "BATTLE_ENDED"
        return "UNKNOWN"

    # Healing or X item — should be at action prompt
    # Check for action prompt text markers
    from renegade_mcp.battle_tracker import _scan_for_new_text
    from renegade_mcp.addresses import addr, BATTLE_SCAN_SIZE

    scan_start = addr("BATTLE_SCAN_START")
    data = emu.read_memory_block(scan_start, BATTLE_SCAN_SIZE)
    if data:
        results = _scan_for_new_text(data, scan_start, {})
        for _, text, vals, _ in results:
            clean = text.replace("\n", " ").lower()
            if "what will" in clean and "do?" in clean:
                return "WAIT_FOR_ACTION"

    return "WAIT_FOR_ACTION"  # Optimistic — qty check is the real verification


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {"success": False, "error": message, "formatted": f"Error: {message}"}
