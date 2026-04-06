#!/usr/bin/env bash
# Switch the active emulator backend between melonDS and DeSmuME.
# Usage: ./switch-emu.sh melonds|desmume
#
# Copies the matching .mcp.<backend>.json to .mcp.json.
# After switching, restart MCP servers in Claude Code with /mcp.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${1:-}"

if [[ "$BACKEND" != "melonds" && "$BACKEND" != "desmume" ]]; then
    echo "Usage: $0 melonds|desmume"
    echo ""
    echo "Current backend:"
    if [[ -f "$SCRIPT_DIR/.mcp.json" ]]; then
        if grep -q '"melonds"' "$SCRIPT_DIR/.mcp.json" 2>/dev/null; then
            echo "  melonds"
        elif grep -q '"desmume"' "$SCRIPT_DIR/.mcp.json" 2>/dev/null; then
            echo "  desmume"
        else
            echo "  unknown"
        fi
    else
        echo "  no .mcp.json found"
    fi
    exit 1
fi

SOURCE="$SCRIPT_DIR/.mcp.${BACKEND}.json"

if [[ ! -f "$SOURCE" ]]; then
    echo "Error: $SOURCE not found"
    exit 1
fi

cp "$SOURCE" "$SCRIPT_DIR/.mcp.json"
echo "Switched to $BACKEND backend."
echo "Restart MCP servers with /mcp in Claude Code."
