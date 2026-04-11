"""Shared test helpers for Renegade MCP test suite."""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Any

# Ensure both projects are importable
sys.path.insert(0, "/workspace/MelonMCP")
sys.path.insert(0, "/workspace/DesmumeMCP")
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest")

SAVESTATES_DIR = Path("/workspace/RenegadePlatinumPlaytest/savestates")

# Save state extension per backend
_EXT = {"melonds": ".mst", "desmume": ".dst"}


def _savestate_ext() -> str:
    """Get the save state file extension for the active backend."""
    backend = os.environ.get("EMU_BACKEND", "").lower()
    if backend in _EXT:
        return _EXT[backend]
    # Auto-detect: if .dst files exist, assume DeSmuME (legacy tests)
    if any(SAVESTATES_DIR.glob("*.dst")):
        return ".dst"
    return ".mst"


def do_load_state(emu, name: str, redetect_shift: bool = True) -> None:
    """Load a named save state. Tries the active backend's extension first.

    Args:
        emu: Emulator client.
        name: Save state name (without extension).
        redetect_shift: If True (default), clear the cached address delta and
            re-detect. This is the safe default because the heap layout delta
            varies between save files and even between boots of the same save.
    """
    ext = _savestate_ext()
    path = SAVESTATES_DIR / f"{name}{ext}"
    if not path.exists():
        # Try the other extension as fallback
        alt_ext = ".dst" if ext == ".mst" else ".mst"
        alt_path = SAVESTATES_DIR / f"{name}{alt_ext}"
        assert alt_path.exists(), f"Save state not found: {path} or {alt_path}"
        path = alt_path
    result = emu.load_state(str(path))
    assert result, f"Failed to load save state: {name}"
    # Give the emulator a moment to settle after state load
    emu.advance_frames(60)

    if redetect_shift:
        from renegade_mcp.addresses import reset, detect_shift
        reset()
        detect_shift(emu)


def _log_to_str(log) -> str:
    """Normalize battle log to a single string for searching."""
    if isinstance(log, str):
        return log
    if isinstance(log, list):
        parts = []
        for entry in log:
            if isinstance(entry, dict):
                parts.append(entry.get("text", ""))
            else:
                parts.append(str(entry))
        return "\n".join(parts)
    return str(log)


def assert_log_contains(result: dict[str, Any], *phrases: str) -> None:
    """Assert that the battle log contains all given phrases (case-insensitive)."""
    log = _log_to_str(result.get("log", ""))
    log_lower = log.lower()
    for phrase in phrases:
        assert phrase.lower() in log_lower, (
            f"Expected '{phrase}' in log, but not found.\nLog:\n{log}"
        )


def assert_log_not_contains(result: dict[str, Any], *phrases: str) -> None:
    """Assert that the battle log does NOT contain any of the given phrases."""
    log = _log_to_str(result.get("log", ""))
    log_lower = log.lower()
    for phrase in phrases:
        assert phrase.lower() not in log_lower, (
            f"Unexpected '{phrase}' found in log.\nLog:\n{log}"
        )


def assert_final_state(result: dict[str, Any], expected: str) -> None:
    """Assert the final_state matches expected value."""
    actual = result.get("final_state", "MISSING")
    assert actual == expected, (
        f"Expected final_state={expected}, got {actual}.\n"
        f"Log: {result.get('log', 'N/A')}"
    )


def retry_on_rng(state_name: str, max_retries: int = 3):
    """Retry test up to max_retries, reloading save state each time.

    Use for tests involving RNG (damage rolls, encounters, etc.).
    Read-only tests should NOT use this — if they fail, it's a real bug.

    The decorator loads the save state before each attempt, so tests
    using this should NOT call load_state themselves.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, emu, *args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                do_load_state(emu, state_name)
                try:
                    return fn(self, emu, *args, **kwargs)
                except AssertionError as e:
                    last_error = e
            raise last_error
        return wrapper
    return decorator
