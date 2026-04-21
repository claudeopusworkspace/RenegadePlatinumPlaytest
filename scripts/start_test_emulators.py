"""Launch N isolated test emulators for multi-worker pytest runs.

Each worker gets its own data_dir under `.workers/worker_{i}/` so melonDS's
derived `.sav` (battery save) path is unique per process. Without this, 8
emulators mmap the same RenegadePlatinum.sav at startup and one reliably
SIGBUSes as they race on the shared mapping.

Per-worker layout:

    .workers/worker_{i}/
        RenegadePlatinum.nds   (copy of the shared ROM — ~16 MB)
        RenegadePlatinum.sav   (created by melonDS, not shared)
        savestates -> ../../savestates   (read-only symlink, shared)
        macros     -> ../../macros       (read-only symlink, shared)
        data       -> ../../data         (read-only symlink, shared)

Usage:
    .venv/bin/python scripts/start_test_emulators.py              # default 8 workers
    .venv/bin/python scripts/start_test_emulators.py --count 4

Then in another terminal:
    .venv/bin/python -m pytest tests/ -v

conftest.py auto-spawns its own fleet when none is running and tears it
down at session end — running this script manually is only needed when
you want a fleet to persist across many pytest invocations (or for
debugging a single emulator interactively).

The `start_fleet` and `stop_fleet` functions are the public API that
conftest.py imports; `main()` is the CLI wrapper.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket as _socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path("/workspace/RenegadePlatinumPlaytest")
LAUNCHER = PROJECT_ROOT / "scripts" / "start_test_emulator.py"
WORKERS_DIR = PROJECT_ROOT / ".workers"
SHARED_ROM = PROJECT_ROOT / "RenegadePlatinum.nds"
SHARED_LINKS = ("savestates", "macros", "data")

# Stagger between per-worker launches. Each melonDS init mmaps the ROM and
# allocates ~200MB of ARM memory; four-plus processes racing that init
# simultaneously reliably SIGBUS one of them. A small stagger lets each
# instance fully initialize before the next begins.
_STAGGER_S = 2.0

# Deadline after which an unresponsive proc is SIGKILLed during shutdown.
_SHUTDOWN_TERM_GRACE_S = 10.0


def socket_path(index: int) -> Path:
    """Path to the Unix socket for test-fleet worker `index`."""
    return PROJECT_ROOT / f".melonds_test_bridge_{index}.sock"


def _worker_dir(index: int) -> Path:
    return WORKERS_DIR / f"worker_{index}"


def _probe_socket(path: Path) -> bool:
    """True if something is accepting connections on `path` right now."""
    s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(str(path))
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False
    finally:
        s.close()


def discover_live_fleet(max_workers: int = 32) -> list[int]:
    """Return indices of test-fleet sockets with a live listener right now."""
    live: list[int] = []
    for i in range(max_workers):
        if _probe_socket(socket_path(i)):
            live.append(i)
    return live


def _prepare_worker_dir(index: int) -> Path:
    """Create `.workers/worker_{i}/` with a ROM copy and read-only symlinks."""
    wd = _worker_dir(index)
    wd.mkdir(parents=True, exist_ok=True)

    worker_rom = wd / SHARED_ROM.name
    if not worker_rom.exists() or worker_rom.stat().st_size != SHARED_ROM.stat().st_size:
        shutil.copy2(SHARED_ROM, worker_rom)

    for name in SHARED_LINKS:
        target = PROJECT_ROOT / name
        link = wd / name
        if not target.exists():
            continue  # optional (e.g., data/ may not exist)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target.resolve())

    return wd


def start_fleet(
    count: int = 8,
    startup_timeout: float = 180.0,
    stagger_s: float = _STAGGER_S,
) -> list[subprocess.Popen]:
    """Spawn `count` isolated test emulators and wait for all sockets to go live.

    Returns the list of child `subprocess.Popen` objects. On startup failure
    (any child exits or the timeout expires) every child is torn down before
    the exception propagates, so no orphans are left behind.

    Raises:
        FileNotFoundError: if the shared ROM is missing.
        ValueError: if `count` < 1.
        RuntimeError: if startup times out or a child exits during boot.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    if not SHARED_ROM.exists():
        raise FileNotFoundError(f"Shared ROM not found at {SHARED_ROM}")

    # Clean up stale sockets from a prior crashed run.
    for i in range(count):
        p = socket_path(i)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    worker_dirs = [_prepare_worker_dir(i) for i in range(count)]

    procs: list[subprocess.Popen] = []
    python = sys.executable

    for i in range(count):
        wd = worker_dirs[i]
        cmd = [
            python, str(LAUNCHER),
            "--socket", str(socket_path(i)),
            "--data-dir", str(wd),
            "--rom", str(wd / SHARED_ROM.name),
        ]
        proc = subprocess.Popen(cmd, env=os.environ.copy())
        procs.append(proc)
        if i < count - 1 and stagger_s > 0:
            time.sleep(stagger_s)

    # Wait for all sockets to become reachable (file existence alone isn't
    # enough — the bridge thread must actually start listening).
    deadline = time.monotonic() + startup_timeout
    pending = set(range(count))
    while pending and time.monotonic() < deadline:
        ready = {i for i in pending if _probe_socket(socket_path(i))}
        pending -= ready
        if pending:
            for i, proc in enumerate(procs):
                if i in pending and proc.poll() is not None:
                    stop_fleet(procs)
                    raise RuntimeError(
                        f"Test emulator {i} exited with code {proc.returncode} "
                        f"during startup"
                    )
            time.sleep(0.5)

    if pending:
        stop_fleet(procs)
        raise RuntimeError(
            f"Timed out after {startup_timeout:.0f}s waiting for emulators "
            f"{sorted(pending)} to come up"
        )

    return procs


def stop_fleet(
    procs: list[subprocess.Popen], term_grace_s: float = _SHUTDOWN_TERM_GRACE_S,
) -> None:
    """SIGTERM every child, wait up to `term_grace_s`, then SIGKILL the rest.

    The test emulators' own SIGTERM handler unlinks its socket before
    exiting, so callers don't need a separate socket-file cleanup step.
    """
    for proc in procs:
        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    deadline = time.monotonic() + term_grace_s
    for proc in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--count", type=int, default=8,
        help=(
            "Number of emulator instances (default 8). "
            "Requires /dev/shm >= ~150 MB (8 workers × ~17 MB JIT fastmem). "
            "If container was started without `--shm-size`, /dev/shm defaults "
            "to 64 MB — drop --count to 2 or restart the container with "
            "`--shm-size=8g`. See MelonMCP#9 for the SIGBUS diagnosis."
        ),
    )
    parser.add_argument(
        "--startup-timeout", type=float, default=180.0,
        help="Seconds to wait for all sockets to come up before giving up.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    print(f"Preparing {args.count} worker dirs + spawning staggered fleet...")
    try:
        procs = start_fleet(args.count, startup_timeout=args.startup_timeout)
    except (ValueError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    for i in range(args.count):
        print(f"  [ok] emulator {i} up at {socket_path(i).name}")

    print(f"\nAll {args.count} test emulators ready. Run pytest in another terminal.")
    print("Ctrl-C here to shut the fleet down.\n")

    stopped = {"value": False}

    def _signal(signum, _frame):
        if stopped["value"]:
            return
        stopped["value"] = True
        print(f"\nReceived signal {signum} — shutting down fleet.")

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)

    try:
        while not stopped["value"]:
            for i, proc in enumerate(procs):
                if proc.poll() is not None:
                    print(
                        f"Emulator {i} exited unexpectedly "
                        f"(code {proc.returncode}); tearing down fleet."
                    )
                    stopped["value"] = True
                    break
            time.sleep(1.0)
    finally:
        stop_fleet(procs)
        print("Fleet down.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
