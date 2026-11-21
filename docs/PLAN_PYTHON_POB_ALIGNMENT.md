# Plan: align Python calculators with headless PoB2

Source of truth: headless PoB2 engine (`src/pob/headless.py`, `pob_headless/bridge.lua`).
Evidence: `docs/AUDIT_PYTHON_VS_POB.md`. Differential harness: `scripts/audit_python_vs_headless.py`
(re-run after every fix; mismatches are flagged `<-- MISMATCH`).

## Status

| # | Item | File | Status |
|---|------|------|--------|
| 0 | Per-hand output for attack skills (`get_skill_table`) | `pob_headless/bridge.lua` | DONE (17ffdf1) |
| 1 | Evasion: use `calcs.monsterHitChance` (`1 - 0.95*ev/(ev+4*acc)`), inverse updated | `defense_calculator.py` | DONE (this PR) |
| 2 | Max-resistance cap per element (PoB `*ResistMax`, default 75, hard 90); EHP hard-wires 75 | `ehp_calculator.py` (`DefensiveStats`, `_calculate_resistance_dr`) | TODO |
| 3 | Enemy elemental penetration (config `enemy<Type>Pen`): `resMult = 1 - (res>0 and max(res-pen,0) or res)/100` | `ehp_calculator.py` | TODO |
| 4 | Negative enemy resistance must not be floored at 0 (clamp to [-200, 90]) | `spell_dps_calculator.py::_apply_resistances` | TODO |
| 5 | Crit chance: `(base+added)*(1+inc/100)*more`, not additive/capped at 100 | `damage_calculator.py`, `spell_dps_calculator.py`, `mcp_server.py::_handle_calculate_character_dps` | TODO |
| 6 | Crit multiplier ignores MORE modifiers (`extraDamage = base*inc*more`) | `spell_dps_calculator.py::_calculate_crit_multiplier` | TODO |
| 7 | Shock hard-coded 1.2x; speed rounding / server tick | `spell_dps_calculator.py`, `damage_calculator.py` | TODO (minor) |
| 8 | Structural: chained damage conversion, single inc/more pool | `damage_calculator.py`, `spell_dps_calculator.py` | TODO (large; prefer routing to headless) |

Items 1-5 each reproduce in `scripts/audit_python_vs_headless.py`; 6-8 come from reading the code/PoB source.

## Done in this PR beyond the audit
- Evasion rewritten to PoB's monster-hit formula; constants `EVASION_MAX_EVADE=0.95`, `EVASION_ACCURACY_FACTOR=4` (legacy 1.25/0.3 kept only as the player->monster formula, unused).
- Note: PoB rounds hit chance to an integer and returns 5 for `accuracy < 0`; Python does not round, and keeps "accuracy == 0 => 100% evade" (existing behaviour, not PoB).
- `tests/fixtures/poe_ninja/synthetic_lvl90.json` oracle values regenerated from the corrected calc (they were derived from the old formula, so that fixture is a regression guard only, not real ninja truth).

## Next-chat order of work
1. Item 2 (max res), then 3 (pen) — both in `ehp_calculator.py`; re-run the harness, expect Fire/Cold/Lightning max-hit rows to match.
2. Item 4 (negative resist), then 5 (crit scaling), then 6.
3. Add tests for each against PoB reference values printed by the harness (hard-code the numbers; tests must not need the engine).
4. Update the status table above and the mismatch table in `docs/AUDIT_PYTHON_VS_POB.md`.
5. Longer term: make `calculate_character_dps` / EHP defer to `headless_pob_calc` when the engine is ready; keep Python as offline fallback labelled "approximate".

## Prompt for the next chat (copy/paste)

```
Repo: Demonad112/poe2-mcp2, working dir /home/user/poe2-mcp2. Branch: continue on the existing PR branch
(claude/funny-meitner-h776y6, draft PR #15) unless it has merged; if merged, branch from latest main.

DO NOT use or run any MCP tools or the MCP server (mcp__poe2-optimizer__*) — they are NOT configured in this
chat. Use only Bash/Read/Edit and the repo's CLI/scripts.

Setup (no questions):
  PY=$(bash scripts/cloud_setup.sh)            # bootstraps the venv; use "$PY -I" for python
  bash scripts/setup_headless_pob.sh           # luajit + PoB2 checkout (needed for the harness)
  "$PY" -m pip install -q pytest               # if pytest is missing

Goal: finish aligning the Python calculators in src/calculator/ with the headless PoB2 engine (ground truth).
Read docs/PLAN_PYTHON_POB_ALIGNMENT.md (status table + order of work) and docs/AUDIT_PYTHON_VS_POB.md first.
Item 1 (evasion) is already done. Do items 2, 3, 4, 5, 6 in that order:
  2 per-element max resistance cap (DefensiveStats + ehp_calculator._calculate_resistance_dr)
  3 enemy elemental penetration in EHP
  4 stop flooring negative enemy resistance at 0 (clamp -200..90) in spell_dps_calculator._apply_resistances
  5 crit chance = (base+added)*(1+inc/100)*more (damage_calculator, spell_dps_calculator, mcp_server handler)
  6 crit multiplier MORE modifiers
PoB source for every formula is in ~/.cache/poe2-mcp/PathOfBuilding-PoE2/src (CalcDefence.lua, CalcOffence.lua,
Data/Misc.lua) — read it, don't guess. After each fix run:
  "$PY" -I scripts/audit_python_vs_headless.py     # the row for that item must lose its MISMATCH flag
  "$PY" -I -m pytest -q -m "not (network or pob_required or requires_game_data)" --continue-on-collection-errors
(many tests/test_*.py already fail to collect or fail without the MCP package/network — compare the FAILED list
against `git stash` baseline; only new failures matter). Add a pytest per fix with hard-coded PoB reference
values (tests must not need the engine). If an existing test or fixture encodes the old wrong formula, update it
and say so in the commit. Update the status table in the plan doc + mismatch table in the audit doc.
Commit per item, push to the branch, keep the PR draft, and summarize results (PoB vs Python before/after).
Do not do item 8 (structural) unless asked — propose routing to headless_pob_calc instead.
```
