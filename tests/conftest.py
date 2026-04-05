"""Shared fixtures for battle test suite.

These are integration tests that require a running melonDS emulator
connected via the bridge socket. Start the emulator + bridge first:

    1. init_emulator (via melonds MCP)
    2. load_rom (RenegadePlatinum.nds)

Then run:
    cd /workspace/RenegadePlatinumPlaytest
    MelonMCP/.venv/bin/python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Ensure both projects are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ dir for helpers
sys.path.insert(0, "/workspace/MelonMCP")
sys.path.insert(0, "/workspace/RenegadePlatinumPlaytest")

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


@pytest.fixture(scope="session")
def emu() -> EmulatorClient:
    """Connect to the running melonDS bridge. Fails fast if emulator isn't up."""
    from melonds_mcp.client import EmulatorClient

    for sock in [
        "/workspace/RenegadePlatinumPlaytest/.melonds_bridge.sock",
        "/workspace/MelonMCP/.melonds_bridge.sock",
        ".melonds_bridge.sock",
    ]:
        if Path(sock).exists():
            client = EmulatorClient(sock)
            client.get_frame_count()  # verify connection
            return client

    pytest.skip("melonDS bridge socket not found — is the emulator running?")
