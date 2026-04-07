"""Tests for utility tools: reload_tools."""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from melonds_mcp.client import EmulatorClient


class TestReloadTools:
    """reload_tools meta-tool."""

    def test_reload_returns_success(self, emu: EmulatorClient):
        """reload_tools completes without error and reloads modules."""
        # Ensure at least one renegade_mcp module is loaded
        import renegade_mcp.party  # noqa: F401

        # Call the reload logic directly (same as the MCP tool body)
        prefix = "renegade_mcp."
        to_reload = [
            name
            for name in sorted(sys.modules)
            if name.startswith(prefix)
            and name not in ("renegade_mcp.server", "renegade_mcp.__main__")
        ]

        reloaded = []
        errors = []
        for name in to_reload:
            try:
                importlib.reload(sys.modules[name])
                reloaded.append(name.removeprefix(prefix))
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        assert len(reloaded) > 0, "Should have reloaded at least one module"
        assert len(errors) == 0, f"Reload errors: {errors}"
