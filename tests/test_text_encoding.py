"""Tests for Gen 4 text decoding: CHAR_MAP glyph coverage and VAR-block handling.

Covers the three QA regressions where raw control tokens leaked into decoded
dialogue output:

- TestQaBug005TextPlaceholderLeak: Gen 4 FFFE VAR blocks (id/count/args)
  must be stripped; known glyphs 0x25BD line-break and 0x01A8 currency
  must resolve to '\\n' and '$'.
- TestQaBug008HexFormatCodeLeak: alternate-font glyphs (0x01C2 '&', 0x01D2 '%')
  resolve to ASCII; pocket-icon sprite codes 0x0113..0x011A render as empty
  string (they're tiny sprites, not characters).
- TestQaBug009PokemonLigatureLeak: the 0x01E0 0x01E1 pair used to render the
  stylized "Pokémon" glyph must decode as the single word "Pokémon" (0x01E0)
  + "" (0x01E1).

Save states used (integration tests only):
  fr001_repro_growlithe_battle_prompt — Wild Growlithe battle, action prompt.
  bug008_pre_galactic_battle_win — Doubles vs Galactic grunts, Flame Wheel
    line-up; post-battle cutscene writes the Fashion Case KEY ITEMS line and
    the "90% of all Pokémon" Dawn line.
  eterna_forest_entered_south — Cheryl battle entry (Pokémon Trainer ligature).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

from helpers import do_load_state as load_state


# ---------------------------------------------------------------------------
# QA BUG-005: ROM text-variable placeholders leak through dialogue output
# ---------------------------------------------------------------------------

class TestQaBug005TextPlaceholderLeak:
    """Decoders strip Gen 4 VAR blocks (FFFE id count args) and resolve
    known glyph codes (0x25BD line-break, 0x01A8 currency) instead of
    surfacing raw [VAR]/[FFFE]/[XXXX] placeholders to callers."""

    def test_battle_prompt_is_clean(self, emu: EmulatorClient):
        """read_dialogue(region='battle') returns no raw control tokens.

        Pre-fix: "What will Chimchar do?[VAR][0200][0001][0000]"
        Post-fix: "What will Chimchar do?"
        """
        from renegade_mcp.dialogue import read_dialogue

        load_state(emu, "fr001_repro_growlithe_battle_prompt")
        result = read_dialogue(emu, "battle")
        text = result.get("text", "")
        assert text == "What will Chimchar do?", (
            f"Battle prompt should be clean, got: {text!r}"
        )
        # Belt-and-braces: no raw bracketed tokens anywhere in the output.
        assert "[" not in text, f"Raw control token leaked: {text!r}"

    def test_var_block_consumer_consumes_count_plus_three(self):
        """_consume_var_block advances past FFFE + var_id + arg_count + args."""
        from renegade_mcp.text_encoding import CTRL_VAR, _consume_var_block

        # [VAR][0200][0001][0000] = FFFE, id=0200, count=1, arg=0000 → 4 tokens
        vals = [CTRL_VAR, 0x0200, 0x0001, 0x0000]
        assert _consume_var_block(vals, 0) == 4

        # [VAR][0103][0002][0000][0000] = FFFE, id=0103, count=2, 2 args → 5 tokens
        vals = [CTRL_VAR, 0x0103, 0x0002, 0x0000, 0x0000]
        assert _consume_var_block(vals, 0) == 5

        # Corrupt arg_count is clamped (safety): 0xFFFF args would otherwise
        # swallow the rest of the buffer. Treated as count=0.
        vals = [CTRL_VAR, 0x0200, 0xFFFF, 0x41, 0x42, 0x43]
        # 0xFFFF > 8 → treated as 0 args → advances 3 tokens.
        assert _consume_var_block(vals, 0) == 3

    def test_text_encoding_decode_values_strips_var(self):
        """decode_values(): VAR blocks stripped, other chars pass through."""
        from renegade_mcp.text_encoding import CTRL_VAR, decode_values

        # "H" (0x0132) + [VAR][0200][0001][0000] + "i" (0x014D)
        vals = [0x0132, CTRL_VAR, 0x0200, 0x0001, 0x0000, 0x014D]
        lines = decode_values(vals)
        assert lines == ["Hi"], f"Got: {lines!r}"

    def test_line_break_0x25bd_becomes_newline(self):
        """0x25BD line-break (the one that used to show as [25BD]) becomes \\n."""
        from renegade_mcp.text_encoding import CTRL_LINE_BREAK, decode_values

        # "A" + line-break + "B"
        vals = [0x012B, CTRL_LINE_BREAK, 0x012C]
        lines = decode_values(vals)
        assert lines == ["A", "B"], f"Got: {lines!r}"

    def test_currency_glyph_0x01a8_becomes_dollar(self):
        """0x01A8 (P-with-stroke / Pokémon-currency) renders as '$'."""
        from renegade_mcp.text_encoding import decode_values

        # "$" (0x01A8) + "1" (0x0162) + "0" (0x0161) + "0" (0x0161)
        vals = [0x01A8, 0x0162, 0x0161, 0x0161]
        lines = decode_values(vals)
        assert lines == ["$100"], f"Got: {lines!r}"

    def test_battle_log_is_clean_after_seek_encounter(self, emu: EmulatorClient):
        """battle_turn output has no [VAR]/[FFFE]/[XXXX] in any log entry."""
        from renegade_mcp.turn import battle_turn

        load_state(emu, "fr001_repro_growlithe_battle_prompt")
        result = battle_turn(emu, move_index=0)
        log_entries = result.get("log", [])
        for entry in log_entries:
            text = entry.get("text", "") if isinstance(entry, dict) else str(entry)
            assert "[FFFE]" not in text and "[VAR]" not in text, (
                f"Control token leaked in battle log: {text!r}"
            )
            # Any raw hex placeholder would have the form [XXXX]. Allow
            # nothing bracketed at all.
            import re
            assert not re.search(r"\[[0-9A-F]{4}\]", text), (
                f"Raw hex placeholder leaked: {text!r}"
            )


# ---------------------------------------------------------------------------
# QA BUG-008: Hex format codes leak in item-pickup / cutscene dialogue
# ---------------------------------------------------------------------------
# Same family as fixed BUG-005 (0x25BD, 0x01A8). BUG-005 handled FFFE VAR blocks
# and two glyphs, but left five more glyphs that routinely leak through
# item-acquired cutscene text:
#   0x01C2 — small-font '&'   ("TMs & HMs" pocket label, ROM file 395)
#   0x01D2 — small-font '%'   ("90% of all Pokémon", ROM file 23 Dawn dialogue)
#   0x0113 — ITEMS pocket icon glyph
#   0x0114 — KEY ITEMS pocket icon glyph
#   0x0115 — TMs & HMs pocket icon glyph
#   (0x0116–0x011A cover MAIL/MEDICINE/BERRIES/POKé BALLS/BATTLE ITEMS per ROM file 396)
#
# Pocket icon glyphs are tiny sprites in-game — they can't render as ASCII and
# are emitted as empty string. Alt-font glyphs are mapped to their ASCII variant.

class TestQaBug008HexFormatCodeLeak:
    """CHAR_MAP covers alternate-font glyphs and pocket-icon sprite codes so
    they don't leak as raw [XXXX] brackets in decoded dialogue."""

    def test_small_font_ampersand_0x01c2(self):
        """0x01C2 (alt-font '&') renders as '&'. Example: 'TMs & HMs'."""
        from renegade_mcp.text_encoding import decode_values

        # "TMs " + 0x01C2 + " HMs"
        # T=0x013E A=0x012B/...  but simpler: test the glyph directly surrounded by ASCII.
        # Use letters T(0x013E), M(0x0137), s(0x0157), space(0x01DE), H(0x0132).
        vals = [0x013E, 0x0137, 0x0157, 0x01DE, 0x01C2, 0x01DE, 0x0132, 0x0137, 0x0157]
        lines = decode_values(vals)
        assert lines == ["TMs & HMs"], f"Got: {lines!r}"

    def test_small_font_percent_0x01d2(self):
        """0x01D2 (alt-font '%') renders as '%'. Example: '90% of all'."""
        from renegade_mcp.text_encoding import decode_values

        # "90" + 0x01D2 (→ %) + " " — digits: 9=0x016A 0=0x0161
        vals = [0x016A, 0x0161, 0x01D2]
        lines = decode_values(vals)
        assert lines == ["90%"], f"Got: {lines!r}"

    def test_pocket_icon_glyphs_are_elided(self):
        """0x0113..0x011A are pocket sprite icons — render as empty string.

        Covers all 8 pockets from ROM file 396 (pocket label table).
        """
        from renegade_mcp.text_encoding import decode_values

        for glyph in (0x0113, 0x0114, 0x0115, 0x0116, 0x0117, 0x0118, 0x0119, 0x011A):
            # Render "A" + glyph + "B" — glyph should vanish entirely.
            vals = [0x012B, glyph, 0x012C]
            lines = decode_values(vals)
            assert lines == ["AB"], (
                f"Glyph 0x{glyph:04X} leaked instead of being elided: {lines!r}"
            )

    def test_pocket_name_template_renders_clean(self):
        """End-to-end: 'KEY ITEMS Pocket' template round-trips without brackets.

        Reproduces the ROM file 396 KEY ITEMS entry: FFFE color-open + 0x0114
        icon + FFFE color-close + 'KEY ITEMS'. Pre-fix this surfaced as
        '[0114]KEY ITEMS'; post-fix it is just 'KEY ITEMS'.
        """
        from renegade_mcp.text_encoding import CTRL_VAR, decode_values

        # FFFE FF00 0001 0002 (color-open 1-arg 0x0002 = blue)
        # + 0x0114 pocket icon
        # + FFFE FF00 0001 0000 (color-close 1-arg 0x0000)
        # + " KEY ITEMS" letters
        # Letter codes from CHAR_MAP: A=0x012B, so K=A+10=0x0135, E=A+4=0x012F,
        # Y=A+24=0x0143, I=A+8=0x0133, T=A+19=0x013E, M=A+12=0x0137, S=A+18=0x013D,
        # space=0x01DE.
        vals = [
            CTRL_VAR, 0xFF00, 0x0001, 0x0002,
            0x0114,
            CTRL_VAR, 0xFF00, 0x0001, 0x0000,
            0x0135, 0x012F, 0x0143, 0x01DE,  # "KEY "
            0x0133, 0x013E, 0x012F, 0x0137, 0x013D,  # "ITEMS"
        ]
        lines = decode_values(vals)
        assert lines == ["KEY ITEMS"], f"Got: {lines!r}"
        # Belt-and-braces: no bracketed leaks.
        joined = "".join(lines)
        assert "[" not in joined, f"Raw bracket in decoded output: {joined!r}"

    def test_post_galactic_dialogue_has_no_brackets(self, emu: EmulatorClient):
        """Integration: replay the Galactic-grunts double battle win and
        assert the `post_battle_dialogue` list contains no [XXXX] leaks.

        Pre-fix the Fashion Case cutscene surfaced:
          'in the [0114]KEY ITEMS Pocket.' and '90[01D2] of all Pokémon...'
        Post-fix both lines are clean.
        """
        import re
        from renegade_mcp.turn import battle_turn

        load_state(emu, "bug008_pre_galactic_battle_win")

        # Finish the double battle — Flame Wheel (slot 1) KOs each enemy.
        # Partner Clefairy flinches / auto-acts; we just need to land killing blows.
        # Turn 1: Flame Wheel → Stunky (crit + Aftermath, but Stunky dies).
        # Turn 2: Silcoon (sent in after Stunky faints).
        # Turn 3: Cascoon (sent in after Silcoon faints) → battle ends.
        r1 = battle_turn(emu, move_index=1, target=0)
        assert r1["final_state"] in ("WAIT_FOR_ACTION", "ACTION"), (
            f"Turn 1 state: {r1['final_state']}"
        )
        r2 = battle_turn(emu, move_index=1, target=1)  # target Silcoon
        assert r2["final_state"] in ("WAIT_FOR_ACTION", "ACTION"), (
            f"Turn 2 state: {r2['final_state']}"
        )
        r3 = battle_turn(emu, move_index=1, target=0)  # target remaining enemy
        assert r3["final_state"] in ("WAIT_FOR_ACTION", "ACTION"), (
            f"Turn 3 state: {r3['final_state']}"
        )
        r4 = battle_turn(emu, move_index=1, target=1)
        assert r4["final_state"] == "BATTLE_ENDED", (
            f"Turn 4 did not end battle: {r4['final_state']}"
        )

        post_dialogue = r4.get("post_battle_dialogue", [])
        assert post_dialogue, "Expected post_battle_dialogue from Galactic cutscene"

        # Assert no lines contain bracketed hex tokens like [0114] / [01D2].
        bracket_re = re.compile(r"\[[0-9A-F]{4}\]")
        for line in post_dialogue:
            leak = bracket_re.search(line)
            assert leak is None, (
                f"Hex-code leak in post_battle_dialogue: {leak.group()!r} "
                f"in line: {line!r}"
            )

        # Positive spot-checks: the two specific lines that carried the leak
        # now render with their resolved glyphs.
        all_text = "\n".join(post_dialogue)
        assert "90% of all" in all_text, (
            f"Expected '90% of all' with resolved %% in:\n{all_text!r}"
        )
        assert "KEY ITEMS Pocket" in all_text, (
            f"Expected 'KEY ITEMS Pocket' with stripped icon in:\n{all_text!r}"
        )


# ---------------------------------------------------------------------------
# QA BUG-009: [01E0][01E1] "Pokémon" ligature leak
# ---------------------------------------------------------------------------
# Trainer-class strings in ROM file 619 begin with the pair 0x01E0 0x01E1 to
# render the stylized "Pokémon" glyph ahead of "Trainer"/"Breeder"/"Ranger".
# Before this fix the pair leaked as `[01E0][01E1] Trainer Cheryl`.
# CHAR_MAP now maps 0x01E0 → "Pokémon" and 0x01E1 → "" so the 2-byte pair
# decodes as one word and the full string renders "Pokémon Trainer Cheryl".

def _encode_ascii(text: str) -> list[int]:
    """Encode an ASCII string using the reverse of CHAR_MAP. Only supports
    letters/digits/space/basic punctuation — enough to construct the test
    strings below. Skips the ligature bytes, which must be inserted directly."""
    from renegade_mcp.text_encoding import CHAR_MAP

    # Build a one-shot reverse map over the subset we need (letters + digits +
    # space + common punctuation). Ligature codes (0x01E0 / 0x01E1 → "Pokémon"/"")
    # are excluded so plain "P" still maps to its letter code.
    reverse: dict[str, int] = {}
    reserved = {0x01E0, 0x01E1, 0x01C2, 0x01D2, 0x01B7,  # dupes / ligatures
                0x0121, 0x0122, 0x0123, 0x0124, 0x0125,   # small-font digits
                0x0126, 0x0127, 0x0128, 0x0129, 0x012A}
    for code, ch in CHAR_MAP.items():
        if code in reserved or not ch or code < 0x0100:
            continue
        reverse.setdefault(ch, code)
    return [reverse[c] for c in text]


class TestQaBug009PokemonLigatureLeak:
    """CHAR_MAP resolves the [01E0][01E1] pair to "Pokémon"."""

    def test_ligature_decodes_as_pokemon(self):
        """0x01E0 + 0x01E1 + space + 'Trainer' → 'Pokémon Trainer'."""
        from renegade_mcp.text_encoding import decode_values

        vals = [0x01E0, 0x01E1] + _encode_ascii(" Trainer")
        lines = decode_values(vals)
        assert lines == ["Pokémon Trainer"], f"Got: {lines!r}"

    def test_ligature_prefix_before_breeder(self):
        """ROM file 619 index 16 is [01E0][01E1] Breeder."""
        from renegade_mcp.text_encoding import decode_values

        vals = [0x01E0, 0x01E1] + _encode_ascii(" Breeder")
        lines = decode_values(vals)
        assert lines == ["Pokémon Breeder"], f"Got: {lines!r}"

    def test_trainer_name_line_no_brackets(self):
        """End-to-end: trainer send-in line renders with resolved ligature."""
        from renegade_mcp.text_encoding import decode_values

        vals = [0x01E0, 0x01E1] + _encode_ascii(
            " Trainer Cheryl sent out Wailmer!"
        )
        lines = decode_values(vals)
        joined = "\n".join(lines)
        assert "[01E0]" not in joined, f"Hex leak: {joined!r}"
        assert "[01E1]" not in joined, f"Hex leak: {joined!r}"
        assert "Pokémon Trainer Cheryl sent out Wailmer!" in joined, (
            f"Unexpected decoded text: {joined!r}"
        )

    def test_cheryl_battle_log_has_no_brackets(self, emu: EmulatorClient):
        """Integration: running a turn in the Cheryl battle surfaces at
        least one 'Pokémon Trainer' line and never surfaces [01E0]/[01E1]."""
        import re
        from renegade_mcp.interaction import interact_with
        from renegade_mcp.turn import battle_turn

        load_state(emu, "eterna_forest_entered_south")

        enc = interact_with(emu, x=28, y=83)
        assert enc.get("encounter", {}).get("encounter") == "battle", (
            f"Expected Cheryl battle trigger, got: {enc!r}"
        )

        # Turn 1: KO Drifloon (Flamethrower = move slot 1) by turn 2 — Cheryl
        # heals with Super Potion on turn 2 then we KO. The "Pokémon Trainer
        # Cheryl used one Super Potion!" and send-in lines only appear on the
        # turn Cheryl's first Pokémon faints. Run two turns to hit them.
        # Flamethrower KOs Drifloon (resist but frail); if it survives,
        # Cheryl will Super Potion on turn 2 — either path surfaces a
        # "Pokémon Trainer Cheryl" line.
        all_log: list[dict] = []
        for _ in range(3):
            r = battle_turn(emu, move_index=1)
            all_log.extend(r.get("log", []) or [])
            if r["final_state"] == "SWITCH_PROMPT":
                break
            if r["final_state"] not in ("WAIT_FOR_ACTION", "ACTION"):
                break

        joined = "\n".join(entry.get("text", "") for entry in all_log)

        # Assert no hex-code leaks for this glyph family.
        bracket_re = re.compile(r"\[(?:01E0|01E1)\]")
        assert bracket_re.search(joined) is None, (
            f"Ligature leaked into Cheryl battle log:\n{joined}"
        )
        # Positive spot-check: the resolved ligature should appear at least
        # once across the two turns (Cheryl's Super Potion + send-in Wailmer
        # lines both carry the prefix).
        assert "Pokémon Trainer" in joined, (
            f"Expected 'Pokémon Trainer' line across 2 Cheryl turns:\n{joined}"
        )
