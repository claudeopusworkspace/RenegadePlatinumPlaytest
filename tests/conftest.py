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
                    try:
                        detect_shift(client)
                    except RuntimeError:
                        # No valid game data — load a save state and retry
                        from helpers import do_load_state
                        do_load_state(client, "eterna_city_shiny_swinub_in_party")
                        detect_shift(client)

                return client

    pytest.skip("No emulator bridge socket found — is an emulator running?")
