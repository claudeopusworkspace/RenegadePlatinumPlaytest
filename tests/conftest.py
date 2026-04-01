"""Shared fixtures for battle test suite.

These are integration tests that require a running DeSmuME emulator
connected via the bridge socket. Start the emulator + bridge first:

    1. init_emulator (via desmume MCP)
    2. load_rom (RenegadePlatinum.nds)

Then run:
    cd /workspace/RenegadePlatinumPlaytest
    DesmumeMCP/.venv/bin/python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Ensure both projects are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ dir for helpers
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest/DesmumeMCP")
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest")

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient


@pytest.fixture(scope="session")
def emu() -> EmulatorClient:
    """Connect to the running DeSmuME bridge. Fails fast if emulator isn't up."""
    from desmume_mcp.client import EmulatorClient

    for sock in [
        "/workspace/RenegadePlatinumPlaytest/.desmume_bridge.sock",
        "/workspace/RenegadePlatinumPlaytest/DesmumeMCP/.desmume_bridge.sock",
        ".desmume_bridge.sock",
    ]:
        if Path(sock).exists():
            client = EmulatorClient(sock)
            client.get_frame_count()  # verify connection
            return client

    pytest.skip("DeSmuME bridge socket not found — is the emulator running?")
