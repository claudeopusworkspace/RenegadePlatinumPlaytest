"""Shared fixtures for battle test suite.

These are integration tests that require a running emulator (melonDS or DeSmuME)
connected via the bridge socket. Start the emulator + bridge first:

    1. init_emulator (via melonds or desmume MCP)
    2. load_rom (RenegadePlatinum.nds)

Then run:
    cd /workspace/RenegadePlatinumPlaytest
    python -m pytest tests/ -v

Set EMU_BACKEND=desmume or EMU_BACKEND=melonds to force a specific backend.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from renegade_mcp.phase_timer import PhaseTimer, set_timer

# Ensure both projects are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ dir for helpers
sys.path.insert(0, "/workspace/MelonMCP")
sys.path.insert(0, "/workspace/DesmumeMCP")
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest")

# Backend socket configs (same order as connection.py)
_BACKENDS = {
    "melonds": {
        "sockets": [
            "/workspace/RenegadePlatinumPlaytest/.melonds_bridge.sock",
            "/workspace/MelonMCP/.melonds_bridge.sock",
        ],
        "import": "melonds_mcp.client",
    },
    "desmume": {
        "sockets": [
            "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock",
            "/workspace/DesmumeMCP/.desmume_bridge.sock",
        ],
        "import": "desmume_mcp.client",
    },
}


@pytest.fixture(scope="session")
def emu() -> Any:
    """Connect to whichever emulator bridge is running. Fails fast if neither is up."""
    forced = os.environ.get("EMU_BACKEND", "").lower()

    # Build search order: forced backend first, then the other
    if forced in _BACKENDS:
        order = [forced] + [k for k in _BACKENDS if k != forced]
    else:
        order = list(_BACKENDS.keys())  # melonds first by default

    for name in order:
        cfg = _BACKENDS[name]
        for sock in cfg["sockets"]:
            if Path(sock).exists():
                mod = importlib.import_module(cfg["import"])
                client = mod.EmulatorClient(sock)
                client.get_frame_count()  # verify connection

                # Initialize address resolution (tests bypass connection.py).
                # detect_shift needs valid game data in RAM — if the emulator
                # just loaded the ROM (title screen), load a known save state
                # first so the party/badge canary values are present.
                from renegade_mcp.addresses import detect_shift, get_delta
                if get_delta() is None:
                    # Always load a known state first — on a fresh ROM
                    # (title screen), heap memory is zeroed and detect_shift
                    # can't distinguish delta=0 from delta=-0x20.
                    from helpers import do_load_state
                    do_load_state(client, "eterna_city_shiny_swinub_in_party")
                    detect_shift(client)

                return client

    pytest.skip("No emulator bridge socket found — is an emulator running?")


# ── Phase profiling ──
# Activated by --benchmark flag or RENEGADE_BENCHMARK=1 env var.

def pytest_addoption(parser):
    parser.addoption(
        "--benchmark", action="store_true", default=False,
        help="Enable phase-level profiling and print timing breakdown per test.",
    )


@pytest.fixture(autouse=True)
def _phase_timer(request, emu):
    """Auto-activate PhaseTimer when benchmarking is enabled."""
    benchmark = (
        request.config.getoption("--benchmark", default=False)
        or os.environ.get("RENEGADE_BENCHMARK") == "1"
    )
    if not benchmark:
        yield
        return

    import time as _time
    timer = PhaseTimer(emu=emu)
    set_timer(timer)
    t_start = _time.perf_counter()
    yield timer
    wall_s = _time.perf_counter() - t_start
    set_timer(None)

    # Collect results directly into module-level list (fixture teardown
    # runs after pytest_runtest_makereport for "call", so stashing on
    # request.node doesn't work — the report hook fires too early).
    summary = timer.summary()
    if summary:
        _benchmark_results.append({
            "test": request.node.nodeid,
            "wall_s": round(wall_s, 2),
            "phases": summary,
            "total_phase_ms": round(timer.total_ms(), 1),
        })


# ── Benchmark report collector ──

_benchmark_results: list[dict] = []


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print benchmark results at the end of the test run."""
    if not _benchmark_results:
        return

    terminalreporter.write_sep("=", "PHASE BENCHMARK RESULTS")

    for entry in sorted(_benchmark_results, key=lambda e: -e["wall_s"]):
        test_name = entry["test"].split("::")[-1]
        terminalreporter.write_line(
            f"\n{'─' * 70}"
        )
        terminalreporter.write_line(
            f"  {entry['test']}  [{entry['wall_s']}s]"
        )
        terminalreporter.write_line(
            f"{'─' * 70}"
        )

        phases = entry["phases"]
        if not phases:
            terminalreporter.write_line("    (no phases recorded)")
            continue

        # Column header
        terminalreporter.write_line(
            f"    {'Phase':<30} {'Wall ms':>10} {'Frames':>8} {'Count':>6} {'%':>6}"
        )
        terminalreporter.write_line(f"    {'─' * 62}")

        for name, data in phases.items():
            terminalreporter.write_line(
                f"    {name:<30} {data['wall_ms']:>10.1f} {data['frames']:>8} {data['count']:>6} {data['pct']:>5.1f}%"
            )

        accounted = entry["total_phase_ms"]
        total_wall = entry["wall_s"] * 1000
        unaccounted = total_wall - accounted
        if total_wall > 0:
            terminalreporter.write_line(f"    {'─' * 62}")
            terminalreporter.write_line(
                f"    {'(instrumented total)':<30} {accounted:>10.1f}"
            )
            if unaccounted > 50:
                terminalreporter.write_line(
                    f"    {'(uninstrumented overhead)':<30} {unaccounted:>10.1f}"
                )

    # Write JSON results to file for programmatic analysis
    results_path = Path(__file__).resolve().parent.parent / "logs" / "benchmark_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(results_path, "w") as f:
        json.dump(_benchmark_results, f, indent=2)
    terminalreporter.write_line(f"\nResults saved to {results_path}")
