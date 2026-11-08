#!/usr/bin/env bash
# Idempotent setup of the headless PoB2 calc engine (real PoB calculations, no desktop app).
# Installs luajit + a native lua-utf8 module and clones PathOfBuilding-PoE2 (MIT) into
# $POE2_POB_HOME (default ~/.cache/poe2-mcp/pob2). Prints the PoB2 `src` dir on stdout.
set -euo pipefail
HOME_DIR="${POE2_POB_HOME:-$HOME/.cache/poe2-mcp}"
SRC="$HOME_DIR/PathOfBuilding-PoE2"
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
if [ ! -d "$SRC/src" ]; then
  git clone --depth 1 https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 "$SRC" >&2
fi
if [ ! -f "$LR/lib/lua/5.1/lua-utf8.so" ]; then
  command -v luarocks >/dev/null 2>&1 || { echo "luarocks missing" >&2; exit 1; }
  luarocks --lua-version=5.1 --tree="$LR" install luautf8 >&2
fi
echo "$SRC/src"
