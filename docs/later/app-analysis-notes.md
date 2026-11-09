# Deferred notes (post Batch 1)

- **Damage rows fail (32/105 on Yykiuy)**: per-skill DPS +7–13% high on Falling Thunder, Hollow Resonance, Staggering Palm, Storm Wave, Tempest Bell; Whirling Assault −26% (ninja `damage[0]`=55974 vs `dps`=38106 — ninja-side inconsistency, unresolved). Triage per skill: config / mapping / drift.
- **Damage-type split**: physical/cold/lightning share off by several points on most skills; possible ordering or basis (hit vs crit-weighted) bug in `_TYPES` zip vs ninja `damageTypes` order. Frozen Locus and Hollow Focus: DPS within tolerance but split wrong.
- **Unresolved passive nodes**: 15343, 49356, 60239 (not resolved by the importer).
- Verify DEFENCE_FIELD_SET key names against PoB2 source rather than only fixture agreement.
