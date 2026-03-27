"""Battle text tracking — init baseline + poll for new narration.

Replaces the file-based coupling between battle_init.py and battle_poll.py
with an in-memory BattleTracker singleton.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from renegade_mcp.text_encoding import CHAR_MAP, CTRL_END, CTRL_NEWLINE, CTRL_PAGE_BREAK, CTRL_VAR

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# Scan region
SCAN_START = 0x0228A000
SCAN_SIZE = 0x180000  # 1.5 MB

HEADER_MARKER = b"\xEC\xD2\xF8\xB6"
MAX_TEXT_CHARS = 120
POLL_REGION_PADDING = 0x1000

# Timing
MAX_POLLS = 300
DISCOVERY_POLLS = 30
POLL_FRAMES = 15
SETTLE_FRAMES = 120


def _decode_text(vals: list[int]) -> tuple[str, list[int]]:
    """Decode 16-bit values up to END marker. Returns (text, vals_up_to_end)."""
    out = ""
    for i, v in enumerate(vals):
        if v == CTRL_END:
            return out, vals[:i]
        elif v == CTRL_NEWLINE:
            out += "\n"
        elif v == CTRL_PAGE_BREAK:
            out += "\n"
        elif v in CHAR_MAP:
            out += CHAR_MAP[v]
        else:
            out += f"[{v:04X}]"
    return out, vals


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


def _format_log(log: list[dict], final_state: str) -> str:
    """Format battle log as readable string."""
    lines = ["=== Battle Log ==="]
    for entry in log:
        text = entry["text"].replace("\n", " / ")
        while "[FFFE]" in text:
            text = text[: text.index("[FFFE]")].rstrip()
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
        frame = emu.get_frame_count()
        raw_bytes = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
        data = bytes(raw_bytes)
        markers = _scan_markers(data, SCAN_START)

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

        for poll in range(MAX_POLLS):
            emu.advance_frames(POLL_FRAMES)

            active_baseline = baseline if not seen_auto else None
            text, vals = self._scan_battle_text(emu, scan_start, scan_size, active_baseline)
            if text is None:
                continue
            stop = _classify_stop(vals)

            if text and text != prev_text:
                prev_text = text

                if stop == "AUTO_ADVANCE":
                    seen_auto = True
                    log.append({"text": text, "stop": stop})
                elif seen_auto:
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
        for attempt in range(DISCOVERY_POLLS):
            emu.advance_frames(POLL_FRAMES)

            raw_bytes = emu.read_memory_range(SCAN_START, size="byte", count=SCAN_SIZE)
            if not raw_bytes:
                continue

            data = bytes(raw_bytes)
            results = _scan_for_new_text(data, SCAN_START, baseline)
            if results:
                addrs = [r[0] for r in results]
                nearest = min(addrs)
                furthest = max(addrs)
                region_start = max(SCAN_START, nearest - POLL_REGION_PADDING)
                region_end = furthest + POLL_REGION_PADDING
                return region_start, region_end - region_start

        return None

    @staticmethod
    def _scan_battle_text(
        emu: EmulatorClient, scan_start: int, scan_size: int,
        baseline: dict[str, str] | None,
    ) -> tuple[str | None, list[int]]:
        """Scan narrow region for best active text slot."""
        raw_bytes = emu.read_memory_range(scan_start, size="byte", count=scan_size)
        if not raw_bytes:
            return None, []

        data = bytes(raw_bytes)
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
