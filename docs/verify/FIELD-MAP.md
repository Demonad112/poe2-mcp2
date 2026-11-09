# verify_character field map (poe.ninja → PoB2 headless)

Source of truth for keys: `DEFENCE_FIELD_SET` in `src/pob/headless.py`; skill rows from `get_skill_table` in `pob_headless/bridge.lua`. Engine pin: PoB2 `bb52d6b`. poe.ninja values are truth; nothing here is tuned to force a match.

| Group | ninja key | PoB output key | Compare |
|---|---|---|---|
| overall | life / energyShield / mana / spirit | Life / EnergyShield / Mana / Spirit | exact int |
| overall | strength / dexterity / intelligence | Str / Dex / Int | exact int |
| overall | movementSpeed | EffectiveMovementSpeedMod | floor of ×100 (PoB 1.348 = ninja 134) |
| defence | evasionRating / armour | Evasion / Armour | exact int |
| defence | evadeChance / deflectChance | EvadeChance / DeflectChance | exact int |
| defence | 4 resistances + OverCap | per-element Resist / ResistOverCap | exact int |
| defence | charge counts (3) | max charges | exact int |
| defence | effectiveHealthPool | TotalEHP | ±1% |
| defence | 5× `*MaximumHitTaken` | per-type max hit | ±1% |
| damage | skills[].dps[].dps | TotalDPS | ±1% |
| damage | dotDps | TotalDotDPS | ±1% |
| damage | rate / critChance / critMultiplier | Speed / CritChance / CritMultiplier | ±1% |
| damage | damageTypes[] (split %) | Σ`<Type>StoredCombinedAvg` share | ±1 percentage point |

Skill match is by skill name against enabled PoB socket groups; a missing name is a failure ("skill not found").

## Report (`verify-report/v1`)
`source`, `overall`, `defence`, `skills[]` (ninja vs mcp), `diffs[]` (field, group, ninja, mcp, tolerance, delta_pct, pass, cause; failures first), `summary{total,passed,failed}`.

## Status on fixture (Yykiuy, L88)
73/105 pass. All defence/overall rows pass. All 32 failures are damage rows — triage in Batch 2 as (a) config difference, (b) mapping error, (c) engine drift. PoB key names were confirmed only by the fixture run matching; re-verify against PoB source if a row is unexpectedly zero.

## Batch 2 findings (Yykiuy, PoB bb52d6b) — 79/105 pass, 26 fail (all per-skill damage; all overall/defence rows pass)

| Row group | Cause class | Status |
|---|---|---|
| `split.*` for skills where PoB sets `<Type>HitAverage` (Hollow Focus, Frozen Locus) | (b) mapping: was crit-weighted `StoredCombinedAvg`, ninja is post-mitigation `HitAverage` | **Fixed**, regression test added; now exact |
| `split.*` for spell/trigger-path skills (Tempest Bell, Falling Thunder, Storm Wave, Hollow Resonance, Staggering Palm, Whirling Assault) | (b) basis: PoB leaves `HitAverage` 0, only pre-mitigation `StoredCombinedAvg` exists. Report flags the basis. | Open: needs a post-mitigation per-type source (derive from enemy res/armour or read a different PoB key) |
| `dps` +7.7% to +12.9% (Falling Thunder, Hollow Resonance, Staggering Palm, Storm Wave, Tempest Bell) | unclassified (a) config vs (c) drift. Crit chance/multi and rate rows pass, so hit inputs match; the gap is in mitigation/enemy config. Hollow Focus and Frozen Locus DPS match exactly. | Open: next step is diffing enemy config (level, resists, boss flags) in ninja's export vs headless |
| `Whirling Assault` dps -26%, dot -55% | unclassified: ninja is higher, opposite direction to the rest; likely skill part/stage or condition config | Open |

### Batch 2, config diagnosis (what-if via `verify_character` `config`)

- The export's own Config has enemy level 82, 50% ele res (placeholders = PoB defaults), pinnacle default; no explicit enemy overrides. `enemyIsBoss` Boss/Uber/None are all further off than the default.
- Setting ele res to 60 makes Tempest Bell, Storm Wave, Hollow Resonance, Staggering Palm match ninja to 1.000 (Falling Thunder -4.5%), **but** breaks Hollow Focus / Frozen Locus (exact at 50) by about -17%. So this is **not** a global enemy-config difference. Don't apply it as a default.
- Conclusion: the +7.7%..+12.9% DPS gap is specific to the spell/trigger-path skills (the ones where PoB leaves `HitAverage` at 0). Likely a per-skill mitigation/penetration/exposure or hit-vs-crit handling difference, i.e. (c) engine drift or a skill-specific condition. Still unconfirmed.
- Whirling Assault is off in the opposite direction at every setting tried (0.74 at default); separate cause.

### Batch 2, per-type probe of the spell/trigger-path skills (Tempest Bell, Storm Wave)

Probed by dumping enemy-side values from the headless engine (temporary bridge handler, reverted; no net bridge change).

- Enemy config in PoB matches the export: level 82, resists phys 0 / cold 40 / fire 50 / lightning 50 / chaos 0, no INC/MORE damage-taken, no penetration on the skill. Ninja's crit chance, crit multi and rate match PoB exactly for these skills (Tempest Bell 64.56% / 4.4 / 2.0; Storm Wave 100% / 3.38 / 1.667), so the hit inputs are not the cause.
- On the normal hit path (Hollow Focus) PoB's per-type multipliers are phys 0.416 (armour), cold 0.6, fire 0.5, lightning 0.5, i.e. the expected resist maths, and DPS and split match ninja exactly.
- On the spell/trigger path PoB sets `<Type>HitAverage`, `<Type>CritAverage` and `EffMult` all to 0 (the per-hit mitigation branch is not taken), but `AverageDamage` is non-zero: Storm Wave `AverageDamage` / pre-mitigation sum = 0.796, which the visible enemy resists cannot produce (they imply ~0.57). So PoB's DPS for these skills comes from a path whose per-type mitigation is not exposed in the output table. Ninja's split is within 3 to 9 percentage points of PoB's pre-mitigation split (less lightning, more phys and cold), which fits partial mitigation on ninja's side.
- **Classification:** (c) engine drift / different calc path (PoB bb52d6b vs ninja's current version), not fixable by config or by a mapping change, since no PoB output key carries the post-mitigation per-type value for these skills. `dps` +7.7% to +12.9% and the matching `split.*` rows stay as documented drift. The `verify_character` cause text already labels the split rows as a basis mismatch.

### Batch 2 status

| Group | Rows | Status |
|---|---|---|
| overall + defence | all | pass |
| Hollow Focus, Frozen Locus (dps, dot, split) | all | pass (split fixed in Batch 2) |
| Falling Thunder, Hollow Resonance, Staggering Palm, Storm Wave, Tempest Bell: dps, dot, split | 21 | (c) documented drift |
| Whirling Assault: dps -26%, dot -55%, split | 5 | open: unexplained, opposite direction from the others |

79/105 pass; the 26 failures are (c) drift plus Whirling Assault, which is not yet classified.

## App field mapping (Batch 3)

| Group | ninja key | App page location | App vs ninja on Yykiuy |
|---|---|---|---|
| overall/defence | life, energyShield, evasionRating, armour, spirit | Defences > Pools | match |
| defence | effectiveHealthPool | Defences > Pools | match |
| defence | `*MaximumHitTaken` x5 | Defences > Largest hit you survive | match |
| defence | resistances + OverCap | Defences > Resistances | match |
| damage | skills[].dps[].dps, critChance, critMultiplier, rate | Advanced > DPS matrix | match (Storm Wave +0.17%, in tolerance) |
| damage | damageTypes[] | Advanced > DPS matrix; Damage review | **mismatch: lightning/fire swapped** (see APP-FIX-LIST.md #1) |
| tree | passives node ids | Overview warning; Advanced > Passive tree | **3 ids unresolved** (APP-FIX-LIST.md #2) |
