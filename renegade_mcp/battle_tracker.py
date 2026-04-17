"""Battle text tracking — init baseline + poll for new narration.

Replaces the file-based coupling between battle_init.py and battle_poll.py
with an in-memory BattleTracker singleton.
"""

from __future__ import annotations

import re
import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.text_encoding import CHAR_MAP, CTRL_END, CTRL_LINE_BREAK, CTRL_NEWLINE, CTRL_PAGE_BREAK, CTRL_VAR, _consume_var_block

# Matches [FFFE] plus up to 3 following [XXXX] argument tokens (decoded u16 vars)
_FFFE_TOKEN_RE = re.compile(r"\[FFFE\](?:\[[0-9A-F]{4}\]){0,3}")

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient

# Scan region — SCAN_START resolved at runtime, SCAN_SIZE is constant
from renegade_mcp.addresses import BATTLE_SCAN_SIZE as SCAN_SIZE

HEADER_MARKER = b"\xEC\xD2\xF8\xB6"
MAX_TEXT_CHARS = 120
POLL_REGION_PADDING = 0x1000

# Timing
MAX_POLLS = 150
DISCOVERY_POLLS = 30
POLL_FRAMES = 15
SETTLE_FRAMES = 120
NO_TEXT_EXIT_THRESHOLD = 20  # consecutive None scans before declaring battle over (~5 sec)


def _decode_text(vals: list[int]) -> tuple[str, list[int]]:
    """Decode 16-bit values up to END marker. Returns (text, vals_up_to_end).

    Strips Gen 4 VAR blocks (``FFFE <id> <count> <args>``) from the rendered
    text so callers don't see raw ``[FFFE][XXXX]...`` placeholders. The raw
    vals list is still returned intact for downstream pattern matching
    (e.g. action-prompt detection scans for the FFFE/0200 marker).
    """
    out = ""
    i = 0
    end_idx = len(vals)
    while i < len(vals):
        v = vals[i]
        if v == CTRL_END:
            end_idx = i
            break
        if v == CTRL_VAR:
            i = _consume_var_block(vals, i)
            continue
        if v == CTRL_NEWLINE or v == CTRL_PAGE_BREAK or v == CTRL_LINE_BREAK:
            out += "\n"
        elif v in CHAR_MAP:
            out += CHAR_MAP[v]
        else:
            out += f"[{v:04X}]"
        i += 1
    return out, vals[:end_idx]


def _scan_markers(data: bytes, base_addr: int) -> dict[str, str]:
    """Find all D2EC B6F8 markers with active text. Returns {hex_addr: text}."""
    markers = {}
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

        vals = []
        known_count = 0
        pos = text_start
        while pos + 1 < len(data) and len(vals) < MAX_TEXT_CHARS:
            v = struct.unpack_from("<H", data, pos)[0]
            vals.append(v)
            pos += 2
            if v == CTRL_END:
                break
            if v in CHAR_MAP:
                known_count += 1

        if known_count >= 3:
            text, _ = _decode_text(vals)
            if text.strip():
                addr = base_addr + idx
                markers[f"0x{addr:08X}"] = text

        idx += 2

    return markers


def _scan_for_new_text(data: bytes, base_addr: int, baseline: dict[str, str] | None) -> list[tuple]:
    """Scan for text markers, filtering against baseline. Returns sorted results."""
    if baseline is None:
        baseline = {}

    results = []
    idx = 0
    while True:
        idx = data.find(HEADER_MARKER, idx)
        if idx < 0:
            break

        abs_addr = base_addr + idx
        addr_str = f"0x{abs_addr:08X}"

        text_start = idx + 4
        if text_start + 1 >= len(data):
            idx += 2
            continue

        first_val = struct.unpack_from("<H", data, text_start)[0]
        if first_val == CTRL_END:
            idx += 2
            continue

        vals = []
        known_count = 0
        pos = text_start
        while pos + 1 < len(data) and len(vals) < MAX_TEXT_CHARS:
            v = struct.unpack_from("<H", data, pos)[0]
            vals.append(v)
            pos += 2
            if v == CTRL_END:
                break
            if v in CHAR_MAP:
                known_count += 1

        if known_count >= 3:
            text, _ = _decode_text(vals)
            if text.strip():
                if addr_str in baseline and baseline[addr_str] == text:
                    idx += 2
                    continue
                results.append((abs_addr, text, vals, known_count))

        idx += 2

    results.sort(key=lambda x: -x[3])
    return results


def _classify_stop(vals: list[int]) -> str:
    """Classify stop type from trailing values before END.

    Only [FFFE][0200] indicates an action prompt (move/switch selection).
    Other FFFE codes like [FFFE][0202] are text variable substitutions
    (e.g. level numbers in "grew to Lv. 11!") and should auto-advance.
    """
    end_idx = None
    for i, v in enumerate(vals):
        if v == CTRL_END:
            end_idx = i
            break
    if end_idx is None or end_idx == 0:
        return "AUTO_ADVANCE"

    if vals[end_idx - 1] == CTRL_NEWLINE:
        return "WAIT_FOR_INPUT"

    # Check for [FFFE][0200] — the specific action/switch prompt pattern
    for j in range(max(0, end_idx - 5), end_idx - 1):
        if vals[j] == CTRL_VAR and vals[j + 1] == 0x0200:
            return "WAIT_FOR_ACTION"

    return "AUTO_ADVANCE"


def _is_orphan_name_text(text: str) -> bool:
    """Return True if `text` looks like a bare species/move/trainer-class name
    that got scraped from a scratch buffer between real macro lines.

    The battle poll loop picks the memory slot with the most decoded chars
    each tick. After a faint/level-up/trainer-send macro clears, a short
    name-cache slot ("Water Pulse", "Makuhita", "Bug Catcher") briefly
    becomes the top match before the next full macro populates. Real macro
    narration always contains either a newline (multi-line box) or terminal
    punctuation (`.` `!` `?`); bare name caches contain neither.

    Examples we filter out (from session 9 logs):
      "Water Pulse", "Makuhita", "Monferno", "Drowzee", "Slowpoke",
      "Bug Catcher", "Buneary".
    """
    if not text:
        return False
    if "\n" in text:
        return False
    if any(ch in text for ch in ".!?,;:…"):
        return False
    # Real one-word battle text is vanishingly rare. A bare name is <= 24 chars
    # (longest vanilla trainer-class label is "Galactic Commander" at 18);
    # cap conservatively to avoid false positives on future lines.
    return len(text) <= 24


def _format_log(log: list[dict], final_state: str) -> str:
    """Format battle log as readable string."""
    lines = ["=== Battle Log ==="]
    for entry in log:
        text = entry["text"].replace("\n", " / ")
        # Strip [FFFE] control codes plus their up-to-3-word argument triplets
        # (e.g. "[FFFE][0202][XXXX][XXXX]" or "[FFFE][0200]"). Preserves any
        # readable text on either side so lines that begin with a substitution
        # (like "[FFFE][0202]...Gotcha!") aren't truncated to empty.
        text = _FFFE_TOKEN_RE.sub("", text).strip()
        marker = ""
        if entry["stop"] == "WAIT_FOR_INPUT":
            marker = "  [waits for B]"
        elif entry["stop"] == "WAIT_FOR_ACTION":
            marker = "  [action prompt]"
        lines.append(f"  {text}{marker}")
    lines.append(f"\nState: {final_state}")
    return "\n".join(lines)


class BattleTracker:
    """Manages battle text tracking state across init and poll calls."""

    def __init__(self) -> None:
        self._baseline: dict[str, str] | None = None
        self._baseline_frame: int = 0
        self._discovered_region: tuple[int, int] | None = None

    def init(self, emu: EmulatorClient) -> dict[str, Any]:
        """Snapshot current text markers as baseline. Call at battle start."""
        from renegade_mcp.addresses import addr
        scan_start = addr("BATTLE_SCAN_START")
        frame = emu.get_frame_count()
        data = emu.read_memory_block(scan_start, SCAN_SIZE)
        markers = _scan_markers(data, scan_start)

        self._baseline = markers
        self._baseline_frame = frame
        self._discovered_region = None

        previews = []
        for addr, text in markers.items():
            preview = text.replace("\n", " / ")[:60]
            previews.append(f"  {addr}: {preview}...")

        return {
            "frame": frame,
            "marker_count": len(markers),
            "markers": previews,
            "message": f"Battle init saved at frame {frame}. Found {len(markers)} existing marker(s).",
        }

    def poll(self, emu: EmulatorClient, auto_press: bool = False) -> dict[str, Any]:
        """Poll for new battle narration after selecting a move.

        Args:
            auto_press: If True, auto-press B to dismiss mid-battle dialogue.

        Returns dict with log entries, final state, and formatted text.
        """
        if self._baseline is None:
            raise RuntimeError(
                "No battle baseline. Call battle_init first at the start of the battle."
            )

        # Validate baseline
        current_frame = emu.get_frame_count()
        if current_frame < self._baseline_frame:
            self._baseline = None
            raise RuntimeError(
                f"Current frame ({current_frame}) < init frame ({self._baseline_frame}). "
                "A save state may have been loaded. Re-run battle_init."
            )

        baseline = self._baseline

        # Phase 2: discover where NEW battle text is
        region = self._discover_region(emu, baseline)
        if region is None:
            return {
                "log": [],
                "final_state": "NO_TEXT",
                "formatted": "=== Battle Log ===\n  (no new battle text found)\n\nState: NO_TEXT",
            }

        scan_start, scan_size = region

        # Phase 3: poll the narrow region
        log: list[dict] = []
        prev_text = None
        seen_auto = False
        consecutive_none = 0

        for poll in range(MAX_POLLS):
            emu.advance_frames(POLL_FRAMES)

            active_baseline = baseline if not seen_auto else None
            text, vals = self._scan_battle_text(emu, scan_start, scan_size, active_baseline)
            if text is None:
                consecutive_none += 1
                # After processing battle text, prolonged absence of text
                # markers means the battle scene has ended.  Text markers
                # are ephemeral (only present during active dialogue), so
                # ~5 seconds of silence is a reliable end-of-battle signal.
                # Exception: after "fainted" text, EXP + switch prompt text
                # is still coming — multi-hit move animations (e.g. 5-hit
                # Bullet Seed) can cause long gaps between faint and EXP.
                faint_seen = any("fainted" in e.get("text", "") for e in log)
                threshold = NO_TEXT_EXIT_THRESHOLD * 3 if faint_seen else NO_TEXT_EXIT_THRESHOLD
                if seen_auto and consecutive_none >= threshold:
                    return {
                        "log": log,
                        "final_state": "TIMEOUT",
                        "formatted": _format_log(log, "TIMEOUT"),
                    }
                continue
            consecutive_none = 0
            stop = _classify_stop(vals)

            if text and text != prev_text:
                prev_text = text

                if stop == "AUTO_ADVANCE":
                    seen_auto = True
                    if not _is_orphan_name_text(text):
                        log.append({"text": text, "stop": stop})
                elif seen_auto or stop == "WAIT_FOR_ACTION":
                    # WAIT_FOR_ACTION ([FFFE][0200]) is a definitive action
                    # prompt — always return it, even without prior AUTO_ADVANCE.
                    # This prevents move-learn prompts from being silently
                    # dropped during _recover_from_level_up re-polls.
                    log.append({"text": text, "stop": stop})
                    emu.advance_frames(SETTLE_FRAMES)

                    if stop == "WAIT_FOR_INPUT" and auto_press:
                        emu.press_buttons(["b"], frames=8)
                        emu.advance_frames(30)
                        continue

                    return {
                        "log": log,
                        "final_state": stop,
                        "formatted": _format_log(log, stop),
                    }

        return {
            "log": log,
            "final_state": "TIMEOUT",
            "formatted": _format_log(log, "TIMEOUT"),
        }

    def _discover_region(self, emu: EmulatorClient, baseline: dict[str, str]) -> tuple[int, int] | None:
        """Broad scan to find where NEW battle text lives."""
        from renegade_mcp.addresses import addr
        scan_start = addr("BATTLE_SCAN_START")
        for attempt in range(DISCOVERY_POLLS):
            emu.advance_frames(POLL_FRAMES)

            data = emu.read_memory_block(scan_start, SCAN_SIZE)
            if not data:
                continue

            results = _scan_for_new_text(data, scan_start, baseline)
            if results:
                addrs = [r[0] for r in results]
                nearest = min(addrs)
                furthest = max(addrs)
                region_start = max(scan_start, nearest - POLL_REGION_PADDING)
                region_end = furthest + POLL_REGION_PADDING
                return region_start, region_end - region_start

        return None

    @staticmethod
    def _scan_battle_text(
        emu: EmulatorClient, scan_start: int, scan_size: int,
        baseline: dict[str, str] | None,
    ) -> tuple[str | None, list[int]]:
        """Scan narrow region for best active text slot."""
        data = emu.read_memory_block(scan_start, scan_size)
        if not data:
            return None, []

        results = _scan_for_new_text(data, scan_start, baseline)
        if results:
            _, text, vals, _ = results[0]
            return text, vals
        return None, []


# Module-level singleton
_tracker = BattleTracker()


def battle_init(emu: EmulatorClient) -> dict[str, Any]:
    """Snapshot battle text baseline. Delegates to the singleton tracker."""
    return _tracker.init(emu)


def battle_poll(emu: EmulatorClient, auto_press: bool = False) -> dict[str, Any]:
    """Poll for new battle narration. Delegates to the singleton tracker."""
    return _tracker.poll(emu, auto_press)
