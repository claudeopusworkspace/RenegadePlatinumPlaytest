"""Shared fixtures for battle test suite.

These are integration tests that run against dedicated test melonDS
instances. conftest manages the fleet lifecycle automatically:

    cd /workspace/RenegadePlatinumPlaytest
    .venv/bin/python -m pytest tests/            # spawns 8 emus, runs, tears down
    .venv/bin/python -m pytest --fleet-size=2    # smaller fleet for single-file runs
    .venv/bin/python -m pytest --fleet-size=0    # skip auto-spawn (reuse already-live fleet,
                                                 # or a standalone .melonds_test_bridge.sock)

If a parallel fleet (.melonds_test_bridge_*.sock) is already live when
pytest starts, it's reused *without* teardown at session end — letting
you pre-boot once via `scripts/start_test_emulators.py` and run many
invocations against it.

The playthrough emulator (`.melonds_bridge.sock`) is deliberately NOT in
the fallback search order: tests must never be able to silently land on
the interactive Claude-Code emulator.
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

_PROJECT_ROOT = Path("/workspace/RenegadePlatinumPlaytest")


def _probe_socket(path: Path) -> bool:
    """True if something is listening on `path` right now.

    Unix domain socket files survive process death as stale filesystem
    entries, so glob alone can't tell a live fleet from one that was
    killed with the files left behind. A short `connect()` distinguishes:
    live → success, stale → ConnectionRefusedError immediately.
    """
    import socket as _socket
    s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(str(path))
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False
    finally:
        s.close()


def _discover_parallel_test_sockets() -> list[Path]:
    """Return sorted .melonds_test_bridge_{N}.sock paths with a live listener."""
    candidates = sorted(
        _PROJECT_ROOT.glob(".melonds_test_bridge_*.sock"),
        key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
    )
    return [p for p in candidates if _probe_socket(p)]


def _worker_socket() -> Path | None:
    """Pick the bridge socket for this pytest worker (xdist-aware).

    Under xdist, `PYTEST_XDIST_WORKER` is set to `gw0`, `gw1`, … — use that
    index into the sorted list of parallel test sockets. Outside xdist,
    return the first existing parallel socket if any, else None so the
    caller falls back to the single-emulator search order.
    """
    parallel = _discover_parallel_test_sockets()
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker and worker.startswith("gw"):
        try:
            idx = int(worker[2:])
        except ValueError:
            return None
        if 0 <= idx < len(parallel):
            return parallel[idx]
        return None
    return parallel[0] if parallel else None


# Backend socket configs.
# Parallel test sockets (.melonds_test_bridge_{0..N-1}.sock) are resolved
# separately by _worker_socket() so each xdist worker gets its own emulator.
# The fallbacks below cover single-emulator runs — ONLY the unsuffixed
# standalone test socket from scripts/start_test_emulator.py. The live
# Claude-Code playthrough emulator (.melonds_bridge.sock) is intentionally
# NOT in this list: a `pkill` that killed the fleet mid-session used to
# leave pytest silently targeting the playthrough, trashing whatever the
# interactive Claude instance was doing.
_BACKENDS = {
    "melonds": {
        "sockets": [
            "/workspace/RenegadePlatinumPlaytest/.melonds_test_bridge.sock",
        ],
        "import": "melonds_mcp.client",
    },
    "desmume": {
        "sockets": [
            "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock",
        ],
        "import": "desmume_mcp.client",
    },
}


# ── Fleet lifecycle (auto-spawn / auto-teardown) ──
# conftest takes ownership of the test fleet by default: master pytest
# spawns N emulators before xdist decides worker count, and tears them
# down at session end. If a fleet is already live when pytest starts,
# we detect and reuse it without taking ownership (no teardown), which
# keeps the pre-boot workflow intact (run `scripts/start_test_emulators.py`
# once, then many pytest invocations).
#
# Hook ordering note: the spawn has to happen inside
# `pytest_xdist_auto_num_workers`, NOT in `pytest_configure`. xdist
# makes its "distributed or sequential?" decision inside
# `pytest_cmdline_main`, and that runs BEFORE `pytest_configure` —
# meaning a fleet spawned there arrives too late and xdist silently
# falls back to -n 0 (full suite ran in 13:45 instead of 2:30 before
# this was moved). `pytest_xdist_auto_num_workers` is the earliest
# master-only hook where the config is available, and it's inherently
# skipped in xdist worker subprocesses — exactly what we need.

# Store spawned procs on the module so `pytest_sessionfinish` can find
# them. We can't stash on `config` from inside
# `pytest_xdist_auto_num_workers` because that hook runs before
# `pytest_configure`, and some hook wrappers reject attribute writes on
# config at that phase.
_spawned_fleet_procs: list = []


def pytest_addoption(parser):
    parser.addoption(
        "--fleet-size", type=int, default=8, dest="fleet_size",
        help=(
            "Number of test emulators to auto-spawn when no fleet is live. "
            "Default 8. Set to 0 to skip auto-spawn (reuse an already-live "
            "fleet, or fall through to the standalone test socket)."
        ),
    )
    parser.addoption(
        "--benchmark", action="store_true", default=False,
        help="Enable phase-level profiling and print timing breakdown per test.",
    )


def _is_xdist_worker(config) -> bool:
    """True when this pytest process is an xdist worker (not the master)."""
    return hasattr(config, "workerinput")


def _ensure_fleet_for_master(config) -> int:
    """Spawn the fleet (if needed) and return the live socket count.

    Idempotent: if already-live sockets exist, reuses them without
    taking ownership. If we spawn, procs are stashed on the module for
    teardown in `pytest_sessionfinish`.
    """
    global _spawned_fleet_procs

    already_live = _discover_parallel_test_sockets()
    if already_live:
        if not _spawned_fleet_procs:
            print(
                f"\n[conftest] {len(already_live)} test emulator socket(s) already "
                f"live — reusing without taking ownership.",
            )
        return len(already_live)

    fleet_size = config.getoption("fleet_size", default=8)
    if fleet_size <= 0:
        return 0

    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    from start_test_emulators import start_fleet  # noqa: E402

    print(
        f"\n[conftest] Spawning fleet of {fleet_size} test emulator(s) "
        f"(~{2 * fleet_size}s) ...",
        flush=True,
    )
    try:
        _spawned_fleet_procs = start_fleet(fleet_size)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        pytest.exit(f"Failed to spawn test fleet: {e}", returncode=2)

    print(f"[conftest] Fleet ready: {fleet_size} emulators live.", flush=True)
    return fleet_size


def pytest_xdist_auto_num_workers(config):
    """Resolve `-n auto` to live parallel-test-emulator count; spawn if needed.

    pytest-xdist calls this hook (firstresult) when `-n auto` is in effect.
    The hook is only invoked in the master process — xdist worker
    subprocesses skip it — so it's the natural place to own the
    master-only fleet lifecycle. Doing the spawn inside a later hook
    (e.g., `pytest_configure`) is too late: xdist's
    `pytest_cmdline_main` has already decided distribution mode by
    then.

    Returns 0 when fewer than two sockets are live, which causes xdist
    to set `dist=no` (sequential on a single shared emulator).
    """
    count = _ensure_fleet_for_master(config)
    if count < 2:
        return 0

    print(
        f"\n[conftest] Running pytest-xdist with -n{count} "
        f"(one worker per live test emulator).",
    )
    return count


def pytest_sessionfinish(session, exitstatus):
    """Tear down only the fleet this process spawned; reused fleets are left alone."""
    global _spawned_fleet_procs
    if _is_xdist_worker(session.config):
        return
    if not _spawned_fleet_procs:
        return

    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    from start_test_emulators import stop_fleet  # noqa: E402

    procs = _spawned_fleet_procs
    _spawned_fleet_procs = []
    print(f"\n[conftest] Stopping {len(procs)} auto-spawned emulator(s)...", flush=True)
    stop_fleet(procs)


def _init_client(mod_name: str, sock: str) -> Any:
    """Connect to a bridge socket and prime address resolution."""
    # Stagger the initial session-fixture work across xdist workers: every
    # worker hits its emulator's first load_state at (near-)identical wall
    # clock, and 3+ coincident load_states of the same .mst file reliably
    # SIGBUS a melonDS instance. A 1.5s-per-worker stagger desynchronizes
    # the initial call; subsequent load_states diverge naturally across
    # test files and don't trip the race.
    import time as _time
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    if worker.startswith("gw"):
        try:
            _time.sleep(1.5 * int(worker[2:]))
        except ValueError:
            pass

    mod = importlib.import_module(mod_name)
    client = mod.EmulatorClient(sock)
    client.get_frame_count()  # verify connection

    # Initialize address resolution (tests bypass connection.py).
    # detect_shift needs valid game data in RAM — if the emulator just loaded
    # the ROM (title screen), load a known save state first so the party/badge
    # canary values are present.
    from renegade_mcp.addresses import detect_shift, get_delta
    if get_delta() is None:
        # Always load a known state first — on a fresh ROM (title screen),
        # heap memory is zeroed and detect_shift can't distinguish delta=0
        # from delta=-0x20.
        from helpers import do_load_state
        do_load_state(client, "eterna_city_shiny_swinub_in_party")
        detect_shift(client)

    return client


@pytest.fixture(scope="session")
def emu() -> Any:
    """Connect to whichever test emulator bridge is running. Fails fast if none is up.

    Selection order:
      1. Indexed parallel fleet socket for this xdist worker (or the first
         indexed socket when running sequentially).
      2. The standalone test emulator socket (`.melonds_test_bridge.sock`),
         probed for a live listener.

    The live playthrough emulator (`.melonds_bridge.sock`) is never in this
    list — see module docstring.
    """
    worker_sock = _worker_socket()
    if worker_sock is not None:
        return _init_client("melonds_mcp.client", str(worker_sock))

    forced = os.environ.get("EMU_BACKEND", "").lower()

    if forced in _BACKENDS:
        order = [forced] + [k for k in _BACKENDS if k != forced]
    else:
        order = list(_BACKENDS.keys())  # melonds first by default

    for name in order:
        cfg = _BACKENDS[name]
        for sock in cfg["sockets"]:
            p = Path(sock)
            # Probe rather than just checking file existence — Unix socket
            # files linger as stale FS entries when the server crashes or
            # was SIGKILL'd, and a stale file would otherwise make
            # _init_client's connect() raise instead of falling through.
            if p.exists() and _probe_socket(p):
                return _init_client(cfg["import"], sock)

    pytest.skip(
        "No test emulator bridge is live. Either run pytest without "
        "--fleet-size=0 (default auto-spawns 8 emulators) or start "
        "scripts/start_test_emulator.py / start_test_emulators.py manually."
    )


# ── Streaming suppression ──
# Disable MelonMCP's auto-streaming for the test session. Streaming's renderer
# subprocess can zombie under rapid load_rom/load_state/advance_frames churn
# and silently hang the whole emulator (claudeopusworkspace/MelonMCP#4). The
# set_stream_config override sits at tier 0 of settings.get_stream()'s chain,
# scoped to the MelonMCP server process — no file writes, no env fiddling.
# Exposed on the bridge in claudeopusworkspace/MelonMCP#7 so conftest can
# call it directly without needing an MCP session in the loop.


@pytest.fixture(scope="session", autouse=True)
def _disable_streaming(emu) -> Any:
    """Force streaming off for the life of the test session, restore after."""
    if not hasattr(emu, "set_stream_config"):
        # Older MelonMCP or DesmumeMCP backend — nothing to do.
        yield
        return

    emu.set_stream_config(enabled=False)

    # Kill any renderer + ffmpeg processes left from prior interactive play.
    # Bridge exposure landed in claudeopusworkspace/MelonMCP#8. hasattr guard
    # keeps this graceful against older MelonMCP builds / DesmumeMCP.
    if hasattr(emu, "stop_video_stream"):
        try:
            emu.stop_video_stream()
        except Exception:
            pass

    try:
        yield
    finally:
        # Restore default resolution (env vars + settings.json) so
        # interactive play after pytest gets streaming back.
        emu.set_stream_config(enabled=None)


# ── Phase profiling ──
# Activated by --benchmark flag (registered in pytest_addoption above) or
# the RENEGADE_BENCHMARK=1 env var.

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
