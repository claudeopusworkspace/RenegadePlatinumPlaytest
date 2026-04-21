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

conftest.py auto-detects the number of running sockets and forwards to
pytest-xdist with -n matching. No flags required on the pytest side.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path("/workspace/RenegadePlatinumPlaytest")
LAUNCHER = PROJECT_ROOT / "scripts" / "start_test_emulator.py"
WORKERS_DIR = PROJECT_ROOT / ".workers"
SHARED_ROM = PROJECT_ROOT / "RenegadePlatinum.nds"
SHARED_LINKS = ("savestates", "macros", "data")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--count", type=int, default=2,
        help=(
            "Number of emulator instances (default 2). "
            "N>=3 SIGBUSes on this container because /dev/shm defaults to 64 MB "
            "and melonDS's JIT fastmem needs ~17 MB of tmpfs per worker (see "
            "MelonMCP#9 — diagnosed). To scale up: "
            "`sudo mount -o remount,size=8G /dev/shm` and optionally "
            "`sudo sysctl -w vm.max_map_count=1048576`, then --count 8."
        ),
    )
    parser.add_argument(
        "--startup-timeout", type=float, default=180.0,
        help="Seconds to wait for all sockets to come up before giving up.",
    )
    return parser.parse_args()


def _socket_path(index: int) -> Path:
    return PROJECT_ROOT / f".melonds_test_bridge_{index}.sock"


def _worker_dir(index: int) -> Path:
    return WORKERS_DIR / f"worker_{index}"


def _prepare_worker_dir(index: int) -> Path:
    """Create `.workers/worker_{i}/` with a ROM copy and read-only symlinks."""
    wd = _worker_dir(index)
    wd.mkdir(parents=True, exist_ok=True)

    # ROM: copy (not symlink) so melonDS derives a unique .sav path per worker.
    worker_rom = wd / SHARED_ROM.name
    if not worker_rom.exists() or worker_rom.stat().st_size != SHARED_ROM.stat().st_size:
        shutil.copy2(SHARED_ROM, worker_rom)

    # Symlinks to shared read-only directories — savestates, macros, data.
    for name in SHARED_LINKS:
        target = PROJECT_ROOT / name
        link = wd / name
        if not target.exists():
            continue  # optional (e.g., data/ may not exist)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target.resolve())

    return wd


def main() -> int:
    args = _parse_args()
    n = args.count
    if n < 1:
        print("--count must be >= 1", file=sys.stderr)
        return 2

    if not SHARED_ROM.exists():
        print(f"Shared ROM not found at {SHARED_ROM}", file=sys.stderr)
        return 2

    # Clean up stale sockets from a prior crashed run.
    for i in range(n):
        p = _socket_path(i)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    WORKERS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Preparing {n} worker dirs under {WORKERS_DIR} ...")
    worker_dirs = [_prepare_worker_dir(i) for i in range(n)]

    procs: list[subprocess.Popen] = []
    python = sys.executable

    # Stagger startup: each melonDS init mmaps the ROM and allocates ~200MB of
    # ARM memory; four-plus processes racing that init simultaneously reliably
    # SIGBUS one of them. A small stagger lets each instance fully initialize
    # before the next begins.
    STAGGER_S = 2.0

    print(f"Spawning {n} test emulators (staggered ~{STAGGER_S}s between each)...")
    for i in range(n):
        wd = worker_dirs[i]
        cmd = [
            python, str(LAUNCHER),
            "--socket", str(_socket_path(i)),
            "--data-dir", str(wd),
            "--rom", str(wd / SHARED_ROM.name),
        ]
        proc = subprocess.Popen(cmd, env=os.environ.copy())
        procs.append(proc)
        if i < n - 1:
            time.sleep(STAGGER_S)

    # Wait for all sockets to appear.
    deadline = time.monotonic() + args.startup_timeout
    pending = set(range(n))
    while pending and time.monotonic() < deadline:
        ready = {i for i in pending if _socket_path(i).exists()}
        if ready:
            for i in sorted(ready):
                print(f"  [ok] emulator {i} up at {_socket_path(i).name}")
            pending -= ready
        if pending:
            for i, proc in enumerate(procs):
                if i in pending and proc.poll() is not None:
                    print(
                        f"  [FAIL] emulator {i} exited with code {proc.returncode} during startup",
                        file=sys.stderr,
                    )
                    _shutdown(procs)
                    return 1
            time.sleep(0.5)

    if pending:
        print(f"Timed out waiting for emulators: {sorted(pending)}", file=sys.stderr)
        _shutdown(procs)
        return 1

    print(f"\nAll {n} test emulators ready. Run pytest in another terminal.")
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
                    print(f"Emulator {i} exited unexpectedly (code {proc.returncode}); tearing down fleet.")
                    stopped["value"] = True
                    break
            time.sleep(1.0)
    finally:
        _shutdown(procs)

    return 0


def _shutdown(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)

    deadline = time.monotonic() + 10.0
    for proc in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)

    print("Fleet down.")


if __name__ == "__main__":
    sys.exit(main())
