"""Read trainer status data from the save block.

Trainer name, money, and badges are stored in the small save block
starting at 0x0227E1D0. Offsets are relative to this base.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# ── Save block offsets ──
MONEY_OFFSET = 0x7C  # u32, verified via snapshot/diff across trainer battles
BADGE_OFFSET = 0x82  # verified with 1 badge (Coal Badge = bit 0 → value 0x01)

# ── Trainer defeat flags ──
# VarsFlags.flags bitfield in save RAM
# Flag = FLAG_OFFSET_TRAINER_DEFEATED + trainerID
# Script field encodes trainer ID: single = 3000 + ID - 1, double = 5000 + ID - 1
# FLAGS_ARRAY = SAVE_BLOCK_BASE + 0xFEC (resolved at runtime via addr())
FLAG_OFFSET_TRAINER_DEFEATED = 1360
SCRIPT_OFFSET_SINGLE = 3000
SCRIPT_OFFSET_DOUBLE = 5000


def trainer_id_from_script(script: int) -> int | None:
    """Extract trainer ID from an NPC's script field. Returns None if not a trainer script."""
    if SCRIPT_OFFSET_SINGLE <= script < SCRIPT_OFFSET_SINGLE + 2000:
        return script - SCRIPT_OFFSET_SINGLE + 1
    if SCRIPT_OFFSET_DOUBLE <= script < SCRIPT_OFFSET_DOUBLE + 2000:
        return script - SCRIPT_OFFSET_DOUBLE + 1
    return None


def is_trainer_defeated(emu: EmulatorClient, trainer_id: int) -> bool:
    """Check if a trainer has been defeated by reading the VarsFlags bitfield."""
    from renegade_mcp.addresses import addr
    flags_array = addr("FLAGS_ARRAY")
    flag_id = FLAG_OFFSET_TRAINER_DEFEATED + trainer_id
    byte_addr = flags_array + (flag_id // 8)
    bit_mask = 1 << (flag_id % 8)
    byte_val = emu.read_memory(byte_addr, size="byte")
    return bool(byte_val & bit_mask)


# ── Trainer class lookup (QA BUG-020) ──
# Sprite classes shown by view_map come from the NPC's graphics_id (via
# GFX_NAMES). The actual in-battle trainer class is stored in trdata.narc
# as a class-index byte that indexes into ROM message file 619. These
# don't always agree — e.g. trainer 76 uses the "Ace Trainer F" sprite
# but battles as "Bird Keeper Alexandra". `trainer_classes.json` was
# pre-built from trdata.narc + file 619 at data-prep time so runtime
# lookups are a plain dict hit.
_TRAINER_CLASSES_CACHE: dict[int, str] | None = None


def _load_trainer_classes() -> dict[int, str]:
    global _TRAINER_CLASSES_CACHE
    if _TRAINER_CLASSES_CACHE is None:
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "data" / "trainer_classes.json"
        raw = json.loads(path.read_text())
        _TRAINER_CLASSES_CACHE = {
            int(tid): entry["class_name"] for tid, entry in raw.items()
        }
    return _TRAINER_CLASSES_CACHE


def lookup_trainer_class(trainer_id: int) -> str | None:
    """Return the authoritative trainer class name from trdata.narc.

    Returns None when the trainer ID isn't in the table (should never happen
    for live-game trainer IDs, but keeps callers safe against future data
    rev bumps).
    """
    return _load_trainer_classes().get(trainer_id)


# ── Flavor-NPC allowlist (QA BUG-021) ──
# Some Renegade-Platinum NPCs declare a trainer_type byte and a trainer
# script in their zone_event header, but the actual script path only
# emits flavor dialogue and never invokes the battle. A story-side script
# pre-sets the trainer-defeat flag for these NPCs so they silently
# deactivate — from view_map's save-flag-based `defeated` probe, that
# looks like a cleared trainer on first map entry. To avoid misleading
# callers (completionist checkers, planning tools), suppress the trainer
# metadata for (map_id, trainer_id) pairs enumerated in
# data/rp_flavor_trainers.json. Entries are added as QA discovers them.
_FLAVOR_TRAINERS_CACHE: dict[int, set[int]] | None = None


def _load_flavor_trainers() -> dict[int, set[int]]:
    global _FLAVOR_TRAINERS_CACHE
    if _FLAVOR_TRAINERS_CACHE is None:
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "data" / "rp_flavor_trainers.json"
        raw = json.loads(path.read_text())
        _FLAVOR_TRAINERS_CACHE = {
            int(mid): set(tids) for mid, tids in raw.get("maps", {}).items()
        }
    return _FLAVOR_TRAINERS_CACHE


def is_flavor_trainer(map_id: int, trainer_id: int) -> bool:
    """Return True if the (map, trainer) pair is a known flavor-only NPC."""
    return trainer_id in _load_flavor_trainers().get(map_id, set())


def read_trainer_status(emu: EmulatorClient) -> dict[str, Any]:
    """Read money and badge count from the save block.

    Works anytime — pure memory read, no UI interaction.
    """
    from renegade_mcp.addresses import addr
    save_base = addr("SAVE_BLOCK_BASE")
    money_addr = save_base + MONEY_OFFSET
    money = emu.read_memory(money_addr, size="long")

    result: dict[str, Any] = {
        "money": money,
    }

    # Badges: placeholder until we confirm the address at first gym
    if BADGE_OFFSET is not None:
        badge_addr = save_base + BADGE_OFFSET
        badge_byte = emu.read_memory(badge_addr, size="byte")
        badges = bin(badge_byte).count("1")
        badge_names = [
            "Coal", "Forest", "Cobble", "Fen",
            "Relic", "Mine", "Icicle", "Beacon",
        ]
        earned = [badge_names[i] for i in range(8) if badge_byte & (1 << i)]
        result["badges"] = badges
        result["badge_names"] = earned
        result["badge_raw"] = badge_byte
    else:
        result["badges"] = "unknown (address unconfirmed)"

    # Bicycle state: cyclingGear u16 in FieldOverworldState.PlayerData
    cycling_gear = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
    on_bicycle = bool(cycling_gear)
    result["on_bicycle"] = on_bicycle

    result["formatted"] = f"Money: ${money:,}"
    if isinstance(result.get("badges"), int):
        result["formatted"] += f" | Badges: {result['badges']}/8"
        if result.get("badge_names"):
            result["formatted"] += f" ({', '.join(result['badge_names'])})"
    else:
        result["formatted"] += " | Badges: TBD (will confirm at first gym)"
    if on_bicycle:
        result["formatted"] += " | Bicycle: ON"

    return result
