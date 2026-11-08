# Headless PoB2 engine: build it locally (copy/paste prompt)

`scripts/setup_headless_pob.sh` does this automatically. Use the prompt below if you want an
agent (or yourself) to do it by hand, e.g. on Windows/macOS or when the script can't run.

**Why a custom LuaJIT:** PoB2's source uses `x += 1`. Stock LuaJIT (Ubuntu `apt install luajit`)
can't parse it, so PoB2 dies at `Modules/Main.lua:340: '=' expected near '+'`. PoB2's own
Dockerfile builds LuaJIT at commit `2460b3ff93a1c955de3d62cfc825de7d68dc272e`, which works.

## Prompt

> Set up the headless Path of Building 2 engine for the poe2-mcp2 repo, PoE2 only.
> 1. Build LuaJIT at commit 2460b3ff93a1c955de3d62cfc825de7d68dc272e from https://github.com/LuaJIT/LuaJIT
>    (`git clone`, `git checkout <commit>`, `make`). Confirm `src/luajit -e "local c=1 c+=1"` exits 0.
> 2. Clone https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 (depth 1).
> 3. Build the native `lua-utf8` module for Lua 5.1: `luarocks --lua-version=5.1 --tree=<dir> install luautf8`.
> 4. Export `POE2_LUAJIT=<path to that luajit>`, `POE2_POB_SRC=<PoB2 clone>/src`, and make `lua-utf8.so`
>    resolvable (`~/.cache/poe2-mcp/lua_modules/lib/lua/5.1/` is what the client expects by default).
> 5. In the poe2-mcp2 repo run `python scripts/pob_cli.py tool headless_pob_status '{}'` and require
>    `"ready": true`, then `python -m pytest tests/test_headless_pob.py` and require it to pass.
> Only PoE2 builds (`<PathOfBuilding2>` root, `targetVersion="0_1"`) are valid; PoE1 exports are rejected.
