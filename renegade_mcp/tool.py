"""Decorator for Renegade MCP tools -- auto-checkpoint + frame profiling."""

from __future__ import annotations

import functools
import inspect
import json
import time
from pathlib import Path


_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "frame_usage.jsonl"


def _build_action(fn, args, kwargs):
    """Build a human-readable action string from function name + non-default args."""
    sig = inspect.signature(fn)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()

    parts = []
    for name, param in sig.parameters.items():
        value = bound.arguments[name]
        # Skip args that match their default value
        if param.default is not inspect.Parameter.empty and param.default == value:
            continue
        parts.append(f"{name}={value!r}")

    return f"{fn.__name__}({', '.join(parts)})"


def _log_frame_usage(
    tool_name: str,
    action: str,
    frame_start: int,
    frame_end: int,
    elapsed_ms: float,
):
    """Append a frame-usage entry to the JSONL log."""
    entry = {
        "ts": time.time(),
        "tool": tool_name,
        "action": action,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "frames": frame_end - frame_start,
        "wall_ms": round(elapsed_ms, 1),
    }
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Don't let logging failures break gameplay


def renegade_tool(fn):
    """Decorator for state-changing Renegade MCP tools.

    Automatically handles two cross-cutting concerns:

    1. **Checkpoint creation** -- saves emulator state before the tool runs,
       with an action string built from the function name and non-default args.
    2. **Frame profiling** -- records start/end frame counts and wall-clock time,
       appended to ``logs/frame_usage.jsonl``.

    Usage::

        @mcp.tool()
        @renegade_tool
        def navigate(directions: str, flee_encounters: bool = False) -> dict[str, Any]:
            from renegade_mcp.navigation import navigate_manual
            emu = get_client()
            return navigate_manual(emu, directions, flee_encounters=flee_encounters)

    Read-only tools (pure memory/ROM reads like ``read_party``, ``read_battle``,
    ``read_bag``) should use bare ``@mcp.tool()`` instead -- they don't advance
    frames and don't need checkpoints.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from renegade_mcp.connection import get_client

        emu = get_client()
        action = _build_action(fn, args, kwargs)

        # Checkpoint before any emulator interaction
        emu.create_checkpoint(action=action)

        # Profile frame usage
        frame_start = emu.get_frame_count()
        t_start = time.monotonic()

        result = fn(*args, **kwargs)

        frame_end = emu.get_frame_count()
        elapsed_ms = (time.monotonic() - t_start) * 1000

        _log_frame_usage(fn.__name__, action, frame_start, frame_end, elapsed_ms)

        # Flush bridge profiling stats for this tool call
        from renegade_mcp.profiler import ProfiledClient
        if isinstance(emu, ProfiledClient):
            emu.flush(tool_name=fn.__name__, action=action)

        return result

    return wrapper
