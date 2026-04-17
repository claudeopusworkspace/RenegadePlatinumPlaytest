"""Consolidated Gen 4 Pokemon text encoding — single source of truth.

Merges character tables from decode_msg.py (most complete), read_dialogue.py,
read_battle.py, battle_init.py, and battle_poll.py.
"""

from __future__ import annotations

# ── Character Table ──
# Comprehensive Gen 4 text encoding (16-bit little-endian characters).

CHAR_MAP: dict[int, str] = {}

# A-Z: 0x012B - 0x0144
for _i in range(26):
    CHAR_MAP[0x012B + _i] = chr(ord("A") + _i)

# a-z: 0x0145 - 0x015E
for _i in range(26):
    CHAR_MAP[0x0145 + _i] = chr(ord("a") + _i)

# 0-9 (standard): 0x0161 - 0x016A
for _i in range(10):
    CHAR_MAP[0x0161 + _i] = chr(ord("0") + _i)

# 0-9 (alternate/small font): 0x0121 - 0x012A
for _i in range(10):
    CHAR_MAP[0x0121 + _i] = chr(ord("0") + _i)

# Punctuation and symbols
CHAR_MAP[0x01DE] = " "
CHAR_MAP[0x0188] = "\u00e9"  # é (as in Pokémon)
CHAR_MAP[0x0189] = "\u2642"  # ♂ male symbol
CHAR_MAP[0x018A] = "\u2640"  # ♀ female symbol
CHAR_MAP[0x01A9] = "("
CHAR_MAP[0x01AA] = ")"
CHAR_MAP[0x01AB] = "!"
CHAR_MAP[0x01AC] = "?"
CHAR_MAP[0x01AD] = ","
CHAR_MAP[0x01AE] = "."
CHAR_MAP[0x01AF] = "\u2026"  # … ellipsis
CHAR_MAP[0x01B0] = "+"
CHAR_MAP[0x01B1] = "="
CHAR_MAP[0x01B2] = "-"
CHAR_MAP[0x01B3] = "'"
CHAR_MAP[0x01B4] = '"'  # opening double quote
CHAR_MAP[0x01B5] = '"'  # closing double quote
CHAR_MAP[0x01B6] = "~"
CHAR_MAP[0x01B7] = "&"
CHAR_MAP[0x01BA] = "/"
CHAR_MAP[0x01BB] = "@"
CHAR_MAP[0x01BC] = "*"
CHAR_MAP[0x01BD] = "#"
CHAR_MAP[0x01BE] = "-"  # en-dash / line-break hyphen
CHAR_MAP[0x01C0] = ";"
CHAR_MAP[0x01C2] = "&"  # small-font ampersand (ROM file 395/396 "TMs & HMs")
CHAR_MAP[0x01C3] = "%"
CHAR_MAP[0x01C4] = ":"
CHAR_MAP[0x01D2] = "%"  # small-font percent (ROM file 23 "90% of all Pokémon")

# Currency glyph (₽-like P-with-stroke). Rendered as "$" for ASCII output.
CHAR_MAP[0x01A8] = "$"

# Bag pocket sprite icons — small bag-pocket glyphs that can't render as ASCII.
# Emitted empty so pocket names like "[0113]ITEMS Pocket" render as "ITEMS Pocket".
# Enumerated from ROM file 396 (pocket label table).
CHAR_MAP[0x0113] = ""  # ITEMS icon
CHAR_MAP[0x0114] = ""  # KEY ITEMS icon
CHAR_MAP[0x0115] = ""  # TMs & HMs icon
CHAR_MAP[0x0116] = ""  # MAIL icon
CHAR_MAP[0x0117] = ""  # MEDICINE icon
CHAR_MAP[0x0118] = ""  # BERRIES icon
CHAR_MAP[0x0119] = ""  # POKé BALLS icon
CHAR_MAP[0x011A] = ""  # BATTLE ITEMS icon

# "Pokémon" ligature glyph — rendered as a 2-tile sprite icon in-game (looks
# like the stylized "PKMN" logo). Always appears as the 2-byte pair
# [0x01E0][0x01E1] prefixing trainer classes in ROM file 619: "Pokémon
# Trainer", "Pokémon Breeder", "Pokémon Ranger". Map the first byte to the
# text "Pokémon" and the second to empty so the pair decodes as one word.
CHAR_MAP[0x01E0] = "Pokémon"
CHAR_MAP[0x01E1] = ""

# Gender symbols used in battle text (different codepoints from 0x0189/0x018A)
CHAR_MAP[0x2467] = "\u2642"  # ♂
CHAR_MAP[0x2469] = "\u2640"  # ♀

# ── Control codes ──

CTRL_END = 0xFFFF
CTRL_VAR = 0xFFFE
CTRL_NEWLINE = 0xE000
CTRL_PAGE_BREAK = 0x25BC
CTRL_LINE_BREAK = 0x25BD  # alternate line-break used in battle narration

TEXT_CONTROL: dict[int, str] = {
    CTRL_END: "[END]",
    CTRL_VAR: "[VAR]",
    CTRL_NEWLINE: "\n",
    CTRL_PAGE_BREAK: "\n---\n",
    CTRL_LINE_BREAK: "\n",
}


def decode_char(val: int) -> str:
    """Decode a single 16-bit value to a character or control string."""
    if val in TEXT_CONTROL:
        return TEXT_CONTROL[val]
    if val in CHAR_MAP:
        return CHAR_MAP[val]
    return f"[{val:04X}]"


def decode_gen4_text(data: bytes, offset: int, max_len: int = 20) -> str:
    """Decode Gen 4 16-bit text from a byte buffer at a given offset.

    Reads up to max_len characters or until 0xFFFF terminator.
    """
    import struct

    chars = []
    for i in range(max_len):
        pos = offset + i * 2
        if pos + 1 >= len(data):
            break
        val = struct.unpack_from("<H", data, pos)[0]
        if val == CTRL_END:
            break
        if val in CHAR_MAP:
            chars.append(CHAR_MAP[val])
        elif val in TEXT_CONTROL:
            chars.append(TEXT_CONTROL[val])
        else:
            chars.append(f"[{val:04X}]")
    return "".join(chars)


def _consume_var_block(values: list[int], i: int) -> int:
    """Given an index `i` pointing at CTRL_VAR (0xFFFE), return the index of
    the first value AFTER the variable block.

    Gen 4 VAR format: ``FFFE <var_id> <arg_count> <args × arg_count>`` —
    total 3 + arg_count tokens consumed. Unknown/corrupt blocks are clamped
    so one bad arg_count can't swallow the rest of the buffer.
    """
    if i + 2 >= len(values):
        return len(values)
    arg_count = values[i + 2]
    # Defensive clamp: real VAR blocks rarely have more than 3 args.
    # Anything larger is probably corrupt data or a misaligned decode.
    if arg_count > 8:
        arg_count = 0
    return min(i + 3 + arg_count, len(values))


def decode_values(values: list[int]) -> list[str]:
    """Decode a list of 16-bit values into text lines, splitting on newlines.

    Strips Gen 4 VAR blocks (``FFFE <id> <count> <args>``) rather than
    surfacing them as raw ``[FFFE][XXXX]...`` placeholder tokens.
    """
    lines: list[str] = []
    current = ""
    i = 0
    while i < len(values):
        val = values[i]
        if val == CTRL_END:
            break
        if val == CTRL_VAR:
            i = _consume_var_block(values, i)
            continue
        ch = decode_char(val)
        if ch == "\n" or ch == "\n---\n":
            lines.append(current)
            current = ""
        else:
            current += ch
        i += 1
    if current:
        lines.append(current)
    return lines
