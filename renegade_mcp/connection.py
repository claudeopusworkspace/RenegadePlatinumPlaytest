"""Lazy, reconnectable bridge client wrapper for the DS emulator.

Supports both melonDS and DeSmuME backends. The active backend is determined by:
1. EMU_BACKEND env var ("melonds" or "desmume")
2. Auto-detection: whichever bridge socket exists (melonDS preferred)

The game MCP server starts without requiring an emulator connection.
Connection is only attempted when a tool is actually called.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Both clients expose an identical API — use either for type hints
    from melonds_mcp.client import EmulatorClient

# Backend configs: (socket search paths, client import module)
_BACKENDS = {
    "melonds": {
        "sockets": [".melonds_bridge.sock", "MelonMCP/.melonds_bridge.sock"],
        "env_var": "MELONDS_BRIDGE_SOCK",
        "import": "melonds_mcp.client",
    },
    "desmume": {
        "sockets": [".desmume_bridge.sock", "DesmumeMCP/.desmume_bridge.sock"],
        "env_var": "DESMUME_BRIDGE_SOCK",
        "import": "desmume_mcp.client",
    },
}


def _detect_backend() -> str | None:
    """Detect which backend to use from env var or socket presence."""
    import os

    # Explicit override
    forced = os.environ.get("EMU_BACKEND", "").lower()
    if forced in _BACKENDS:
        return forced

    # Auto-detect: check for running sockets (melonDS first)
    for name, cfg in _BACKENDS.items():
        env_path = os.environ.get(cfg["env_var"])
        if env_path and Path(env_path).exists():
            return name
        for rel in cfg["sockets"]:
            if Path(rel).exists():
                return name

    return None


class BridgeConnection:
    """Lazy bridge client wrapper — connects on first use, reconnects on failure."""

    def __init__(self) -> None:
        self._client: Any = None
        self._backend: str | None = None

    @property
    def backend(self) -> str | None:
        """The active backend name, or None if not connected."""
        return self._backend

    def get_client(self) -> EmulatorClient:
        """Get a connected EmulatorClient, or raise RuntimeError with a clear message."""
        if self._client is not None:
            try:
                self._client.get_frame_count()
                return self._client
            except Exception:
                self._client = None
                self._backend = None

        # Detect which backend to use
        backend = _detect_backend()
        if backend is None:
            raise RuntimeError(
                "Emulator not connected. No bridge socket found for melonDS or DeSmuME. "
                "Call init_emulator and load_rom via the emulator MCP server first."
            )

        cfg = _BACKENDS[backend]
        socket_path = self._find_socket(cfg)
        if socket_path is None:
            raise RuntimeError(
                f"EMU_BACKEND={backend} but no bridge socket found. "
                "Call init_emulator and load_rom first."
            )

        try:
            import importlib

            mod = importlib.import_module(cfg["import"])
            client_cls = mod.EmulatorClient
            self._client = client_cls(str(socket_path))
            self._client.get_frame_count()
            self._backend = backend

            # Wrap client in profiling proxy if enabled
            from renegade_mcp.profiler import is_enabled as _profile_enabled
            if _profile_enabled():
                from renegade_mcp.profiler import ProfiledClient
                self._client = ProfiledClient(self._client)

            # Detect heap address shift for this emulator
            from renegade_mcp.addresses import detect_shift
            detect_shift(self._client)

            return self._client
        except Exception as e:
            self._client = None
            self._backend = None
            raise RuntimeError(
                f"Cannot connect to {backend} bridge at {socket_path}: {e}"
            ) from e

    def reset(self) -> None:
        """Force reconnection on next call."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._backend = None

        # Clear cached address resolution
        from renegade_mcp.addresses import reset as reset_addresses
        reset_addresses()

    @staticmethod
    def _find_socket(cfg: dict) -> Path | None:
        """Find the bridge socket for a given backend config."""
        import os

        env_path = os.environ.get(cfg["env_var"])
        if env_path:
            p = Path(env_path)
            if p.exists():
                return p

        for rel in cfg["sockets"]:
            p = Path(rel)
            if p.exists():
                return p

        return None


# Module-level singleton
_bridge = BridgeConnection()


def get_client() -> EmulatorClient:
    """Get a connected EmulatorClient. Raises RuntimeError if unavailable."""
    return _bridge.get_client()


def reset_connection() -> None:
    """Force reconnection on next tool call."""
    _bridge.reset()
