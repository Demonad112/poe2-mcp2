#!/usr/bin/env bash
# Idempotent setup of the headless PoB2 calc engine (real PoB calculations, no desktop app).
# Installs luajit + a native lua-utf8 module and clones PathOfBuilding-PoE2 (MIT) into
# $POE2_POB_HOME (default ~/.cache/poe2-mcp/pob2). Prints the PoB2 `src` dir on stdout.
set -euo pipefail
HOME_DIR="${POE2_POB_HOME:-$HOME/.cache/poe2-mcp}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Prefer an existing PoB2 checkout (POE2_POB_SRC, else sibling ../PathOfBuilding-PoE2) so we track
# the user's fork instead of cloning upstream; fall back to the cache clone.
if [ -n "${POE2_POB_SRC:-}" ]; then SRC="$(dirname "$POE2_POB_SRC")"
elif [ -f "$ROOT/../PathOfBuilding-PoE2/src/HeadlessWrapper.lua" ]; then SRC="$(cd "$ROOT/../PathOfBuilding-PoE2" && pwd)"
else SRC="$HOME_DIR/PathOfBuilding-PoE2"; fi
LR="$HOME_DIR/lua_modules"
mkdir -p "$HOME_DIR"

if ! command -v luajit >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  { $SUDO apt-get update -qq && $SUDO apt-get install -y -qq luajit libluajit-5.1-dev luarocks gcc make; } >&2
fi
# PoB2 source uses `x += 1`, which stock LuaJIT (e.g. Ubuntu apt) can't parse. Build the commit
# PoB2's own Dockerfile pins and use it.
LJ_COMMIT=2460b3ff93a1c955de3d62cfc825de7d68dc272e
LJ="$HOME_DIR/LuaJIT"
if [ ! -x "$LJ/src/luajit" ]; then
  command -v make >/dev/null 2>&1 || { echo "make/gcc required to build LuaJIT" >&2; exit 1; }
  git clone -q https://github.com/LuaJIT/LuaJIT "$LJ" >&2
  git -C "$LJ" checkout -q "$LJ_COMMIT" >&2
  make -C "$LJ" -j"$(nproc)" >&2
fi
# Pin: must match POB_COMMIT_PIN_FULL in src/pob/headless.py (goldens are recorded against it).
POB_PIN="$(sed -n 's/^POB_COMMIT_PIN_FULL = "\([0-9a-f]\{40\}\)".*/\1/p' "$ROOT/src/pob/headless.py")"
if [ ! -d "$SRC/src" ]; then
  # Remove a half-finished clone from an interrupted earlier run (dir exists but has no src/).
  [ -d "$SRC" ] && [ -z "$(ls -A "$SRC/src" 2>/dev/null)" ] && [ ! -f "$SRC/.git/HEAD" ] && rm -rf "$SRC"
  mkdir -p "$SRC"
  git -C "$SRC" init -q >&2
  git -C "$SRC" remote add origin https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 >&2
  git -C "$SRC" fetch -q --depth 1 origin "$POB_PIN" >&2
  git -C "$SRC" checkout -q FETCH_HEAD >&2
elif [ -n "$POB_PIN" ] && [ -d "$SRC/.git" ] && [ "$(git -C "$SRC" rev-parse HEAD)" != "$POB_PIN" ] \
     && [ -z "${POE2_POB_SRC:-}" ] && [ "$SRC" = "$HOME_DIR/PathOfBuilding-PoE2" ]; then
  # Managed cache clone drifted from the pin: move it back (user-supplied checkouts are left alone).
  git -C "$SRC" fetch -q --depth 1 origin "$POB_PIN" >&2 && git -C "$SRC" checkout -q FETCH_HEAD >&2 \
    || echo "WARNING: could not move $SRC to pin $POB_PIN" >&2
fi
if [ -d "$SRC/.git" ] && [ -n "$POB_PIN" ] && [ "$(git -C "$SRC" rev-parse HEAD)" != "$POB_PIN" ]; then
  echo "WARNING: PoB2 checkout is $(git -C "$SRC" rev-parse --short HEAD), pin is ${POB_PIN:0:7}; goldens may differ" >&2
fi
if [ ! -f "$LR/lib/lua/5.1/lua-utf8.so" ]; then
  command -v luarocks >/dev/null 2>&1 || { echo "luarocks missing" >&2; exit 1; }
  luarocks --lua-version=5.1 --tree="$LR" install luautf8 >&2
fi
echo "$SRC/src"
