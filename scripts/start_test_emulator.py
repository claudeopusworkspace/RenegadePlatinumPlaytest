"""Launch a dedicated melonDS emulator for the test suite.

Runs a standalone EmulatorState + bridge server on a test-only Unix socket so
pytest can hit its own emulator without disturbing the one Claude Code has
running for interactive play.

Usage:
    .venv/bin/python scripts/start_test_emulator.py

Then in another terminal:
    .venv/bin/python -m pytest tests/ -v

The test conftest prefers the test socket when it's present, so no env var
wrangling is needed. Ctrl-C (or SIGTERM) shuts the emulator down cleanly.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import threading
from pathlib import Path

# Default paths — override via env vars if needed.
DATA_DIR = Path(os.environ.get("RENEGADE_TEST_DATA_DIR", "/workspace/RenegadePlatinumPlaytest"))
ROM_PATH = Path(os.environ.get("RENEGADE_TEST_ROM", DATA_DIR / "RenegadePlatinum.nds"))
SOCKET_PATH = Path(os.environ.get(
    "MELONDS_BRIDGE_SOCK",
    DATA_DIR / ".melonds_test_bridge.sock",
))


def _configure_logging() -> None:
    """Log to stderr + a dedicated rotating file so we don't trample the live emulator's log."""
    log_path = DATA_DIR / "melonds_test_mcp.log"
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
    sys.path.insert(0, "/workspace/MelonMCP")
    os.environ["MELONDS_BRIDGE_SOCK"] = str(SOCKET_PATH)

    _configure_logging()
    log = logging.getLogger("test_emulator")

    from melonds_mcp.bridge import BridgeServer
    from melonds_mcp.emulator import EmulatorState

    if SOCKET_PATH.exists():
        log.warning("Stale socket at %s — removing", SOCKET_PATH)
        SOCKET_PATH.unlink()

    holder = EmulatorState(data_dir=DATA_DIR)
    # Match server.create_server() invariants.
    holder._journal = None
    holder._renderer_proc = None
    holder._stream_start_frame = 0

    log.info("Initializing melonDS (data_dir=%s)", DATA_DIR)
    log.info(holder.initialize())

    log.info("Loading ROM: %s", ROM_PATH)
    log.info(holder.load_rom(str(ROM_PATH)))

    bridge = BridgeServer(holder, str(SOCKET_PATH))
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
    if SOCKET_PATH.exists():
        try:
            SOCKET_PATH.unlink()
        except OSError:
            pass
    log.info("Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
