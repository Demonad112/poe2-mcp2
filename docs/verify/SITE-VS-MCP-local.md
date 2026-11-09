# Site vs local MCP verification (Batch 1)

- **Site (poe.ninja)**: pre-computed charModel (`defensiveStats`, `skills[].dps[]`, `pathOfBuildingExport`). Treated as truth.
- **Local MCP**: `verify_character` loads the charModel's PoB export into the headless PoB2 engine, reads stats and a per-skill table, and diffs. Output: JSON (`verify-report/v1`) then markdown with failures first.
- Run: `verify_character {"char_model_path": "tests/fixtures/ninja_yykiuy_charmodel.json", "ninja_url": "https://poe.ninja/poe2/profile/Demonad112-2589/character/Yykiuy"}`.
- Needs the engine (`bash scripts/setup_headless_pob.sh`; on Windows see the workspace `docs/windows-local-setup.md` and set `POE2_LUAJIT`). Cloud/Linux was built and run at PoB `bb52d6b`.
- Scope: damage, defences, overall only. No trade.
- Known gap: damage rows (see FIELD-MAP.md status). Not tuned.
