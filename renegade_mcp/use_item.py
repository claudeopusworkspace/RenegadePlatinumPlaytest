"""Unified item use dispatcher for the overworld bag.

Single entry point `use_item(emu, item_name, party_slot=-1, forget_move=-1)`
handles every field-usable item by looking up its fieldUseFunc and
dispatching to the appropriate menu flow.

Supported flows
---------------
    No-target       BAG_MESSAGE / ESCAPE_ROPE / HONEY / BICYCLE
    Party-target    HEALING / BERRY / EVO_STONE / GRACIDEA
    Party + move    TM_HM (delegates to teach_tm)

Rejected with a clear error
---------------------------
    Fishing rods    → use seek_encounter(rod=...)
    Modal UIs       → Town Map, Journal, Pal Pad, Poffin Case, Poké Radar,
                      Explorer Kit, Vs. Seeker, Vs. Recorder, Sprayduck,
                      Mulch, Azure Flute — drive manually with press_buttons
    Mail            → use give_item to attach
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from renegade_mcp.bag import read_bag
from renegade_mcp.bag_cursor import get_pocket_cursor
from renegade_mcp.data import item_field_use
from renegade_mcp.party import read_party
from renegade_mcp.pause_menu import MENU_SIZE, open_pause_menu

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


# ── Timing ──
MENU_WAIT = 300       # frames after major menu transitions
NAV_WAIT = 60         # frames after D-pad navigation
DISMISS_WAIT = 120    # frames after B press to dismiss text

# ── Pause menu ──
BAG_INDEX = 2

# ── Bag pocket touch coords (bottom screen) ──
POCKET_COORDS = {
    "Items":        (27, 51),
    "Medicine":     (35, 102),
    "Poke Balls":   (59, 142),
    "TMs & HMs":    (100, 165),
    "Berries":      (156, 165),
    "Mail":         (195, 142),
    "Battle Items": (220, 102),
    "Key Items":    (228, 51),
}

# ── Party screen layout (D-pad, 2-column grid) ──
PARTY_NAV = {
    0: [],
    1: ["right"],
    2: ["down"],
    3: ["down", "right"],
    4: ["down", "down"],
    5: ["down", "down", "right"],
}

# ── fieldUseFunc values (pret/pokeplatinum include/constants/items.h) ──
FUNC_NONE          = 0
FUNC_HEALING       = 1
FUNC_TOWN_MAP      = 2
FUNC_EXPLORER_KIT  = 3
FUNC_BICYCLE       = 4
FUNC_JOURNAL       = 5
FUNC_TM_HM         = 6
FUNC_MAIL          = 7
FUNC_BERRY         = 8
FUNC_POFFIN_CASE   = 9
FUNC_PAL_PAD       = 10
FUNC_POKE_RADAR    = 11
FUNC_SPRAYDUCK     = 12
FUNC_MULCH         = 13
FUNC_HONEY         = 14
FUNC_VS_SEEKER     = 15
FUNC_OLD_ROD       = 16
FUNC_GOOD_ROD      = 17
FUNC_SUPER_ROD     = 18
FUNC_BAG_MESSAGE   = 19
FUNC_EVO_STONE     = 20
FUNC_ESCAPE_ROPE   = 21
FUNC_AZURE_FLUTE   = 22
FUNC_VS_RECORDER   = 23
FUNC_GRACIDEA      = 24

FISHING_FUNCS = {FUNC_OLD_ROD, FUNC_GOOD_ROD, FUNC_SUPER_ROD}

PARTY_TARGET_FUNCS = {FUNC_HEALING, FUNC_BERRY, FUNC_EVO_STONE, FUNC_GRACIDEA}

NO_TARGET_FUNCS = {FUNC_BAG_MESSAGE, FUNC_ESCAPE_ROPE, FUNC_HONEY, FUNC_BICYCLE}

# Modal / context-gated flows we explicitly reject (add dedicated support if needed)
MODAL_UI_FUNCS = {
    FUNC_TOWN_MAP, FUNC_EXPLORER_KIT, FUNC_JOURNAL, FUNC_POFFIN_CASE,
    FUNC_PAL_PAD, FUNC_POKE_RADAR, FUNC_VS_SEEKER, FUNC_VS_RECORDER,
    FUNC_SPRAYDUCK, FUNC_MULCH, FUNC_AZURE_FLUTE,
}

# Evolution-stone detection: poll up to this many chunks of 60 frames to
# distinguish "evolution started" from "it had no effect". Evolution scene
# transition is fast (~60-90 frames); "no effect" dialog appears within
# a similar window.
EVO_DETECT_CHUNKS = 12       # 12 * 60 = ~720 frames / ~12 sec
EVO_DETECT_ADVANCE = 60
EVO_ANIMATION_MAX_CHUNKS = 40   # ~2400 frames / ~40 sec ceiling on the scene


# ─────────────────────────── primitives ───────────────────────────


def _press(emu: EmulatorClient, buttons: list[str], wait: int = NAV_WAIT) -> None:
    emu.press_buttons(buttons, frames=8)
    emu.advance_frames(wait)


def _tap(emu: EmulatorClient, x: int, y: int, wait: int = NAV_WAIT) -> None:
    emu.tap_touch_screen(x, y, frames=8)
    emu.advance_frames(wait)


def _error(message: str) -> dict[str, Any]:
    return {"success": False, "error": message, "formatted": f"Error: {message}"}


def _navigate_to_bag_pocket(
    emu: EmulatorClient, pocket_name: str, item_index: int
) -> bool:
    """Open pause menu → Bag → tap pocket tab → scroll cursor to item_index.

    Returns True on success. Leaves the cursor on the target item, ready for
    the caller to press A to open the item submenu.
    """
    if not open_pause_menu(emu):
        return False

    # Navigate pause menu cursor to BAG
    from renegade_mcp.addresses import addr
    cursor = emu.read_memory(addr("PAUSE_CURSOR_ADDR"), size="byte")
    steps = (BAG_INDEX - cursor) % MENU_SIZE
    for _ in range(steps):
        _press(emu, ["down"])
    _press(emu, ["a"], wait=MENU_WAIT)  # Open bag

    # Tap the pocket tab
    coords = POCKET_COORDS.get(pocket_name)
    if coords is None:
        return False
    _tap(emu, *coords, wait=MENU_WAIT)

    # Reset to top-of-pocket, then scroll to the target
    scroll, index = get_pocket_cursor(emu, pocket_name)
    for _ in range(scroll + index):
        _press(emu, ["up"])
    for _ in range(item_index):
        _press(emu, ["down"])
    return True


def _select_party_slot(emu: EmulatorClient, party_slot: int) -> bool:
    """Navigate the party-select cursor (cursor starts at slot 0)."""
    nav = PARTY_NAV.get(party_slot)
    if nav is None:
        return False
    for direction in nav:
        _press(emu, [direction])
    return True


def _close_menus(emu: EmulatorClient, presses: int = 3) -> None:
    """Press B `presses` times to back out to the overworld."""
    for _ in range(presses):
        _press(emu, ["b"], wait=MENU_WAIT)


def _bag_qty(bag: list, pocket_name: str, item_lower: str) -> int | None:
    """Find the quantity of an item in a specific pocket (None if absent)."""
    for pocket in bag:
        if pocket["name"] != pocket_name:
            continue
        for it in pocket["items"]:
            if it["name"].lower() == item_lower:
                return it["qty"]
        return None
    return None


def _verify_qty_decreased(
    emu: EmulatorClient, pocket_name: str, item_name: str, old_qty: int
) -> tuple[bool, int | None]:
    """After use, confirm the item's stack dropped by 1 (or was consumed)."""
    item_lower = item_name.lower()
    bag_after = read_bag(emu)
    new_qty = _bag_qty(bag_after, pocket_name, item_lower)
    if new_qty is not None and new_qty == old_qty - 1:
        return True, new_qty
    if new_qty is None and old_qty == 1:
        return True, 0
    return False, new_qty


# ─────────────────────── find item in any pocket ───────────────────────


def _find_item_in_bag(
    bag: list, item_lower: str
) -> tuple[str | None, int | None, dict | None]:
    """Return (pocket_name, item_index_in_pocket, item_entry) or (None, None, None)."""
    for pocket in bag:
        for i, it in enumerate(pocket["items"]):
            if it["name"].lower() == item_lower:
                return pocket["name"], i, it
    return None, None, None


# ─────────────────────────── main dispatcher ───────────────────────────


def use_item(
    emu: EmulatorClient,
    item_name: str,
    party_slot: int = -1,
    forget_move: int = -1,
) -> dict[str, Any]:
    """Use an item from the overworld bag.

    Dispatches based on the item's fieldUseFunc:
      - No-target:  Repel / Max Repel / Super Repel / Black Flute / White Flute /
                    Silver Wing / Coin Case / Fashion Case / Seal Case /
                    Escape Rope / Honey / Bicycle. `party_slot` ignored.
      - Party-target:  Medicine (Potion, Antidote, Revive, ...), healing
                    Berries, evolution stones, Gracidea (Shaymin). Requires
                    `party_slot` (0-5).
      - TMs/HMs:  delegates to teach_tm. Requires `party_slot`; pass
                    `forget_move` (0-3) when the Pokemon knows 4 moves
                    (or -1 to cancel teaching).

    Args:
        item_name: Item name (case-insensitive).
        party_slot: Party index 0-5. Required for party-target items and TMs.
        forget_move: Move slot to forget for TMs/HMs (0-3, or -1 to cancel).

    Error conditions (returned as {success: False, error, formatted}):
        - Item not found in bag.
        - Item is hold-only (no field use) — suggests give_item.
        - Fishing rod — points to seek_encounter(rod=...).
        - Modal UI — unsupported; drive manually with press_buttons.
        - Mail — unsupported; use give_item to attach.
        - Party-target item without party_slot.
        - Party slot out of range.
    """
    item_lower = item_name.lower().strip()

    bag = read_bag(emu)
    pocket_name, item_index, item_entry = _find_item_in_bag(bag, item_lower)

    # TMs/HMs accept a move name (e.g. "Rock Smash") as well as the TM label
    # ("HM06"). If the raw lookup failed, check whether any TM/HM in the bag
    # teaches a move with that name and delegate to teach_tm — it handles the
    # lookup internally.
    if item_entry is None:
        from renegade_mcp.data import item_id_to_tm_index, tm_move_name
        for pocket in bag:
            if pocket["name"] != "TMs & HMs":
                continue
            for it in pocket["items"]:
                tm_idx = item_id_to_tm_index(it["id"])
                if tm_idx is not None and tm_move_name(tm_idx).lower() == item_lower:
                    if party_slot < 0:
                        return _error(
                            f"'{item_name}' is a TM/HM move — provide party_slot (0-5) and, "
                            f"if the Pokemon knows 4 moves, forget_move (0-3, or -1 to cancel)."
                        )
                    from renegade_mcp.teach_tm import teach_tm as _teach_tm
                    if forget_move == -1:
                        forget: int | None = -1
                    elif forget_move >= 0:
                        forget = forget_move
                    else:
                        forget = None
                    result = _teach_tm(emu, item_name, party_slot, forget)
                    result["kind"] = "tm_hm"
                    return result

        return _error(f"'{item_name}' not found in bag.")

    canonical = item_entry["name"]
    func = item_field_use().get(canonical, FUNC_NONE)

    # ── Reject unsupported flows with specific guidance ──
    if func == FUNC_NONE:
        return _error(
            f"'{canonical}' is hold-only and cannot be used from the bag. "
            f"Attach it to a Pokemon with give_item."
        )
    if func in FISHING_FUNCS:
        return _error(
            f"'{canonical}' is a fishing rod — use seek_encounter(rod='{canonical}') instead."
        )
    if func == FUNC_MAIL:
        return _error(
            f"'{canonical}' is mail. Composing letters is not supported by use_item; "
            f"attach it with give_item."
        )
    if func in MODAL_UI_FUNCS:
        return _error(
            f"'{canonical}' opens a modal UI and is not supported by use_item. "
            f"Drive it manually with press_buttons."
        )

    # ── TM/HM delegates to teach_tm ──
    if func == FUNC_TM_HM:
        if party_slot < 0:
            return _error(
                f"'{canonical}' is a TM/HM — provide party_slot (0-5) and, if the "
                f"Pokemon knows 4 moves, forget_move (0-3, or -1 to cancel)."
            )
        from renegade_mcp.teach_tm import teach_tm as _teach_tm
        forget = None if forget_move == -2 else forget_move
        # Convention: use_item's forget_move=-1 means "cancel" (matches teach_tm).
        # -2 is an internal sentinel for "not provided"; surface it as None.
        if forget_move == -1:
            forget = -1
        elif forget_move < 0:
            forget = None
        result = _teach_tm(emu, canonical, party_slot, forget)
        result["kind"] = "tm_hm"
        return result

    # ── Party-target validation ──
    party_mon: dict | None = None
    if func in PARTY_TARGET_FUNCS:
        if party_slot < 0:
            return _error(
                f"'{canonical}' targets a party Pokemon — provide party_slot (0-5)."
            )
        party = read_party(emu)
        if party_slot >= len(party):
            return _error(
                f"Party slot {party_slot} invalid. Party has {len(party)} member(s)."
            )
        party_mon = party[party_slot]

    # ── Dispatch ──
    if func == FUNC_BICYCLE:
        return _flow_bicycle(emu, pocket_name, item_index, item_entry)
    if func == FUNC_ESCAPE_ROPE:
        return _flow_escape_rope(emu, pocket_name, item_index, item_entry)
    if func in {FUNC_BAG_MESSAGE, FUNC_HONEY}:
        return _flow_no_target_message(emu, pocket_name, item_index, item_entry)
    if func in {FUNC_HEALING, FUNC_BERRY, FUNC_GRACIDEA}:
        return _flow_party_medicine(
            emu, pocket_name, item_index, item_entry, party_slot, party_mon
        )
    if func == FUNC_EVO_STONE:
        return _flow_evo_stone(
            emu, pocket_name, item_index, item_entry, party_slot, party_mon
        )

    return _error(f"'{canonical}' (fieldUseFunc={func}) is not supported by use_item.")


# ─────────────────────────── flow handlers ───────────────────────────


def _flow_no_target_message(
    emu: EmulatorClient,
    pocket_name: str,
    item_index: int,
    item_entry: dict,
) -> dict[str, Any]:
    """Bag-message and Honey flow: USE → message → dismiss → close menus."""
    if not _navigate_to_bag_pocket(emu, pocket_name, item_index):
        return _error("Could not open bag — player may not have control.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Item submenu (USE/GIVE/TOSS/CANCEL)
    _press(emu, ["a"], wait=MENU_WAIT)   # USE

    _press(emu, ["b"], wait=DISMISS_WAIT)  # Dismiss message, back to bag
    _close_menus(emu, presses=2)           # Close bag + pause menu

    ok, new_qty = _verify_qty_decreased(emu, pocket_name, item_entry["name"], item_entry["qty"])
    return _build_no_target_result(item_entry, ok, new_qty, kind="bag_message")


def _flow_escape_rope(
    emu: EmulatorClient,
    pocket_name: str,
    item_index: int,
    item_entry: dict,
) -> dict[str, Any]:
    """Escape Rope flow: USE → warp animation completes automatically."""
    if not _navigate_to_bag_pocket(emu, pocket_name, item_index):
        return _error("Could not open bag — player may not have control.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Item submenu
    _press(emu, ["a"], wait=MENU_WAIT)   # USE

    # Escape Rope closes menus automatically as the warp animation starts.
    emu.advance_frames(600)

    ok, new_qty = _verify_qty_decreased(emu, pocket_name, item_entry["name"], item_entry["qty"])
    return _build_no_target_result(item_entry, ok, new_qty, kind="escape_rope")


def _flow_bicycle(
    emu: EmulatorClient,
    pocket_name: str,
    item_index: int,
    item_entry: dict,
) -> dict[str, Any]:
    """Bicycle toggle flow: USE → mount/dismount animation."""
    from renegade_mcp.addresses import addr
    was_cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))

    if not _navigate_to_bag_pocket(emu, pocket_name, item_index):
        return _error("Could not open bag — player may not have control.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Item submenu (USE / REGISTER / CANCEL)
    _press(emu, ["a"], wait=MENU_WAIT)   # USE
    emu.advance_frames(MENU_WAIT)        # Mount/dismount animation

    is_cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))

    if was_cycling == is_cycling:
        # "Can't use here" / Rowan's echo — multi-page text, close everything.
        _press(emu, ["b"], wait=DISMISS_WAIT)
        _press(emu, ["b"], wait=DISMISS_WAIT)
        _close_menus(emu, presses=3)
        return _error(
            f"Bicycle state didn't change (still {'cycling' if is_cycling else 'walking'}). "
            "May not be usable here (indoors, etc.)."
        )

    action = "mounted" if is_cycling else "dismounted"
    return {
        "success": True,
        "kind": "bicycle",
        "item": item_entry["name"],
        "on_bicycle": is_cycling,
        "formatted": f"{action.capitalize()} Bicycle.",
    }


def _flow_party_medicine(
    emu: EmulatorClient,
    pocket_name: str,
    item_index: int,
    item_entry: dict,
    party_slot: int,
    party_mon: dict,
) -> dict[str, Any]:
    """HEALING / BERRY / GRACIDEA: USE → party screen → slot → dismiss text."""
    target_name = party_mon.get("name", f"Slot {party_slot}")

    if not _navigate_to_bag_pocket(emu, pocket_name, item_index):
        return _error("Could not open bag — player may not have control.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Item submenu
    _press(emu, ["a"], wait=MENU_WAIT)   # USE

    if not _select_party_slot(emu, party_slot):
        _close_menus(emu, presses=5)
        return _error(f"Party slot {party_slot} navigation not mapped.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Confirm party slot

    _press(emu, ["b"], wait=DISMISS_WAIT)  # Dismiss "HP restored" text
    _close_menus(emu, presses=2)           # Close bag + pause menu

    ok, new_qty = _verify_qty_decreased(emu, pocket_name, item_entry["name"], item_entry["qty"])
    old_qty = item_entry["qty"]

    if ok:
        msg = f"Used {item_entry['name']} on {target_name}. Quantity: {old_qty} → {new_qty}."
        return {
            "success": True,
            "kind": "medicine",
            "item": item_entry["name"],
            "target": target_name,
            "old_qty": old_qty,
            "new_qty": new_qty,
            "formatted": msg,
        }

    return {
        "success": False,
        "kind": "medicine",
        "item": item_entry["name"],
        "target": target_name,
        "old_qty": old_qty,
        "new_qty": new_qty,
        "formatted": (
            f"Item use may have failed. {item_entry['name']} quantity: "
            f"{old_qty} → {new_qty if new_qty is not None else '???'}. "
            "The menu flow may have gone wrong."
        ),
    }


def _flow_evo_stone(
    emu: EmulatorClient,
    pocket_name: str,
    item_index: int,
    item_entry: dict,
    party_slot: int,
    party_mon: dict,
) -> dict[str, Any]:
    """Evolution stone: USE → party screen → slot → either evolution scene
    or "had no effect" rejection. Relies on the game's own compat check.

    Detects evolution by watching for 'is evolving' / 'What?' text markers
    within ~12 seconds. If none appear, treats it as incompatible and
    closes the menu.
    """
    from renegade_mcp.turn import _is_evolution_text_on_screen

    target_name = party_mon.get("name", f"Slot {party_slot}")
    old_species = party_mon.get("species", party_mon.get("species_name", ""))
    old_species_id = party_mon.get("species_id", 0)

    if not _navigate_to_bag_pocket(emu, pocket_name, item_index):
        return _error("Could not open bag — player may not have control.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Item submenu
    _press(emu, ["a"], wait=MENU_WAIT)   # USE

    if not _select_party_slot(emu, party_slot):
        _close_menus(emu, presses=5)
        return _error(f"Party slot {party_slot} navigation not mapped.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Confirm party slot

    # Detection phase: did evolution start?
    evolving = False
    for _ in range(EVO_DETECT_CHUNKS):
        if _is_evolution_text_on_screen(emu):
            evolving = True
            break
        emu.advance_frames(EVO_DETECT_ADVANCE)

    if not evolving:
        # "It won't have any effect" or similar — dismiss and close.
        _press(emu, ["b"], wait=DISMISS_WAIT)
        _close_menus(emu, presses=3)
        return {
            "success": False,
            "kind": "evo_stone",
            "item": item_entry["name"],
            "target": target_name,
            "evolved": False,
            "formatted": (
                f"{item_entry['name']} had no effect on {target_name}. "
                f"Not a compatible evolution target."
            ),
        }

    # Evolution scene: dismiss "is evolving" text, wait passively for the
    # animation, then advance through post-evolution dialogue.
    _press(emu, ["b"], wait=60)

    for _ in range(EVO_ANIMATION_MAX_CHUNKS):
        emu.advance_frames(EVO_DETECT_ADVANCE)
        if _evolution_complete_text(emu):
            break

    # Clear post-evolution dialogue ("evolved into X!", possible move-learn).
    # For field evolution via stone, species will simply change; move-learn
    # (if any) should be handled manually by the caller for now.
    for _ in range(8):
        _press(emu, ["b"], wait=DISMISS_WAIT)

    # Read party to verify the species change
    party_after = read_party(emu)
    new_mon = party_after[party_slot] if party_slot < len(party_after) else {}
    new_species = new_mon.get("species", new_mon.get("species_name", ""))
    new_species_id = new_mon.get("species_id", 0)
    evolved = (new_species_id != old_species_id) and new_species_id != 0

    if evolved:
        msg = f"{target_name} evolved from {old_species} into {new_species}!"
        return {
            "success": True,
            "kind": "evo_stone",
            "item": item_entry["name"],
            "target": target_name,
            "evolved": True,
            "old_species": old_species,
            "new_species": new_species,
            "formatted": msg,
        }
    return {
        "success": False,
        "kind": "evo_stone",
        "item": item_entry["name"],
        "target": target_name,
        "evolved": False,
        "formatted": (
            f"Could not verify evolution of {target_name}. The menu flow "
            "may have gone wrong — check the party manually."
        ),
    }


def _evolution_complete_text(emu: EmulatorClient) -> bool:
    """Detect 'evolved into' in the text-marker buffer."""
    from renegade_mcp.battle_tracker import _scan_markers, SCAN_SIZE
    from renegade_mcp.turn import _scan_start
    data = emu.read_memory_block(_scan_start(), SCAN_SIZE)
    if not data:
        return False
    markers = _scan_markers(data, _scan_start())
    for text in markers.values():
        clean = text.replace("\n", " ").strip()
        if "evolved into" in clean:
            return True
    return False


def _build_no_target_result(
    item_entry: dict, ok: bool, new_qty: int | None, *, kind: str
) -> dict[str, Any]:
    old_qty = item_entry["qty"]
    if ok:
        msg = f"Used {item_entry['name']}. Quantity: {old_qty} → {new_qty}."
        return {
            "success": True,
            "kind": kind,
            "item": item_entry["name"],
            "old_qty": old_qty,
            "new_qty": new_qty,
            "formatted": msg,
        }
    return {
        "success": False,
        "kind": kind,
        "item": item_entry["name"],
        "old_qty": old_qty,
        "new_qty": new_qty,
        "formatted": (
            f"Item use may have failed. {item_entry['name']} quantity: "
            f"{old_qty} → {new_qty if new_qty is not None else '???'}. "
            "The menu flow may have gone wrong."
        ),
    }


# ────────────── low-level helper kept for fishing.py ──────────────


def activate_key_item(
    emu: EmulatorClient,
    item_name: str,
    allowed_funcs: set[int] | None = None,
) -> dict[str, Any]:
    """Navigate the bag UI to USE a key item, then hand control back.

    Used by fishing.py — fishing can't complete the full USE loop because it
    needs to detect the encounter while USE is in flight. This helper opens
    the bag, selects the item, and presses USE, then returns.

    Args:
        allowed_funcs: Whitelist of acceptable fieldUseFunc values. Defaults
            to the fishing-rod set.

    Returns dict with {success, item, func} on success, or an error.
    """
    if allowed_funcs is None:
        allowed_funcs = FISHING_FUNCS
    item_lower = item_name.lower()

    bag = read_bag(emu)
    pocket_name, item_index, item_entry = _find_item_in_bag(bag, item_lower)
    if item_entry is None:
        return _error(f"'{item_name}' not found in bag.")

    canonical = item_entry["name"]
    func = item_field_use().get(canonical, FUNC_NONE)
    if func == FUNC_NONE:
        return _error(f"'{canonical}' cannot be used from the field.")
    if func not in allowed_funcs:
        return _error(f"'{canonical}' (fieldUseFunc={func}) is not allowed here.")

    if not _navigate_to_bag_pocket(emu, pocket_name, item_index):
        return _error("Could not open bag — player may not have control.")

    _press(emu, ["a"], wait=MENU_WAIT)   # Item submenu
    _press(emu, ["a"], wait=MENU_WAIT)   # USE

    return {"success": True, "item": item_entry, "func": func}
