#!/usr/bin/env bash
# SessionStart hook: prebuild the venv and headless PoB2 engine in the background
# so MCP startup and headless_pob_calc don't pay the build cost. Idempotent, never fails the session.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${TMPDIR:-/tmp}/poe2-session-start.log"
(
  bash "$ROOT/scripts/cloud_setup.sh" >/dev/null
  bash "$ROOT/scripts/setup_headless_pob.sh" >/dev/null
) >"$LOG" 2>&1 &
exit 0
