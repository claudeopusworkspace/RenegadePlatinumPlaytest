"""Plan and execute bulk party healing using Medicine pocket items.

Reads party HP/status + bag contents, computes an optimal healing plan,
and optionally executes it via repeated use_item calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Item knowledge ──

# HP healing items: (name, heal_amount).  Sorted by heal_amount ascending.
# 9999 = heals to full HP regardless of deficit.
HP_ITEMS = [
    ("Berry Juice", 20),
    ("Potion", 20),
    ("Energy Powder", 50),
    ("Fresh Water", 50),
    ("Super Potion", 50),
    ("Soda Pop", 60),
    ("Lemonade", 80),
    ("Moomoo Milk", 100),
    ("Energy Root", 200),
    ("Hyper Potion", 200),
    ("Max Potion", 9999),
    ("Full Restore", 9999),
]

# Status-specific cures: condition name -> list of items that cure ONLY that condition.
STATUS_SPECIFIC_CURES: dict[str, list[str]] = {
    "Sleep": ["Awakening"],
    "Poison": ["Antidote"],
    "Toxic": ["Antidote"],
    "Burn": ["Burn Heal"],
    "Freeze": ["Ice Heal"],
    "Paralysis": ["Parlyz Heal"],
}

# General status cures: cure ALL non-volatile status conditions.
# Ordered by preference (least valuable first — save Full Heal for later).
STATUS_GENERAL_CURES = ["Lava Cookie", "Old Gateau", "Heal Powder", "Full Heal"]

# Revival items: (name, hp_restored).  "half" = 50% max HP, 9999 = full HP.
REVIVAL_ITEMS = [
    ("Revive", "half"),
    ("Revival Herb", 9999),
    ("Max Revive", 9999),
]

# Full Restore is special: cures all status + full HP heal.
FULL_RESTORE = "Full Restore"


def _get_medicine_inventory(bag: list[dict]) -> dict[str, int]:
    """Extract Medicine pocket items as {name: qty} dict."""
    for pocket in bag:
        if pocket["name"] == "Medicine":
            return {item["name"]: item["qty"] for item in pocket["items"]}
    return {}


def _plan_revival(
    pokemon: dict, inventory: dict[str, int]
) -> list[dict[str, Any]]:
    """Plan revival for a fainted Pokemon. Returns list of action dicts."""
    actions = []
    for item_name, heal in REVIVAL_ITEMS:
        if inventory.get(item_name, 0) > 0:
            inventory[item_name] -= 1
            hp_after = pokemon["max_hp"] if heal == 9999 else pokemon["max_hp"] // 2
            actions.append({
                "item": item_name,
                "reason": f"Revive ({hp_after}/{pokemon['max_hp']} HP)",
            })
            # If Revive (half HP), remaining deficit may need HP items
            if heal == "half":
                deficit = pokemon["max_hp"] - hp_after
                if deficit > 0:
                    hp_actions = _plan_hp_healing(deficit, inventory)
                    actions.extend(hp_actions)
            return actions
    return []  # No revival items available


def _plan_status_cure(
    conditions: list[str], inventory: dict[str, int]
) -> list[dict[str, Any]]:
    """Plan status cure. Prefers specific cures over general ones.

    Returns list of action dicts (usually 1 item, but could be 0 if no cure available).
    """
    # Try specific cures first
    for condition in conditions:
        specific = STATUS_SPECIFIC_CURES.get(condition, [])
        for item_name in specific:
            if inventory.get(item_name, 0) > 0:
                inventory[item_name] -= 1
                return [{"item": item_name, "reason": f"Cure {condition}"}]

    # Fall back to general cures
    for item_name in STATUS_GENERAL_CURES:
        if inventory.get(item_name, 0) > 0:
            inventory[item_name] -= 1
            return [{"item": item_name, "reason": f"Cure {', '.join(conditions)}"}]

    return []


def _plan_hp_healing(
    deficit: int, inventory: dict[str, int]
) -> list[dict[str, Any]]:
    """Plan HP healing for a given deficit.

    Algorithm: at each step, check if any single item covers the remaining
    deficit (use cheapest sufficient one). If not, use the cheapest available
    item and repeat. This avoids wasting two items when one would suffice.
    """
    actions = []
    remaining = deficit

    while remaining > 0:
        # Step 1: Find cheapest single item that covers remaining deficit
        best_single = None
        for item_name, heal in HP_ITEMS:
            if inventory.get(item_name, 0) > 0 and heal >= remaining:
                best_single = (item_name, heal)
                break

        if best_single:
            name, heal = best_single
            inventory[name] -= 1
            healed = min(heal, remaining)
            actions.append({
                "item": name,
                "reason": f"Heal {healed} HP (full heal)" if heal >= remaining else f"Heal {healed} HP",
            })
            remaining = 0
        else:
            # Step 2: Use cheapest available item and continue
            used = False
            for item_name, heal in HP_ITEMS:
                if inventory.get(item_name, 0) > 0:
                    inventory[item_name] -= 1
                    actions.append({
                        "item": item_name,
                        "reason": f"Heal {heal} HP ({remaining - heal} remaining)",
                    })
                    remaining -= heal
                    used = True
                    break
            if not used:
                break  # No healing items left

    return actions


def _plan_for_pokemon(
    pokemon: dict, inventory: dict[str, int]
) -> tuple[list[dict[str, Any]], int]:
    """Plan all healing actions for one Pokemon.

    Returns (actions, remaining_hp_deficit).
    """
    actions: list[dict[str, Any]] = []
    name = pokemon["name"]
    hp = pokemon["hp"]
    max_hp = pokemon["max_hp"]
    conditions = list(pokemon.get("status_conditions", []))
    is_fainted = hp <= 0

    if is_fainted:
        revival_actions = _plan_revival(pokemon, inventory)
        if revival_actions:
            actions.extend(revival_actions)
            return actions, 0
        else:
            return [], max_hp  # Can't revive, full deficit remains

    deficit = max_hp - hp
    needs_status = len(conditions) > 0
    needs_hp = deficit > 0

    # Optimization: if needs both status cure AND HP heal, Full Restore covers both
    if needs_status and needs_hp and inventory.get(FULL_RESTORE, 0) > 0:
        inventory[FULL_RESTORE] -= 1
        actions.append({
            "item": FULL_RESTORE,
            "reason": f"Cure {', '.join(conditions)} + heal {deficit} HP (full heal)",
        })
        return actions, 0

    # Status cure first
    if needs_status:
        cure_actions = _plan_status_cure(conditions, inventory)
        actions.extend(cure_actions)
        if not cure_actions:
            # Couldn't cure status — still continue with HP healing
            pass

    # HP healing
    if needs_hp:
        hp_actions = _plan_hp_healing(deficit, inventory)
        actions.extend(hp_actions)
        healed = sum(
            _heal_amount(a["item"]) for a in hp_actions
        )
        remaining_deficit = max(0, deficit - healed)
        return actions, remaining_deficit

    return actions, 0


def _heal_amount(item_name: str) -> int:
    """Look up how much HP an item heals."""
    for name, heal in HP_ITEMS:
        if name == item_name:
            return heal
    # Revival items
    for name, heal in REVIVAL_ITEMS:
        if name == item_name:
            return 9999 if heal == 9999 else 500  # "half" approximation
    return 0


def plan_medicine(
    party: list[dict],
    bag: list[dict],
    exclude_items: list[str] | None = None,
    priority: list[int] | None = None,
) -> dict[str, Any]:
    """Compute a healing plan for the party.

    Args:
        party: Party data from read_party.
        bag: Bag data from read_bag.
        exclude_items: Item names to exclude from consideration.
        priority: Party slot indices in priority order. Defaults to party order.

    Returns dict with plan, item summary, warnings, and formatted output.
    """
    inventory = _get_medicine_inventory(bag)
    original_inventory = dict(inventory)

    # Apply exclusions
    if exclude_items:
        for item in exclude_items:
            # Case-insensitive matching
            for inv_name in list(inventory.keys()):
                if inv_name.lower() == item.lower():
                    del inventory[inv_name]

    # Determine processing order
    if priority:
        ordered_slots = priority
    else:
        ordered_slots = [p["slot"] for p in party]

    # Build slot lookup
    slot_map = {p["slot"]: p for p in party}

    plan = []
    warnings = []
    items_used: dict[str, int] = {}

    for slot in ordered_slots:
        pokemon = slot_map.get(slot)
        if pokemon is None:
            warnings.append(f"Slot {slot} not found in party.")
            continue

        hp = pokemon["hp"]
        max_hp = pokemon["max_hp"]
        conditions = pokemon.get("status_conditions", [])
        is_fainted = hp <= 0

        # Skip Pokemon that don't need healing
        if not is_fainted and hp >= max_hp and not conditions:
            continue

        actions, remaining = _plan_for_pokemon(pokemon, inventory)

        if actions:
            entry = {
                "pokemon": pokemon["name"],
                "slot": slot,
                "actions": actions,
            }
            plan.append(entry)

            # Track items used
            for action in actions:
                item = action["item"]
                items_used[item] = items_used.get(item, 0) + 1

        # Warnings for incomplete healing
        if is_fainted and not actions:
            warnings.append(f"{pokemon['name']} (slot {slot}) is fainted — no revival items available.")
        elif remaining > 0:
            warnings.append(
                f"{pokemon['name']} (slot {slot}) still needs {remaining} HP healing — insufficient items."
            )
        elif conditions and not any(a["reason"].startswith("Cure") or FULL_RESTORE in a["item"] for a in actions):
            warnings.append(
                f"{pokemon['name']} (slot {slot}) has {', '.join(conditions)} — no cure available."
            )

    # Compute remaining inventory
    items_remaining = {}
    for name, qty in original_inventory.items():
        used = items_used.get(name, 0)
        if qty - used > 0:
            items_remaining[name] = qty - used

    # Format human-readable output
    formatted = _format_plan(plan, items_used, items_remaining, warnings)

    result: dict[str, Any] = {
        "plan": plan,
        "items_used": items_used,
        "items_remaining": items_remaining,
        "formatted": formatted,
    }
    if warnings:
        result["warnings"] = warnings
    if not plan:
        result["nothing_to_do"] = True
        result["formatted"] = "All party Pokemon are at full health with no status conditions."

    return result


def _format_plan(
    plan: list[dict],
    items_used: dict[str, int],
    items_remaining: dict[str, int],
    warnings: list[str],
) -> str:
    """Format the healing plan as readable text."""
    if not plan:
        return "No healing needed."

    lines = ["=== Healing Plan ==="]
    for entry in plan:
        lines.append(f"\n  {entry['pokemon']} (slot {entry['slot']}):")
        for action in entry["actions"]:
            lines.append(f"    - {action['item']}: {action['reason']}")

    lines.append("\n--- Items to use ---")
    for item, count in sorted(items_used.items()):
        remaining = items_remaining.get(item, 0)
        lines.append(f"  {item} x{count} (remaining: {remaining})")

    if warnings:
        lines.append("\n--- Warnings ---")
        for w in warnings:
            lines.append(f"  ! {w}")

    lines.append("\nCall use_medicine(confirm=True) to execute this plan.")
    return "\n".join(lines)


def use_medicine(
    emu: EmulatorClient,
    confirm: bool = False,
    exclude_items: list[str] | None = None,
    priority: list[int] | None = None,
) -> dict[str, Any]:
    """Plan or execute bulk party healing.

    First call (confirm=False): returns the healing plan without touching the game.
    Second call (confirm=True): executes the plan via repeated use_item calls.

    Args:
        emu: Emulator client.
        confirm: If True, execute the plan. If False, just return it.
        exclude_items: Item names to exclude from the plan.
        priority: Party slot indices in healing priority order.

    Returns dict with plan details and execution results.
    """
    from renegade_mcp.bag import read_bag
    from renegade_mcp.party import read_party
    from renegade_mcp.use_item import use_item

    party = read_party(emu)
    bag = read_bag(emu)

    if not party:
        return {"success": False, "error": "No party data.", "formatted": "Error: No party data."}

    plan_result = plan_medicine(party, bag, exclude_items, priority)

    if not confirm:
        return plan_result

    # ── Execute the plan ──
    plan = plan_result.get("plan", [])
    if not plan:
        return plan_result  # Nothing to do

    results = []
    for entry in plan:
        slot = entry["slot"]
        for action in entry["actions"]:
            item_name = action["item"]
            result = use_item(emu, item_name, slot)
            results.append({
                "pokemon": entry["pokemon"],
                "slot": slot,
                "item": item_name,
                "success": result.get("success", False),
                "detail": result.get("formatted", ""),
            })
            if not result.get("success"):
                # Stop on failure — menu state may be corrupted
                return {
                    "success": False,
                    "error": f"Failed to use {item_name} on {entry['pokemon']}: {result.get('formatted', 'unknown error')}",
                    "completed": results,
                    "formatted": f"Error: item use failed at {item_name} on {entry['pokemon']}. {len(results) - 1} items used successfully before failure.",
                }

    # Verify final state
    final_party = read_party(emu)
    summary_lines = ["=== Healing Complete ==="]
    for p in final_party:
        conditions = p.get("status_conditions", [])
        status_str = f" ({', '.join(conditions)})" if conditions else ""
        summary_lines.append(f"  {p['name']}: {p['hp']}/{p['max_hp']} HP{status_str}")

    return {
        "success": True,
        "results": results,
        "items_used": plan_result.get("items_used", {}),
        "final_party": final_party,
        "formatted": "\n".join(summary_lines),
    }
