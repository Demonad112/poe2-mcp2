# PoE2 build analysis — session instructions

This repo is a PoE2 MCP server (`poe2-optimizer`, wired via `.mcp.json`). A typical session:
the user pastes a **Path of Building 2 export code** (or XML) plus a question. Do the work
without asking clarifying questions: import the build, pull whatever data the question needs,
answer directly.

## Workflow (no questions, no setup prompts)

1. **Save the pasted code to a file** (never pass long codes inline — they corrupt):
   `Write` it to `<scratchpad>/build.txt` exactly as pasted (whitespace is tolerated).
2. **Import it.**
   - MCP tools present (`mcp__poe2-optimizer__*`): call `import_pob` with `pob_file_path`.
   - Otherwise use the CLI fallback (identical code path, bootstraps its own venv):
     ```bash
     PY=$(bash scripts/cloud_setup.sh) && "$PY" scripts/pob_cli.py analyze <scratchpad>/build.txt
     ```
2b. **Always run the headless PoB calc** on the same file (`headless_pob_calc`, or CLI
   `tool headless_pob_calc '{"pob_file_path":"<scratchpad>/build.txt"}'`) when `headless_pob_status`
   reports `ready: true` (a SessionStart hook builds it in the background; if not ready yet, run
   `bash scripts/setup_headless_pob.sh`). Use its stats (DPS, EHP, res, Spirit) as the PoB-exact
   baseline for every answer; pass `fields` to keep output small. Skip it for questions that
   don't need numbers.
3. **Answer the question using the data tools**, not memory. Via MCP call the tool; via CLI:
   ```bash
   "$PY" scripts/pob_cli.py tool <tool_name> '<json args>'     # list names: ... tools
   ```
4. Reply with: conclusion first, then evidence (stat/gem/node/mod), then concrete changes.

## Tool map (what to use for what)

| Question type | Tools |
|---|---|
| Parse build (class, gems, gear, tree node IDs, stats) | `import_pob` |
| Is this support/spell combo legal, what does a gem do | `validate_support_combination`, `inspect_support_gem`, `inspect_spell_gem`, `list_all_supports`, `list_all_spells` |
| DPS math | `calculate_character_dps` (don't do the math in your head), `get_formula`, `explain_mechanic` |
| Defences / res / spirit sanity | `validate_build_constraints`, `reconcile_defensive_stats` |
| Passive tree | `analyze_passive_tree` (node IDs from the import), `inspect_passive_node`, `inspect_keystone`, `list_all_notables` |
| Gear / mods | `inspect_mod`, `search_mods_by_stat`, `get_mod_tiers`, `get_available_mods`, `validate_item_mods`, `inspect_base_item`, `find_stat_sources` |
| Compare to ladder | `compare_to_top_players` (needs network to poe.ninja) |
| Re-export | `export_pob` |
| PoB-exact calcs without desktop PoB (DPS, EHP, config what-ifs like enemy level/shock) | `headless_pob_status`, `headless_pob_calc` — needs `bash scripts/setup_headless_pob.sh` once (luajit + PoB2 checkout) |
| Verify a character against poe.ninja (damage, defences, overall; poe.ninja = truth) | `verify_character` (`char_model`/`char_model_path`, optional `ninja_url`) → `verify-report/v1` JSON then markdown diff, failures first; needs the headless engine. `reconcile_defensive_stats` routes to it when the charModel has `pathOfBuildingExport` |
| Price / upgrade lookup | `search_trade_items` — needs `POESESSID` env var + `www.pathofexile.com` allowed; on 401/403 it reports the auth failure (not "no items"). If unavailable, say "trade unavailable" — never invent prices |

`pob_*` tools (other than `import_pob`) need a live Path of Building desktop instance — not
available in cloud sessions; use `headless_pob_calc` instead when it reports `ready: true`.

## Rules

- Game data in `data/` is authoritative. If a tool disagrees with what you remember about PoE2,
  trust the tool and say so. If a tool lacks data, say "not in dataset" rather than guessing.
- Separate **facts from the build** (imported), **calculated** (tool output), and **opinion**.
- Imported stats come from PoB's `PlayerStat` entries — if missing (old/exported-without-calcs
  code), say so and work from gems/gear/tree instead of inventing numbers.
- Don't commit the user's build code or pasted data to the repo.

## Dev notes

- Python 3.9+; deps in `requirements.txt` (`mcp<2`). Install into the venv via
  `scripts/cloud_setup.sh` (system-Python install can fail on `ratelimit`).
- Tests: `"$(bash scripts/cloud_setup.sh)" -m pytest -m "not (network or pob_required or requires_game_data)"`
