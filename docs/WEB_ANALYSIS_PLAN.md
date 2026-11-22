# Web Character Analysis — Build Plan (no AI, no MCP, PoB2-exact)

Goal: a website feature where a user pastes a Path of Building 2 code and gets
**damage, EHP, gear breakdown, and ranked upgrade recommendations**, computed the
same way PoB2 computes them, without bloating the site.

---

## 1. The decision (read this first)

**Do not re-implement PoB's math. Run PoB2's own calculation engine, unmodified, in a
small calc service, and use PoB's own built-in "what-if" calculator for upgrades.**

| Option | Accuracy | Maintenance per game patch | Site bloat | Verdict |
|---|---|---|---|---|
| Port PoB calc math to JS/Python | Drifts right away. PoB's calc layer (`Modules/Calc*.lua`, `Data/`) is huge and changes every patch | Very high. You re-port each patch | Medium–high | ❌ |
| **PoB2 engine in a small calc service** (LuaJIT + pinned PoB2 checkout + `bridge.lua`) | **Identical to PoB** (it *is* PoB) | **Low.** Bump a commit pin, run regression | **~0 KB on the frontend.** Results are JSON | ✅ **Recommended** |
| PoB2 engine compiled to WASM in the browser | Identical | Medium (build toolchain, Lua 5.1 shims; LuaJIT itself can't target WASM) | ~50–70 MB download per user | Later/optional |
| MCP + LLM | Only as good as its tool calls | — | — | Not needed |

This repo already proves the recommended path: `pob_headless/bridge.lua` + `src/pob/headless.py`
run PoB2 headless and match poe.ninja (`verify_character`, `docs/verify/FIELD-MAP.md`).

**Measured in this repo** (Phase 0 spike, real level-90 endgame build, 16 socket groups, 15
items, ~120 allocated nodes):

| Operation | Time |
|---|---|
| Engine boot (once per worker) | 2.1 s |
| `load_xml` | 1.1 s |
| Full recalc (`set_config`) | ~265 ms |
| `get_skill_table` (recalcs every group) | ~4.0 s, so keep it off the hot path |
| **What-if via `GetMiscCalculator` (cached env)** | **~10 ms per candidate** (265 candidates in 2.6 s) |
| RSS per engine process | ~376 MB |

The what-if path is **~25× cheaper than a full recalc**. That gap is what makes background
upgrade search viable: a few hundred exact evaluations take seconds, not minutes.

---

## 2. How PoB itself finds upgrades (what we copy)

PoB has a "misc calculator" that re-runs the full calc with a temporary override and
returns the whole output table. The UI uses it for every comparison you see:

| PoB UI feature | Engine call (PoB2 source) |
|---|---|
| Item hover "+X DPS / +Y EHP if equipped" | `calcFunc({ repSlotName = slot, repItem = item })` (`Classes/ItemsTab.lua`) |
| Passive node hover "+X% if allocated" | `calcFunc({ addNodes = { [node] = true } })` (`Classes/PassiveTreeView.lua`) |
| "−X% if removed" | `calcFunc({ removeNodes = { [node] = true } })` |
| Rune/soul core compare | `calcFunc({ repSlotName = slot, repRune = rune })` |
| Flask/charm toggles | `calcFunc({ toggleFlask = item })` / `{ toggleCharm = item }` |
| Node power heat-map | `CalcsTabClass:PowerBuilder()` (loops `addNodes` over the tree) |

`calcFunc, calcBase = build.calcsTab:GetMiscCalculator()` (backed by
`calcs.getMiscCalculator` in `Modules/Calcs.lua`, which caches player/enemy DBs so repeated
calls are cheap).

**So the upgrade engine is: generate candidates → `calcFunc(override)` each → diff against
`calcBase` → rank.** No heuristics are needed for the numbers. Heuristics are only used
to pick *which* candidates to try.

---

## 3. Architecture

```
┌──────────── Browser (static site, GitHub Pages / any CDN) ─────────────┐
│ web/ (Svelte, already in repo)                                          │
│  Analyze route: paste code → POST /analyze → render JSON                │
│  No game data shipped except optional tree layout for display           │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ HTTPS JSON (request ~5–30 KB code, response ~20–80 KB)
┌───────────────▼──────────── Calc API (one small container) ─────────────┐
│ services/calc-api/  (Python, FastAPI or Starlette)                      │
│  • decode + validate code      • result cache (sha256(code+engine pin)) │
│  • engine pool (N LuaJIT procs, warm, reused)                           │
│  • analysis/  summary builders (damage, ehp, gear)                      │
│  • upgrades/  candidate generators + ranker (calls engine whatif)       │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ newline-delimited JSON over stdin/stdout (existing protocol)
┌───────────────▼──────────── Engine (unmodified PoB2 + bridge) ──────────┐
│ luajit pob_headless/bridge.lua   cwd = PathOfBuilding-PoE2/src @ pin    │
│  load_xml · get_stats · get_skill_table · set_config  (exist today)     │
│  get_items · get_tree · whatif · item_from_text       (add, §5)         │
└─────────────────────────────────────────────────────────────────────────┘
```

Why a separate service rather than in-site JS: the frontend stays a static bundle (a few
hundred KB), all heavy data stays server-side, and accuracy is PoB's by construction.

---

## 4. Repository layout (new and changed pieces)

```
poe2-mcp2/
├── pob_headless/
│   └── bridge.lua                 # EXTEND: get_items, get_tree, whatif, item_from_text
├── engine/
│   ├── Dockerfile                 # luajit + lua-utf8 + pruned PoB2 checkout at pinned commit
│   ├── prune_pob.sh               # drop TreeData/*/ images + old tree versions (see §8)
│   └── POB_COMMIT                 # single source of truth for the pin (replace POB_COMMIT_PIN)
├── services/calc-api/
│   ├── app.py                     # HTTP: POST /analyze, POST /upgrades, GET /health
│   ├── pool.py                    # wraps src/pob/headless.HeadlessPoB, N warm workers, recycle every K jobs
│   ├── cache.py                   # LRU in-proc (+ optional Redis/SQLite) keyed by sha256(xml)+pin
│   ├── schema.py                  # response models (versioned: analysis/v1, upgrades/v1)
│   ├── analysis/
│   │   ├── damage.py              # per-skill table, FullDPS, split, crit/speed/hit
│   │   ├── defence.py             # EHP, max-hit per type, res/overcap, layers, spirit
│   │   └── gear.py                # per-slot item + "contribution" (removal delta)
│   └── upgrades/
│       ├── weights.py             # pass 1: marginal stat weights (§6.2)
│       ├── passives.py            # frontier/respec candidates
│       ├── gear.py                # mod-swap + resist-fix + template rares
│       ├── gems.py                # legal support swaps, +level/quality
│       ├── constraints.py         # res cap, attribute reqs, spirit, chaos res
│       ├── rank.py                # objective, per-point/per-affix normalising, pareto
│       └── trade_query.py         # emits official trade search JSON (no prices)
├── data/candidates/               # GENERATED at build time from data/game (mod tiers by item class)
│   └── mod_pool_<pin>.json
├── tests/calc_api/
│   ├── golden/                    # anonymised codes + expected PoB outputs (NOT user pastes)
│   └── test_golden.py             # exact-match vs engine; vs poe.ninja via existing verify code
└── web/src/
    ├── routes/Analyze.svelte      # new route in the existing hash router (lib/stores.js)
    ├── components/analysis/
    │   ├── DamagePanel.svelte
    │   ├── DefencePanel.svelte
    │   ├── GearPanel.svelte
    │   └── UpgradeList.svelte
    └── lib/api.js                 # fetch wrapper, polls/streams /upgrades
```

**Reuse from this repo:** `src/pob/headless.py` (process mgmt, code decode),
`pob_headless/bridge.lua`, `src/calculator/reconcile_poe_ninja.py` + `DEFENCE_FIELD_SET`
(regression), `data/game/mods` and `data/game/base_items` (candidate generation),
`data/poe2_support_gems_database.json` + `src/optimizer/support_validation.py` (legal gem swaps).

**Not needed for the website:** `src/mcp_server.py`, `src/ai/`, the `pob_*` desktop client,
and the heuristic scorers in `src/optimizer/gear_optimizer.py` and `src/analyzer/*`.
Exact what-ifs replace them.

---

## 5. Engine API to add (bridge.lua)

The existing protocol is kept: one JSON object per line in, one per line out.

| Action | Params | Returns | Implementation |
|---|---|---|---|
| `get_items` | — | `[{slot, name, base, rarity, raw, mods:[{line, type:implicit/explicit/rune/desecrated}], requirements}]` | iterate `build.itemsTab.slots`, `item.raw` + parsed mod lines |
| `get_tree` | `{frontier_depth:int}` | `{allocated:[id], points_used, points_total, frontier:[{id, path:[id], cost}]}` | `build.spec.allocNodes`; frontier = unallocated nodes whose `path` length ≤ depth (same as PowerBuilder) |
| `item_from_text` | `{raw}` | `{ok, parsed}` | `new("Item", raw)`; validates candidate items before use |
| **`whatif`** | `{ fields:[...], use_full_dps:bool, overrides:[ {id, repSlotName?, repItemRaw?, addNodes?:[id], removeNodes?:[id], repRune?} ] }` | `{ base:{field:v}, results:[{id, stats:{field:v}}] }` | one `GetMiscCalculator()` call, then loop `calcFunc(o, use_full_dps)` per override, return `scalars(output, fields)` |
| `set_main_skill` | `{group, skill_part?}` | stats | sets `mainSocketGroup`, recalc |

Generalised from the spike handler. The slot-removal, `addNodes` and `removeNodes` paths ran
in the spike; the `repItemRaw` (candidate item) path is untested. It goes in `bridge.lua`
above `handlers.quit`:

```lua
handlers.whatif = function(p)
  require_build()
  local calcFunc, base = build.calcsTab:GetMiscCalculator()
  local nodes = build.spec.nodes
  local results = {}
  for _, o in ipairs(p.overrides or {}) do
    local ov = {}
    if o.repSlotName then
      ov.repSlotName = o.repSlotName
      ov.repItem = o.repItemRaw and new('Item', o.repItemRaw) or nil   -- nil = slot emptied
    end
    if o.addNodes then ov.addNodes = {}; for _, id in ipairs(o.addNodes) do ov.addNodes[nodes[id]] = true end end
    if o.removeNodes then ov.removeNodes = {}; for _, id in ipairs(o.removeNodes) do ov.removeNodes[nodes[id]] = true end end
    local ok, out = pcall(calcFunc, ov, p.use_full_dps)
    results[#results + 1] = ok and { id = o.id, stats = scalars(out, p.fields) } or { id = o.id, error = tostring(out) }
  end
  return { ok = true, base = scalars(base, p.fields), results = results }
end
```

`whatif` is batched on purpose: one round-trip evaluates hundreds of candidates against
the cached base environment, which is the same thing PoB does when it draws the power map.

Standard `fields` set (keep responses small):
`FullDPS, TotalDPS, CombinedDPS, TotalDotDPS, AverageHit, CritChance, CritMultiplier, Speed,
TotalEHP, Life, EnergyShield, Mana, Spirit, SpiritUnreserved(if present), Armour, Evasion,
EvadeChance, DeflectChance, FireResist, ColdResist, LightningResist, ChaosResist,
*ResistOverCap, PhysicalMaximumHitTaken, FireMaximumHitTaken, ColdMaximumHitTaken,
LightningMaximumHitTaken, ChaosMaximumHitTaken, Str, Dex, Int, ReqStr, ReqDex, ReqInt`.
Confirm each key against `Modules/CalcOffence.lua` / `CalcDefence.lua` at the pinned commit
(the repo already does this for defences in `docs/verify/FIELD-MAP.md`).

---

## 6. Analysis and upgrade pipeline

### 6.1 `/analyze` (synchronous, target < 2 s warm)

1. Decode code → XML (`decode_pob_code`), reject non-`<PathOfBuilding2>` roots.
2. Cache lookup by `sha256(xml) + POB_COMMIT`.
3. Engine: `load_xml` (~1.1 s) → `get_stats(fields)` → `get_items` → `get_tree`.
   Run `get_skill_table` (~4 s, one recalc per group) **asynchronously** and stream it in.
   Don't block the first paint on it.
   **DPS headline:** use `FullDPS` when > 0 (the skills the user ticked "include in Full DPS"),
   otherwise `CombinedDPS` of the main skill. The spike build reported `FullDPS = 0` because
   nothing was ticked.
4. **Gear contribution** (one `whatif` batch): for each slot, `{repSlotName: slot, repItem: nil}`.
   The delta shows what each item gives you (DPS%, EHP%, res points). This tells the user
   which slot is weakest, and it seeds the upgrade search.
5. Return `analysis/v1`:
   ```json
   { "engine": {"pob_commit":"…","tree":"0_5"},
     "character": {"class":"…","ascendancy":"…","level":92,"main_skill":"…"},
     "damage": {"full_dps":…, "skills":[{"name":…,"dps":…,"hit":…,"crit":…,"speed":…,"split":{…}}]},
     "defence": {"ehp":…, "max_hit":{"phys":…,"fire":…,…}, "res":{"fire":[75,12],…}, "life":…, "es":…, "spirit":{"total":…,"free":…}},
     "gear": [{"slot":"Body Armour","name":…,"mods":[…],"contribution":{"dps_pct":…,"ehp_pct":…}}],
     "flags": [{"severity":"high","code":"RES_UNCAPPED","detail":"Lightning 61/75"}] }
   ```

### 6.2 `/upgrades` (async job, stream results, target 5–20 s)

**Pass 1: marginal stat weights (~25 calcs).** Apply a synthetic test item per stat in the
weakest slot (or a "stat probe" override: +1 unit of a stat such as +10 life, +1% inc spell
damage, +5% fire res) and record ΔDPS and ΔEHP per unit. You get a per-build weight vector,
the same idea as PoB's stat-weight sort in trade, but computed exactly.

**Pass 2: candidate generation (cheap, uses weights to prune):**

| Category | Candidates | Pruning |
|---|---|---|
| Passives | frontier nodes at depth 1–3 (`get_tree`), plus allocated nodes for respec | rank by estimated value from stat lines × weights, keep top ~60 |
| Gear: mod swap | for each slot, replace the lowest-value explicit with the best *legal* tier (item class + ilvl from `data/game/mods`) of the top-weighted stats | top ~5 per slot |
| Gear: resist fix | if any res < cap: minimal mod changes that cap it while losing the least DPS | always evaluated when flagged |
| Gear: template rare | "realistic good rare" per slot (base + 4–6 tiered mods matching weights, T2–T3, not T1 fantasy) | 1–2 per slot |
| Gems | legal support swaps for the main skill (`support_validation`), +1 level / +quality | top ~10 |

**Pass 3: exact evaluation.** Send all surviving candidates in one `whatif` batch, split
across pool workers. Diff each against the base.

**Ranking (`rank.py`):**
- Objective = `w_d·ΔFullDPS% + w_e·ΔEHP% + w_m·Δmin(MaxHitTaken)%`. The user picks a preset:
  Balanced / Damage / Tanky.
- **Hard constraints** (reject or penalise): res below cap after the change, attribute
  requirements unmet (`Req*` > attributes), Spirit over-reserved, gem combo illegal.
- Normalise: passives **per point spent**, gear **per affix changed**, so a 3-point path
  doesn't beat a 1-point notable unfairly.
- Return the Pareto front plus a top-10 list with a plain-English reason built from the
  biggest stat delta ("+18% DPS: adds 32% increased Lightning Damage, which you scale ~2.1×
  more than Cast Speed").
- For gear, attach `trade_query` JSON (official trade site filter format) so the site can
  deep-link. **Never fabricate prices.** If you add prices later, fetch them live.

**Budget math (measured):** ~10 ms per what-if candidate on a real endgame build. 300
candidates = ~3 s on one worker, so a full upgrade pass (weights + passives + gear + gems)
fits in **5–10 s on a single worker** with no parallelism. Pass-1 pruning is what stops
gear combinatorics (thousands of mod/tier combos) from blowing the budget.

**Respec candidates come free:** the spike's `removeNodes` sweep over every allocated node
gives each node's exact value (e.g. a jewel socket worth −9.9% DPS, a defensive notable
worth −8.3% EHP). Nodes near 0% on both axes are the points to reallocate into the best
frontier nodes.

---

## 7. Website integration (keep it light)

- Add `Analyze` to the existing hash router (`web/src/lib/stores.js`). No new framework.
- `lib/api.js`: `POST /analyze`, then `POST /upgrades` → `{job_id}` → poll `GET /upgrades/{id}`
  every 1 s, or use SSE. Render partial results as they arrive.
- **Ship no PoB data to the browser.** Optional: reuse the existing `static/data/passive_tree.json`
  (already used by the seed calculator) to highlight recommended nodes.
- Show the engine stamp ("Calculated with Path of Building 2 @ `abc1234`, tree 0_5") on
  every result for trust and debugging.
- Keep the paste client-side until submit. Store no codes server-side beyond the result
  cache TTL (e.g. 24 h, keyed by hash).
- Bundle impact: four Svelte components plus a fetch wrapper, a few tens of KB.

---

## 8. Hosting and performance

| Item | Plan |
|---|---|
| Image | Debian-slim + LuaJIT (built at the pinned LuaJIT commit used by `scripts/setup_headless_pob.sh`) + lua-utf8 + PoB2 `src/` + `runtime/lua` |
| Prune | Keep `Data/`, `Modules/`, `Classes/`, `runtime/lua`, `TreeData/<latest>/tree.lua`. **Delete tree images.** They are 84 of the 88 MB in `TreeData/0_5`, and the full checkout is 413 MB. Target image < 150 MB |
| Memory | ~376 MB per engine process (measured). 1 GB box = 2 workers; 2 GB = 4 |
| Cold start | 2.1 s boot (measured). Keep min instances = 1, pre-warm the pool at startup |
| Recycling | Restart a worker every ~200 jobs or on error, so state leaks can't accumulate |
| Concurrency | One build per worker at a time (engine is single-threaded and stateful). Queue the rest |
| Hosts | Fly.io / Cloud Run / Render / any VPS. The frontend stays on GitHub Pages |
| Abuse | Rate-limit per IP, cap code size (~200 KB), job timeout 30 s, kill the worker on timeout |

---

## 9. Accuracy and staying current (the part that matters most)

1. **Single pin**: `engine/POB_COMMIT`. `src/pob/headless.py` and the Dockerfile both read it.
2. **Golden tests** (`tests/calc_api/golden/`): 10–20 anonymised builds across archetypes
   (attack/spell/minion/DoT, life/ES/hybrid). Assert engine output == stored expected values,
   which catches bridge regressions.
3. **Truth check**: run the existing `verify_character` against poe.ninja charModels for the
   same builds (poe.ninja runs PoB too). This catches pin drift versus the live game.
4. **Weekly bump job (GitHub Actions)**: fetch the latest PoB2 commit → build image → run golden +
   verify → open a PR with the diff report. Merge = deploy. Failures don't deploy (fail closed).
5. The **upgrade candidates** come from `data/game` mod tiers. Regenerate
   `data/candidates/mod_pool_<pin>.json` in the same job so mod legality tracks the patch.
6. Return `engine.pob_commit` in every response, and include it in the cache key.

---

## 10. Phased delivery

| Phase | Deliverable | Done when |
|---|---|---|
| **0. Spike** ✅ *partly done* | Prototype `whatif` (slot removal, node removal, frontier add) ran on one real build: 265 candidates, ~10 ms each, sane deltas | Still to do: productionise the handler in `bridge.lua`; benchmark 4 more codes; check item-swap deltas against PoB desktop hovers for 3 items |
| **1. Calc API** | `services/calc-api` with `/analyze`, pool, cache, Dockerfile, pruned image | Golden tests green; p50 `/analyze` < 1.5 s warm |
| **2. Website** | `Analyze` route with Damage / Defence / Gear panels | Paste → panels render; engine stamp shown |
| **3. Upgrades v1** | passives (frontier + per-point), resist-fix, gear contribution | Top-10 list with exact deltas; constraints enforced |
| **4. Upgrades v2** | stat weights, mod-swap + template rares, gem swaps, trade deep-links | Recommendations beat a hand-picked baseline on golden builds |
| **5. Ops** | weekly PoB bump PR, verify-vs-ninja report, rate limits, metrics | Patch day = merge one PR |
| *6. Optional* | WASM engine for fully client-side analysis | Only if hosting cost or latency demands it |

---

## 11. Failure points and mitigations

| Risk | Mitigation |
|---|---|
| PoB internals (`GetMiscCalculator`, override keys) change upstream | Pin the commit; golden tests exercise `whatif`; the bump PR shows breakage before deploy |
| Wrong config assumptions (enemy level, boss, conditions) skew numbers | Default to the build's own `<Config>`; expose 3–4 presets (map boss / pinnacle / clear) via existing `set_config` |
| Candidate items that can't exist (illegal mod/tier/base combos) | Generate only from `data/game/mods` by item class + ilvl; validate via `item_from_text` |
| Combinatorial blow-up | Pass-1 weights prune before exact calc; hard caps per category |
| "Upgrade" that breaks attributes or res | Hard constraints in `rank.py`; resist-fix always runs first |
| Memory creep in long-lived Lua procs | Worker recycling every K jobs |
| PoE1 or old codes | Already rejected by `load_xml` (root and `targetVersion` checks) |
| Licensing | PoB2 is MIT. Ship its LICENSE in the image and credit it in the UI footer |
