# PoE2 MCP Server - Setup Guide (fork: Demonad112/poe2-mcp2)

> **Community Project**: Independent, fan-made. Not affiliated with or endorsed by Grinding Gear Games.

This fork adds a self-bootstrapping launcher (`scripts/run_mcp.sh`), a headless Path of Building 2
calc engine (no desktop PoB needed), and a Claude Code cloud flow. Pick one of the three setups below.

## 1. Claude Code cloud sessions (recommended)

Nothing to install by hand. The repo ships:

- `.mcp.json` - registers `poe2-optimizer` via `bash scripts/run_mcp.sh`.
- `.claude/settings.json` - `SessionStart` hook that runs `scripts/session_start.sh`, which builds the
  venv and headless PoB in the background (idempotent, never fails the session).
- `CLAUDE.md` - the build-analysis workflow (save pasted PoB code to a file, `import_pob`, `headless_pob_calc`).

### Recommended: environment setup script

In the Claude Code environment settings, set the **setup script** so the build happens once at
container build time rather than at first session:

```bash
cd poe2-mcp2 && bash scripts/cloud_setup.sh && bash scripts/setup_headless_pob.sh
```

What it creates:

| Path | Purpose |
|---|---|
| `~/.poe2venv` (+ `.req-stamp`) | Python venv with `requirements.txt`; stamp triggers rebuild when requirements change |
| `~/.cache/poe2-mcp/LuaJIT` | LuaJIT build used by the calc bridge |
| `~/.cache/poe2-mcp/PathOfBuilding-PoE2` | PoB2 checkout (headless engine source) |
| `~/.cache/poe2-mcp/lua_modules` | `lua-utf8` etc. |
| `data/poe2_optimizer.db` | SQLite DB, created lazily on first server start (`create_all`); git-ignored, not built by a script |

If the setup script is absent, the SessionStart hook performs the same build in the background
(log: `${TMPDIR:-/tmp}/poe2-session-start.log`). Allow a minute or two on a cold container.

### Network

Allow outbound `github.com` (PoB2 checkout), `www.pathofexile.com` (trade), `poe.ninja` (ladder
comparison). Package registries are reachable by default.

### Environment variable: `POESESSID`

Only needed for `search_trade_items`. Add it in the **Claude Code environment settings**
(environment variables) - never in chat, never committed.

1. Log in at pathofexile.com, DevTools > Application > Cookies > `POESESSID`.
2. Copy the 32-character value into the environment variable `POESESSID`.
3. Start a new session. `health_check` then reports the trade API as configured.

Without it, trade tools report an auth failure (not "no items"); every other tool works.

### Verify

- `health_check` - database connected, handlers present (a warning about an empty `items` table is expected).
- `headless_pob_status` - must return `"ready": true`.
- `headless_pob_calc` with `{"pob_file_path": "<file with PoB code>"}` - PoB-exact DPS/EHP/res/Spirit.

## 2. Local install + Claude Desktop

```bash
git clone https://github.com/Demonad112/poe2-mcp2.git
cd poe2-mcp2
bash scripts/cloud_setup.sh          # prints the venv python path; creates ~/.poe2venv
bash scripts/setup_headless_pob.sh   # optional: headless PoB2 (needs git, make, a C compiler, luarocks or equivalent)
```

`scripts/run_mcp.sh` bootstraps the venv and then runs `python -m src.mcp_server` over stdio.

Edit the Claude Desktop config:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json` (use Git Bash/WSL for the `bash` command)
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux / WSL**: wherever your client reads it

```json
{
  "mcpServers": {
    "poe2-optimizer": {
      "command": "bash",
      "args": ["/absolute/path/to/poe2-mcp2/scripts/run_mcp.sh"],
      "env": {
        "POESESSID": "optional-32-char-cookie-for-trade-search"
      }
    }
  }
}
```

Use an absolute path. Omit the `env` block if you don't need trade search. Restart Claude Desktop afterwards.

## 3. .mcpb bundle

Build with `python scripts/build_mcpb_bundle.py`, then in Claude Desktop: Settings > Extensions > Install
Extension and select the `.mcpb`. `mcpb_bundle/manifest.json` lists all 48 tools. The bundle excludes the
SQLite DB (created on first run) and raw extracted game files. Headless PoB is not bundled; run
`scripts/setup_headless_pob.sh` from a source checkout if you need it.

## Tools (48)

| Category | Tools |
|---|---|
| Character analysis | `analyze_character`, `compare_to_top_players`, `import_poe_ninja_url`, `analyze_passive_tree`, `get_live_game_state` |
| Validation | `validate_support_combination`, `validate_build_constraints`, `validate_item_mods`, `reconcile_defensive_stats` |
| Gem data | `inspect_support_gem`, `inspect_spell_gem`, `list_all_supports`, `list_all_spells` |
| Passive tree | `list_all_keystones`, `inspect_keystone`, `list_all_notables`, `inspect_passive_node`, `check_tree_freshness` |
| Base items | `list_all_base_items`, `inspect_base_item` |
| Item mods | `inspect_mod`, `list_all_mods`, `search_mods_by_stat`, `get_mod_tiers`, `get_available_mods`, `find_stat_sources` |
| Calculation | `calculate_character_dps`, `headless_pob_status`, `headless_pob_calc` |
| Path of Building (file/code) | `import_pob`, `export_pob`, `get_pob_code` |
| Path of Building (live desktop; not in cloud) | `pob_status`, `pob_load_build`, `pob_get_build`, `pob_get_calcs`, `pob_get_passive_tree`, `pob_install_addon` |
| Trade | `search_items`, `search_trade_items`, `setup_trade_auth` |
| Knowledge | `explain_mechanic`, `get_formula`, `get_game_config` |
| Utility | `health_check`, `clear_cache`, `check_for_updates`, `report_error` |

## Environment variables (`.env`)

Copy `.env.example` to `.env`. All optional. `SECRET_KEY` / `ENCRYPTION_KEY` are generated per process
when unset; to persist, generate your own:

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32)); print('ENCRYPTION_KEY=' + secrets.token_hex(32))"
```

```bash
POESESSID=            # trade search; in cloud sessions set it in environment settings instead
DATABASE_URL=sqlite:///data/poe2_optimizer.db
LOG_LEVEL=INFO
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server fails / `CONNECT_TIMEOUT` on first launch in a cold container | First launch builds the venv. Run `bash scripts/cloud_setup.sh` once (or use the environment setup script), then reconnect |
| `headless_pob_status` `ready: false` | `bash scripts/setup_headless_pob.sh` (needs `github.com` reachable) |
| Trade search returns an auth error | `POESESSID` missing/expired (should be 32 chars); re-copy the cookie |
| `health_check`: Items table empty | Expected; item data is served from `data/*.json`. Optional: `python scripts/populate_database.py` |
| Tools return empty results | Confirm `data/` has the JSON files; try `clear_cache` |
| `bash` not found on Windows | Install Git for Windows or use WSL, or run `python -m src.mcp_server` from the venv directly |

## Updating

```bash
git pull origin main
bash scripts/cloud_setup.sh    # re-syncs the venv when requirements change (stamp-based)
```

## Requirements

- Python 3.9+
- ~100 MB disk for the repo and data, plus the venv and headless PoB cache (~hundreds of MB)
- Internet for poe.ninja / pathofexile.com features
