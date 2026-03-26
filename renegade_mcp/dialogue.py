"""Read and decode dialogue/battle text from emulator RAM.

Scans memory regions for D2EC B6F8 header markers, finds active text slots,
and decodes Gen 4 text encoding.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.text_encoding import CHAR_MAP, CTRL_END, CTRL_PAGE_BREAK, CTRL_NEWLINE, decode_char

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# Memory regions: (start_addr, size, label)
OVERWORLD_REGION = (0x022A7000, 0x2800, "overworld")
BATTLE_REGION = (0x0228A000, 0x180000, "battle")

HEADER_MARKER = b"\xEC\xD2\xF8\xB6"
MAX_TEXT_CHARS = 512


def _find_active_slots(data: bytes, base_addr: int) -> list[tuple]:
    """Find D2EC B6F8 markers with active text. Returns list of (addr, values, known_count)."""
    results = []
    idx = 0

    while True:
        idx = data.find(HEADER_MARKER, idx)
        if idx < 0:
            break

        text_start = idx + 4
        if text_start + 1 >= len(data):
            idx += 2
            continue

        first_val = struct.unpack_from("<H", data, text_start)[0]
        if first_val == CTRL_END:
            idx += 2
            continue

        values = []
        known_count = 0
        pos = text_start

        while pos + 1 < len(data) and len(values) < MAX_TEXT_CHARS:
            val = struct.unpack_from("<H", data, pos)[0]
            values.append(val)
            pos += 2
            if val == CTRL_END:
                break
            if val in CHAR_MAP:
                known_count += 1

        if known_count >= 3:
            results.append((base_addr + text_start, values, known_count))

        idx += 2

    results.sort(key=lambda x: -x[2])
    return results


def _decode_values(values: list[int]) -> list[str]:
    """Decode 16-bit values into text lines."""
    lines = []
    current_line = ""

    for val in values:
        if val == CTRL_END:
            if current_line:
                lines.append(current_line)
                current_line = ""
            break
        elif val == CTRL_PAGE_BREAK:
            if current_line:
                lines.append(current_line)
            lines.append("---")
            current_line = ""
        elif val == CTRL_NEWLINE:
            lines.append(current_line)
            current_line = ""
        else:
            current_line += decode_char(val)

    if current_line:
        lines.append(current_line)

    return lines


def _scan_region(emu: EmulatorClient, region: tuple) -> dict[str, Any] | None:
    """Scan a memory region for active text. Returns result dict or None."""
    start_addr, size, label = region

    raw_bytes = emu.read_memory_range(start_addr, size="byte", count=size)
    if not raw_bytes:
        return None

    data = bytes(raw_bytes)
    slots = _find_active_slots(data, start_addr)

    if not slots:
        return None

    addr, values, _ = slots[0]
    lines = _decode_values(values)

    if not lines or all(not line.strip() or line == "---" for line in lines):
        return None

    return {
        "region": label,
        "address": f"0x{addr:08X}",
        "text": "\n".join(lines),
        "lines": lines,
        "slot_count": len(slots),
    }


def read_dialogue(emu: EmulatorClient, region: str = "auto") -> dict[str, Any]:
    """Read current dialogue or battle text from memory.

    Args:
        region: "auto" (try overworld then battle), "overworld", or "battle".

    Returns dict with text, region, address, and lines.
    """
    if region == "battle":
        result = _scan_region(emu, BATTLE_REGION)
    elif region == "overworld":
        result = _scan_region(emu, OVERWORLD_REGION)
    else:
        result = _scan_region(emu, OVERWORLD_REGION)
        if result is None:
            result = _scan_region(emu, BATTLE_REGION)

    if result is None:
        return {"text": "(no active text)", "region": "none", "lines": [], "slot_count": 0}

    return result
