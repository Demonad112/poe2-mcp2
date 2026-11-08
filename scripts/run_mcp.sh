#!/usr/bin/env bash
# Launch the PoE2 MCP server over stdio (self-bootstrapping). Used by .mcp.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$("$ROOT/scripts/cloud_setup.sh")"
cd "$ROOT"
exec "$PY" -m src.mcp_server
