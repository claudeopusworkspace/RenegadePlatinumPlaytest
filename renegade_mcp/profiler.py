"""Bridge call profiler for renegade_mcp tools.

Wraps the EmulatorClient to time every bridge method call. Enabled by
setting the environment variable RENEGADE_PROFILE=1.

Accumulates per-method stats (call count, total wall-clock time, min/max/avg)
and writes a summary to logs/bridge_profile.jsonl at the end of each tool call
(via flush()), or on demand.

Usage in connection.py::

    client = client_cls(str(socket_path))
    if os.environ.get("RENEGADE_PROFILE"):
        from renegade_mcp.profiler import ProfiledClient
        client = ProfiledClient(client)

The wrapper is transparent -- all attribute access delegates to the real client.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "bridge_profile.jsonl"


def is_enabled() -> bool:
    """Check if profiling is enabled via environment variable."""
    return os.environ.get("RENEGADE_PROFILE", "") == "1"


class ProfiledClient:
    """Transparent wrapper that times every bridge method call."""

    def __init__(self, client: Any) -> None:
        # Use object.__setattr__ to avoid triggering our __setattr__
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_stats", {})
        object.__setattr__(self, "_call_log", [])

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        stats = self._stats
        call_log = self._call_log

        def timed(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            result = attr(*args, **kwargs)
            elapsed = time.perf_counter() - start

            # Update per-method stats
            if name not in stats:
                stats[name] = {
                    "count": 0,
                    "total_ms": 0.0,
                    "min_ms": float("inf"),
                    "max_ms": 0.0,
                }
            s = stats[name]
            elapsed_ms = elapsed * 1000
            s["count"] += 1
            s["total_ms"] += elapsed_ms
            if elapsed_ms < s["min_ms"]:
                s["min_ms"] = elapsed_ms
            if elapsed_ms > s["max_ms"]:
                s["max_ms"] = elapsed_ms

            # Log individual slow calls (>50ms) for drill-down
            if elapsed_ms > 50:
                call_log.append({
                    "method": name,
                    "wall_ms": round(elapsed_ms, 2),
                    "args_summary": _summarize_args(name, args, kwargs),
                })

            return result

        return timed

    def __setattr__(self, name: str, value: Any) -> None:
        # Delegate attribute setting to the wrapped client
        setattr(self._client, name, value)

    def get_profile_stats(self) -> dict[str, Any]:
        """Return accumulated stats as a dict. Does not clear them."""
        summary = {}
        for method, s in sorted(
            self._stats.items(), key=lambda kv: kv[1]["total_ms"], reverse=True
        ):
            summary[method] = {
                "count": s["count"],
                "total_ms": round(s["total_ms"], 1),
                "avg_ms": round(s["total_ms"] / s["count"], 2) if s["count"] else 0,
                "min_ms": round(s["min_ms"], 2) if s["min_ms"] != float("inf") else 0,
                "max_ms": round(s["max_ms"], 2),
            }
        return summary

    def get_slow_calls(self) -> list[dict]:
        """Return the list of individual slow calls (>50ms)."""
        return list(self._call_log)

    def flush(self, tool_name: str = "", action: str = "") -> None:
        """Write accumulated stats to log file and reset counters."""
        stats = self.get_profile_stats()
        if not stats:
            return

        total_bridge_ms = sum(s["total_ms"] for s in stats.values())
        entry = {
            "ts": time.time(),
            "tool": tool_name,
            "action": action,
            "total_bridge_ms": round(total_bridge_ms, 1),
            "methods": stats,
        }

        slow = self.get_slow_calls()
        if slow:
            entry["slow_calls"] = slow

        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(_LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

        # Reset for next tool call
        self._stats.clear()
        self._call_log.clear()

    def reset_stats(self) -> None:
        """Clear accumulated stats without writing."""
        self._stats.clear()
        self._call_log.clear()


def _summarize_args(method: str, args: tuple, kwargs: dict) -> str:
    """Produce a short argument summary for slow-call logging."""
    if method == "read_memory":
        addr = args[0] if args else kwargs.get("address", "?")
        size = args[1] if len(args) > 1 else kwargs.get("size", "byte")
        return f"0x{addr:08X} ({size})" if isinstance(addr, int) else str(addr)
    if method == "read_memory_range":
        addr = args[0] if args else kwargs.get("address", "?")
        count = kwargs.get("count", args[2] if len(args) > 2 else "?")
        return f"0x{addr:08X} x{count}" if isinstance(addr, int) else str(addr)
    if method == "advance_frames":
        count = args[0] if args else kwargs.get("count", 1)
        return f"{count} frames"
    if method == "dump_memory":
        addr = args[0] if args else kwargs.get("address", "?")
        size = args[1] if len(args) > 1 else kwargs.get("size", "?")
        return f"0x{addr:08X} +{size}" if isinstance(addr, int) else str(addr)
    return ""
