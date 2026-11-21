# Audit: `src/calculator` Python vs headless PoB2 (ground truth)

Method: formulas/constants compared with PoB2 `dev` source (`CalcDefence.lua`, `CalcOffence.lua`,
`Data.lua`, `Misc.lua`); numeric differential on the `ninja_yykiuy` fixture via
`scripts/audit_python_vs_headless.py` (re-runnable on any charModel). PoB checkout `601768b`.

## Verified correct (match PoB)
| Item | Python | PoB source |
|---|---|---|
| Armour DR `A/(A+10·D)`, 90% cap | defense_calculator | `armourReductionF`, ArmourRatio=10, DamageReductionCap=90 |
| Player-hits-monster hit chance `1.25·acc/(acc+0.3·ev)`, min 5 | `calculate_evasion_chance` (as a formula) | `calcs.hitChance` |
| Resist hard cap 90 / floor -200 | constants | `MaxResistCap`, `ResistFloor` |
| Base max block 50 | BLOCK_MAX_CHANCE | `object_inherent_base_maximum_block` = 50 (hard cap 90) |
| ES recharge 12.5%/s, delay `4/(1+f)` | defense_calculator | 750/min; live `EnergyShieldRechargeDelay` 3.5088 = 4/1.14 |
| Ailment %/s: ignite 20, poison 20, bleed 15; durations 4/2/5; bleed x2 moving | dot_calculator | Misc.lua 1200/1200/900 per min; durations; ConfigOptions |
| Archmage 4% gain-as-lightning per 100 max mana | spell_dps_calculator | `ArchmagePlayer` constantStats = 4 |
| Phys/chaos max hit (no armour / no pen) | ehp_calculator | exact (4399 / 9477) |
| Crit damage `1 + base·(1+inc)` ; non-crit/crit weighting | spell_dps_calculator | CalcOffence crit block |

## Mismatches (confirmed by execution)
Status: ✅ = fixed and harness row matches PoB (items 1-6). Items 7-10 open.
| # | Issue | PoB | Python | Impact |
|---|---|---|---|---|
| 1 ✅ | **Player evasion vs monster uses wrong formula.** PoB uses `calcs.monsterHitChance = 1 − 0.95·ev/(ev+4·acc)` | 48% | 44.1% | up to ~15 pts (2000 ev vs 2000 acc: 19% vs 3.8%) |
| 2 ✅ | **Max resistance ignored.** EHP calls `calculate_resistance_dr` without a cap, so 75 is hard-wired; builds with +max res (cold 80 here) are understated | cold max hit 19126 | 17596 | −8% |
| 3 ✅ | **No enemy elemental penetration.** PoB applies config `enemy<Type>Pen` (3 pts here) | fire 15711 / lightning 15169 | 17596 / 16919 | +12% / +12% overstated |
| 4 ✅ | **Negative enemy resistance floored at 0.** PoB keeps it (clamp -200..90); exposure on 0-res enemy gives +20% | 1.20x | 1.00x | understates damage |
| 5 ✅ | **"Increased crit chance" added linearly.** PoB: `(base+added)·(1+inc/100)·more` | 5% base +200% inc = 15% | 100% | large overstate |
| 6 ✅ | Crit multiplier ignores `MORE` CritMultiplier; no CritChanceCap input | – | – | minor |
| 7 | Speed has no PoB rounding (`round(...,2)`) or 33 ms server-tick quantisation | – | – | small |
| 8 | Damage conversion: single step, applied before modifiers; PoB converts in a chain (phys>lightning>cold>fire>chaos), scales >100% total, and converted damage keeps source-type tags | – | – | wrong when inc/more differ by type |
| 9 | Single `increased_spell_damage` pool: cannot model type-specific inc/more (e.g. Archmage extra lightning gets lightning mods in PoB) | – | – | structural |
| 10 | Shock hard-coded 1.2x; PoB `BaseShockMagnitude`=20 scaled by magnitude mods | – | – | minor |

## Recommendation
Treat `calculate_character_dps` / `ehp_calculator` as approximations. Fix 1-5 (each is a few lines); for exactness
route DPS/EHP through `headless_pob_calc` and keep the Python as an offline what-if only.
