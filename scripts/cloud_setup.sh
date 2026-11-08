#!/usr/bin/env bash
# Idempotent bootstrap for fresh cloud/CI sessions: private venv + deps.
# A venv is used because system-Python installs can fail (e.g. the `ratelimit`
# sdist breaks against Debian's patched setuptools).
# Prints the venv python path on stdout; all other output goes to stderr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${POE2_VENV:-$HOME/.poe2venv}"
STAMP="$VENV/.req-stamp"
WANT="$(sha256sum "$ROOT/requirements.txt" | cut -d' ' -f1)"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" >&2
fi
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  "$VENV/bin/pip" install -q -r "$ROOT/requirements.txt" >&2
  echo "$WANT" > "$STAMP"
fi
echo "$VENV/bin/python"
