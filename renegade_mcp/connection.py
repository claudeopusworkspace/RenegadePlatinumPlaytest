"""Lazy, reconnectable bridge client wrapper for the DeSmuME emulator.

The game MCP server starts without requiring an emulator connection.
Connection is only attempted when a tool is actually called.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desmume_mcp.client import EmulatorClient

# Default bridge socket location (project root CWD + DesmumeMCP data dir)
_SOCKET_SEARCH_PATHS = [
    ".desmume_bridge.sock",
    "DesmumeMCP/.desmume_bridge.sock",
]


class BridgeConnection:
    """Lazy bridge client wrapper — connects on first use, reconnects on failure."""

    def __init__(self) -> None:
        self._client: EmulatorClient | None = None

    def get_client(self) -> EmulatorClient:
        """Get a connected EmulatorClient, or raise RuntimeError with a clear message."""
        if self._client is not None:
            try:
                # Quick health check — if socket is dead, this will fail
                self._client.get_frame_count()
                return self._client
            except Exception:
                self._client = None

        # Find the bridge socket
        socket_path = self._find_socket()
        if socket_path is None:
            raise RuntimeError(
                "Emulator not connected. The DeSmuME bridge socket was not found. "
                "Call init_emulator and load_rom via the desmume MCP server first."
            )

        try:
            from desmume_mcp.client import EmulatorClient

            self._client = EmulatorClient(str(socket_path))
            # Verify the connection works
            self._client.get_frame_count()
            return self._client
        except Exception as e:
            self._client = None
            raise RuntimeError(
                f"Cannot connect to emulator bridge at {socket_path}: {e}"
            ) from e

    def reset(self) -> None:
        """Force reconnection on next call."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    @staticmethod
    def _find_socket() -> Path | None:
        """Search common locations for the bridge socket."""
        import os

        env_path = os.environ.get("DESMUME_BRIDGE_SOCK")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return p

        for rel in _SOCKET_SEARCH_PATHS:
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
