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
