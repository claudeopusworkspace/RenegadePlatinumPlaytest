"""Launch a dedicated melonDS emulator for the test suite.

Runs a standalone EmulatorState + bridge server on a test-only Unix socket so
pytest can hit its own emulator without disturbing the one Claude Code has
running for interactive play.

Usage:
    .venv/bin/python scripts/start_test_emulator.py
    .venv/bin/python scripts/start_test_emulator.py --socket /path/to/sock
    .venv/bin/python scripts/start_test_emulator.py --index 3   # → .melonds_test_bridge_3.sock

Then in another terminal:
    .venv/bin/python -m pytest tests/ -v

The test conftest prefers the test socket(s) when present, so no env var
wrangling is needed. Ctrl-C (or SIGTERM) shuts the emulator down cleanly.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("RENEGADE_TEST_DATA_DIR", "/workspace/RenegadePlatinumPlaytest"))
DEFAULT_ROM = Path(os.environ.get("RENEGADE_TEST_ROM", DEFAULT_DATA_DIR / "RenegadePlatinum.nds"))
DEFAULT_SOCKET = Path(os.environ.get(
    "MELONDS_BRIDGE_SOCK",
    DEFAULT_DATA_DIR / ".melonds_test_bridge.sock",
))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--socket", type=Path, default=None,
        help="Unix socket path for the bridge. Overrides --index and MELONDS_BRIDGE_SOCK.",
    )
    parser.add_argument(
        "--index", type=int, default=None,
        help="Worker index — convenience for indexed sockets (.melonds_test_bridge_{N}.sock).",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR,
        help=f"Data directory for savestates/macros (default: {DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--rom", type=Path, default=DEFAULT_ROM,
        help=f"ROM path (default: {DEFAULT_ROM}).",
    )
    return parser.parse_args()


def _resolve_socket(args: argparse.Namespace) -> Path:
    if args.socket is not None:
        return args.socket
    if args.index is not None:
        return args.data_dir / f".melonds_test_bridge_{args.index}.sock"
    return DEFAULT_SOCKET


def _configure_logging(data_dir: Path, socket_path: Path) -> None:
    """Log to stderr + a dedicated rotating file per socket so parallel instances don't overlap."""
    log_name = f"melonds_test_mcp_{socket_path.stem}.log"
    log_path = data_dir / log_name
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    stderr_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)


def main() -> int:
    args = _parse_args()
    socket_path = _resolve_socket(args)

    sys.path.insert(0, "/workspace/MelonMCP")
    os.environ["MELONDS_BRIDGE_SOCK"] = str(socket_path)

    _configure_logging(args.data_dir, socket_path)
    log = logging.getLogger("test_emulator")

    from melonds_mcp.bridge import BridgeServer
    from melonds_mcp.emulator import EmulatorState

    if socket_path.exists():
        log.warning("Stale socket at %s — removing", socket_path)
        socket_path.unlink()

    holder = EmulatorState(data_dir=args.data_dir)
    # Match server.create_server() invariants.
    holder._journal = None
    holder._renderer_proc = None
    holder._stream_start_frame = 0

    log.info("Initializing melonDS (data_dir=%s)", args.data_dir)
    log.info(holder.initialize())

    log.info("Loading ROM: %s", args.rom)
    log.info(holder.load_rom(str(args.rom)))

    bridge = BridgeServer(holder, str(socket_path))
    bridge_path = bridge.start()
    holder._bridge = bridge
    log.info("Bridge listening on %s", bridge_path)
    log.info("Test emulator ready. Ctrl-C to shut down.")

    stop = threading.Event()

    def _shutdown(signum, _frame):
        log.info("Received signal %d — shutting down", signum)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    stop.wait()

    log.info("Stopping bridge")
    try:
        bridge.stop()
    except Exception:
        log.exception("Bridge stop failed")
    if socket_path.exists():
        try:
            socket_path.unlink()
        except OSError:
            pass
    log.info("Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
