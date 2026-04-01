"""Shared test helpers for battle test suite."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure both projects are importable
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest/DesmumeMCP")
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest")

SAVESTATES_DIR = Path("/workspace/RenegadePlatinumPlaytest/savestates")


def do_load_state(emu, name: str) -> None:
    """Load a named save state. Raises if the file doesn't exist."""
    path = SAVESTATES_DIR / f"{name}.dst"
    assert path.exists(), f"Save state not found: {path}"
    result = emu.load_state(str(path))
    assert result, f"Failed to load save state: {name}"
    # Give the emulator a moment to settle after state load
    emu.advance_frames(60)


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
