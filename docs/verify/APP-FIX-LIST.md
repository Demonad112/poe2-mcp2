# App fix list (Batch 3): site vs poe.ninja / MCP, Yykiuy

Baseline: poe.ninja charModel fixture (truth) and `verify_character` (79/105 pass; defence + overall all pass).
App values from `upgraded-disco-companion/docs/verify/SITE-VS-MCP.md` (captured 2026-11-09). Scope: damage, defences, overall. No trade.
Tolerances: integers exact; DPS/EHP within 1%.

## Fix these (app is wrong)

| # | Field | App value | ninja / MCP value | Likely app-side cause | Fix |
|---|---|---|---|---|---|
| 1 | Damage split, Falling Thunder (and any skill) | fire 47%, lightning 8% | lightning 47%, fire 8% (ninja `damageTypes` [12,47,33,8,0]) | `damageTypes` index order mapped wrong: ninja order is [physical, lightning, cold, fire, chaos]; app swaps lightning and fire | Map by that order; add a test with this fixture (Falling Thunder: lightning 47, fire 8) |
| 2 | Tree: 3 unresolved node ids 15343, 49356, 60239 | "not found in tree data", no keystones resolved | all 3 are allocated on the character | Shipped tree data (PassiveTree-0.5) is older than the character's tree version | Update tree data to the current version, or fall back to ninja/PoB node data; re-check keystones afterwards (currently "none resolved", almost certainly wrong) |

## Verified OK (app matches ninja)

Life 1,477 · ES 2,922 · evasion 8,704 · armour 0 · spirit 147 · EHP 18,456 · max hits 4,399 / 9,477 / 15,169 / 15,711 / 19,126 (phys/chaos/lightning/fire/cold) · resists 75/80/74/69 with overcap 5/59/0/0 · Falling Thunder DPS 233,295, crit 64.56% / 4.4x, rate 1.5912.

## Within tolerance, just stale

| Field | App | ninja | Note |
|---|---|---|---|
| Storm Wave DPS | 148,262 | 148,009 | +0.17%, inside 1%. Capture-time drift; ignore |

## Not comparable (don't treat as app bugs)

- Per-skill DPS in the MCP is +7.7% to +12.9% over ninja for the spell/trigger-path skills and Whirling Assault is off; see FIELD-MAP.md. The app's figures come from ninja, so the app is correct here and the MCP's PoB is the outlier.
- Gear, findings, tier targets and passive-tree summary rows have no ninja/PoB oracle in `verify_character`; they need the chat-based comparison in SITE-VS-MCP.md and are out of this list.

## Batch 4 oracle

Use `verify-report/v1` JSON from `verify_character` on `tests/fixtures/ninja_yykiuy_charmodel.json`: after fix 1 the app's split for every skill should equal ninja's `damageTypes` after remapping.
