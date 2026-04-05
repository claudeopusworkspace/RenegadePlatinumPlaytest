"""Read bag cursor state from emulator memory.

The FieldBagCursor struct persists per-pocket cursor positions across
bag open/close cycles. It's heap-allocated and referenced from FieldSystem.

Layout (20 bytes):
    u8 scroll[8]    -- scroll offset per pocket (0x00-0x07)
    u8 index[8]     -- cursor position per pocket (0x08-0x0F)
    u16 pocket      -- last selected pocket ID (0x10)
    u16 padding     -- (0x12)

Pocket IDs: 0=Items, 1=Medicine, 2=Poke Balls, 3=TMs & HMs,
            4=Berries, 5=Mail, 6=Battle Items, 7=Key Items

Index values are 1-based (1 = first item). Scroll is 0-based.
Effective 0-based cursor position = scroll + index - 1.

Address derivation:
    FieldSystem.menuCursorPos is at offset 0x90 = 0x0229FA28
    FieldSystem.bagCursor     is at offset 0x98 = 0x0229FA30 (pointer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

BAG_CURSOR_PTR_ADDR = 0x0229FA30

POCKET_IDS: dict[str, int] = {
    "Items": 0,
    "Medicine": 1,
    "Poke Balls": 2,
    "TMs & HMs": 3,
    "Berries": 4,
    "Mail": 5,
    "Battle Items": 6,
    "Key Items": 7,
}


def get_pocket_cursor(emu: EmulatorClient, pocket_name: str) -> tuple[int, int]:
    """Get (scroll, index) for a specific bag pocket.

    Returns (0, 0) if pocket is unknown or read fails.
    """
    pocket_id = POCKET_IDS.get(pocket_name)
    if pocket_id is None:
        return (0, 0)

    ptr = emu.read_memory(BAG_CURSOR_PTR_ADDR, size="long")
    if not ptr:
        return (0, 0)

    scroll = emu.read_memory(ptr + pocket_id, size="byte")
    index = emu.read_memory(ptr + 8 + pocket_id, size="byte")

    return (scroll, index)
