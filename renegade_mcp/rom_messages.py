"""Decode Pokemon Platinum ROM message archives (Gen 4 encrypted text).

Pure file I/O against romdata/pl_msg/ — no emulator connection needed.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any

from renegade_mcp.text_encoding import CHAR_MAP, CTRL_END, CTRL_VAR

MSG_DIR = Path("romdata") / "pl_msg"


def _decrypt_entry_table(data: bytes, num_entries: int, seed: int) -> list[tuple[int, int]]:
    """Decrypt the offset/length table. Returns list of (offset, char_count)."""
    entries = []
    for i in range(num_entries):
        raw_off = struct.unpack_from("<I", data, 4 + i * 8)[0]
        raw_len = struct.unpack_from("<I", data, 4 + i * 8 + 4)[0]
        ekey = (seed * 0x2FD * (i + 1)) & 0xFFFF
        xk = (ekey | (ekey << 16)) & 0xFFFFFFFF
        off = raw_off ^ xk
        ln = raw_len ^ xk
        entries.append((off, ln))
    return entries


def _decrypt_string_raw(data: bytes, offset: int, char_count: int, string_index: int) -> list[int]:
    """Decrypt a string and return raw u16 character values."""
    key = (0x91BD3 * (string_index + 1)) & 0xFFFF
    chars = []
    for j in range(char_count):
        pos = offset + j * 2
        if pos + 1 >= len(data):
            break
        enc = struct.unpack_from("<H", data, pos)[0]
        dec = (enc ^ key) & 0xFFFF
        key = (key + 0x493D) & 0xFFFF
        chars.append(dec)
    return chars


def _decode_chars(chars: list[int]) -> str:
    """Convert raw u16 values to readable string."""
    text = ""
    j = 0
    while j < len(chars):
        c = chars[j]
        if c == CTRL_END:
            break
        elif c == CTRL_VAR:
            j += 1
            if j < len(chars):
                vtype = chars[j]
                j += 1
                if j < len(chars):
                    vcount = chars[j]
                    j += 1
                    args = []
                    for _ in range(vcount):
                        if j < len(chars):
                            args.append(chars[j])
                            j += 1
                    parts = [f"0x{vtype:04X}"] + [f"0x{a:04X}" for a in args]
                    text += "{" + ",".join(parts) + "}"
                    continue
                else:
                    text += "{VAR}"
                    continue
            else:
                text += "{VAR}"
                continue
        elif c in CHAR_MAP:
            text += CHAR_MAP[c]
        else:
            text += f"[0x{c:04X}]"
        j += 1
    return text


def decode_file(file_index: int) -> list[dict[str, Any]]:
    """Decode all strings in a ROM message file. Returns list of {index, text} dicts."""
    path = MSG_DIR / f"{file_index:04d}.bin"
    if not path.is_file():
        return []

    data = path.read_bytes()
    if len(data) < 4:
        return []

    num_entries = struct.unpack_from("<H", data, 0)[0]
    seed = struct.unpack_from("<H", data, 2)[0]

    table_end = 4 + num_entries * 8
    if table_end > len(data):
        return []

    entries = _decrypt_entry_table(data, num_entries, seed)
    results = []

    for i, (offset, char_count) in enumerate(entries):
        if offset + char_count * 2 > len(data) + 2 or char_count > 10000:
            results.append({"index": i, "text": f"<invalid: offset={offset}, len={char_count}>"})
            continue

        raw_chars = _decrypt_string_raw(data, offset, char_count, i)
        text = _decode_chars(raw_chars)
        results.append({"index": i, "text": text})

    return results


def search_all(query: str) -> list[dict[str, Any]]:
    """Search all ROM message files for strings containing query text."""
    if not MSG_DIR.exists():
        return []

    query_lower = query.lower()
    files = sorted(f for f in os.listdir(MSG_DIR) if f.endswith(".bin"))
    matches = []

    for fname in files:
        file_index = int(fname.replace(".bin", ""))
        results = decode_file(file_index)

        for entry in results:
            if query_lower in entry["text"].lower():
                display = entry["text"].replace("\n", " | ")
                if len(display) > 120:
                    display = display[:120] + "..."
                matches.append({
                    "file": file_index,
                    "index": entry["index"],
                    "text": display,
                })

    return matches
