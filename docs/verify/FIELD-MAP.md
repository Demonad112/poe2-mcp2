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
