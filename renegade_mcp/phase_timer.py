"""Lightweight phase-level profiler for renegade_mcp tools.

Tracks wall-clock time and emulator frame count per named "phase" within
a tool call.  Phases are delimited by context managers::

    from renegade_mcp.phase_timer import phase

    def navigate_to_impl(emu, x, y):
        with phase("bfs_pathfind"):
            path = bfs(start, goal, grid)
        with phase("walk_path"):
            execute_path(emu, path)

When no PhaseTimer is active on the current thread (the normal case during
live gameplay), ``phase()`` returns a zero-cost null context — no allocation,
no timing, no frame reads.

Activation is handled by the test harness (conftest fixture) or by the
``@renegade_tool`` decorator when ``RENEGADE_PROFILE=1``.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any


_local = threading.local()


class PhaseTimer:
    """Accumulates per-phase wall time and frame counts."""

    def __init__(self, emu: Any = None) -> None:
        self._emu = emu
        self._phases: dict[str, dict[str, float]] = {}

    @contextmanager
    def phase(self, name: str):
        """Time a named phase.  Accumulates across multiple calls."""
        fc_start = self._emu.get_frame_count() if self._emu else 0
        t_start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            frames = (
                self._emu.get_frame_count() - fc_start if self._emu else 0
            )
            if name not in self._phases:
                self._phases[name] = {
                    "wall_ms": 0.0,
                    "frames": 0,
                    "count": 0,
                }
            p = self._phases[name]
            p["wall_ms"] += elapsed_ms
            p["frames"] += frames
            p["count"] += 1

    def summary(self) -> dict[str, dict[str, Any]]:
        """Return phase data sorted by wall time descending."""
        total_ms = sum(p["wall_ms"] for p in self._phases.values())
        out: dict[str, dict[str, Any]] = {}
        for name, p in sorted(
            self._phases.items(), key=lambda kv: -kv[1]["wall_ms"]
        ):
            pct = (p["wall_ms"] / total_ms * 100) if total_ms > 0 else 0
            out[name] = {
                "wall_ms": round(p["wall_ms"], 1),
                "frames": int(p["frames"]),
                "count": int(p["count"]),
                "pct": round(pct, 1),
            }
        return out

    def total_ms(self) -> float:
        return sum(p["wall_ms"] for p in self._phases.values())

    def reset(self) -> None:
        self._phases.clear()


# ── Thread-local access ──────────────────────────────────────────────

def set_timer(timer: PhaseTimer | None) -> None:
    """Activate a PhaseTimer on the current thread."""
    _local.timer = timer


def get_timer() -> PhaseTimer | None:
    """Get the active PhaseTimer, or None."""
    return getattr(_local, "timer", None)


# ── Convenience context manager (zero-cost when inactive) ────────────

class _NullContext:
    """No-op context manager returned when profiling is off."""
    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NULL = _NullContext()


def phase(name: str):
    """Get a phase context manager.

    Returns the real timer's phase if profiling is active, otherwise a
    singleton no-op context (~0 ns overhead).
    """
    timer = getattr(_local, "timer", None)
    if timer is not None:
        return timer.phase(name)
    return _NULL
