"""CLI entry point: python -m renegade_mcp"""

from __future__ import annotations

import sys


def main() -> None:
    # MCP stdio transport uses stdout for JSON-RPC.
    # Redirect stdout to stderr during setup to prevent corruption.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        from renegade_mcp.server import create_server

        server = create_server()
    finally:
        sys.stdout = real_stdout

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
