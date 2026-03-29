"""Read trainer status data from the save block.

Trainer name, money, and badges are stored in the small save block
starting at 0x0227E1D0. Offsets are relative to this base.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# ── Save block addresses ──
# Small save block base derived from encrypted party data:
#   party_count @ 0x0227E26C = base + 0x9C → base = 0x0227E1D0
SAVE_BLOCK_BASE = 0x0227E1D0
MONEY_OFFSET = 0x7C  # u32, verified via snapshot/diff across trainer battles

# Badge offset: unverified (we have 0 badges). Will confirm at first gym.
# PKHeX Platinum puts badges around offset 0x82 but our layout may differ.
BADGE_OFFSET = None  # Set once confirmed


def read_trainer_status(emu: EmulatorClient) -> dict[str, Any]:
    """Read money and badge count from the save block.

    Works anytime — pure memory read, no UI interaction.
    """
    money_addr = SAVE_BLOCK_BASE + MONEY_OFFSET
    money = emu.read_memory(money_addr, size="long")

    result: dict[str, Any] = {
        "money": money,
    }

    # Badges: placeholder until we confirm the address at first gym
    if BADGE_OFFSET is not None:
        badge_addr = SAVE_BLOCK_BASE + BADGE_OFFSET
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

    result["formatted"] = f"Money: ${money:,}"
    if isinstance(result.get("badges"), int):
        result["formatted"] += f" | Badges: {result['badges']}/8"
        if result.get("badge_names"):
            result["formatted"] += f" ({', '.join(result['badge_names'])})"
    else:
        result["formatted"] += " | Badges: TBD (will confirm at first gym)"

    return result
