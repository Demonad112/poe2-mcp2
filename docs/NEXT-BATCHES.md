# Next batches: poe2-mcp verifier

When the user says **"next batch"**, take the first batch below whose status is `[ ]`. Run it as written (on Sonnet if
possible). When its gate passes and the user has seen the result, change its status to `[x]`. Scope for every batch:
damage, health/defences and overall stats only. **No trade.**

Spec: `C:\Users\Addy7\.claude\plans\currently-my-goal-for-breezy-taco.md`

---

## [ ] Batch 1: finish and check the verifier

```
Workspace: C:\Dev\projects\POE 2 MCP (poe2-mcp2 is a nested repo). Spec: C:\Users\Addy7\.claude\plans\currently-my-goal-for-breezy-taco.md. Scope is damage, health/defences and overall stats only. NO trade: skip every trade item, including any parked trade note.

A previous session started this plan and was stopped mid-way. First run `git -C poe2-mcp2 status --short` and check docs/verify and docs/later to see what exists. Then finish only what's missing:
- tests/fixtures/ninja_yykiuy_charmodel.json (trimmed public data)
- bridge.lua get_skill_table, plus the field-set constant in src/pob/headless.py
- reconcile_with_ninja in src/calculator/reconcile_poe_ninja.py: integers exact; DPS, EHP and max hits within 1%; a likely cause on each failure
- verify_character MCP tool: verify-report/v1 JSON first, then a markdown diff with failures first. reconcile_defensive_stats uses the exact path.
- docs/verify/FIELD-MAP.md, docs/verify/SITE-VS-MCP-local.md, docs/later/app-analysis-notes.md, and a verify_character row in poe2-mcp2/CLAUDE.md
- tests: test_reconcile_ninja.py (pure) and test_headless_skill_table.py (pob_required)

Gate: .venv\Scripts\python.exe -m pytest poe2-mcp2/tests -q -m "not network", plus the pob_required test once.
Smoke-run verify_character on https://poe.ninja/poe2/profile/Demonad112-2589/character/Yykiuy and give a pass/fail table. Do not tune values to force a match.
Never read poe2-mcp2/.env. No commits or pushes without asking. No subagents. Keep replies concise.
```

Ninja raw data, if still present: `C:\Users\Addy7\AppData\Local\Temp\claude\85ae98e42ad53793\1d9543af-263e-40a4-8b8e-a19e3220386f\scratchpad\yykiuy.json`
(re-fetch with `PoeNinjaAPI._fetch_char_model("Demonad112-2589","forbiddenrites","Yykiuy")` if it is gone).

## [ ] Batch 2: fix the MCP where it differs from poe.ninja

```
Workspace: C:\Dev\projects\POE 2 MCP. Run verify_character on Yykiuy (poe.ninja is the truth). For each failed row, sort it into one of three causes:
(a) PoB config differs from ninja (enemy level, charges, conditions, buffs)
(b) mapping error (wrong PoB key, wrong ninja field, unit or percent mismatch)
(c) engine drift (PoB commit bb52d6b vs ninja's version)
Fix (a) and (b) in the MCP: set config from ninja's data, correct FIELD-MAP.md, add a regression test for each fix. Document (c) only. Rerun until only (c) rows remain, and report the final table.
Damage, health and overall only, NO trade. Never read .env. No commits without asking.
```

## [ ] Batch 3: run the site-vs-MCP check and write the app fix list

```
Workspace: C:\Dev\projects\POE 2 MCP. Follow docs/verify/SITE-VS-MCP-local.md: compare the app's values for Yykiuy (from the SITE-VS-MCP.md doc in upgraded-disco-companion) against verify_character output, field by field, using FIELD-MAP.md. Fill in the FIELD-MAP "app field" column. Write docs/verify/APP-FIX-LIST.md with field, app value, MCP/ninja value, and the likely app-side cause. Include the damage-split order bug and the 3 unresolved tree nodes (15343, 49356, 60239) from docs/later/app-analysis-notes.md.
Don't edit the app here; that is a separate session in the app repo. Damage, health and overall only, NO trade. No commits without asking.
```

## [ ] Batch 4: app fixes (in the app repo, not here)

Make the fixes from `docs/verify/APP-FIX-LIST.md` in the app repo, with the `verify-report/v1` JSON as its test
oracle. Start that session in the app's folder. Ask before any commit in either repo.
