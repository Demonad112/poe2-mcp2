#!/usr/bin/env python3
"""Differential audit: src/calculator Python formulas vs the headless PoB2 engine.

Usage: python scripts/audit_python_vs_headless.py [charModel.json]   (default: ninja_yykiuy fixture)
Needs the headless engine (scripts/setup_headless_pob.sh). PoB = ground truth.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pob import headless
from src.calculator.defense_calculator import DefenseCalculator
from src.calculator.ehp_calculator import EHPCalculator, DefensiveStats, ThreatProfile, DamageType
from src.calculator.spell_dps_calculator import SpellDPSCalculator, SpellStats, CharacterModifiers, EnemyStats

FIELDS = ["Life", "EnergyShield", "Armour", "Evasion", "EvadeChance", "FireResist", "ColdResist",
          "LightningResist", "ChaosResist", "BlockChanceMax", "EnergyShieldRecharge",
          "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
          "LightningMaximumHitTaken", "ChaosMaximumHitTaken"]


def pob_monster_hit_chance(ev, acc):  # CalcDefence.lua calcs.monsterHitChance
    return max(min(round((1 - 0.95 * ev / (ev + 4 * acc)) * 100), 100), 5)


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/fixtures/ninja_yykiuy_charmodel.json"
    d = json.loads(path.read_text(encoding="utf-8")); m = d.get("charModel", d)
    with headless.HeadlessPoB(startup_timeout=300) as p:
        p.load_build(m["pathOfBuildingExport"])
        s = p.call("get_stats", fields=FIELDS)["stats"]
    rows = []
    # 1. evasion vs monster accuracy (enemy acc is level dependent; use 2114 = lvl 82 in the fixture)
    acc = 2114
    py = DefenseCalculator().calculate_evasion_chance(s["Evasion"], acc).evade_chance_percent
    rows.append((f"Evade pct (evasion={s['Evasion']}, acc={acc})", 100 - pob_monster_hit_chance(s["Evasion"], acc), py))
    # 2. max-hit / EHP per type (pool+resist only; PoB value includes enemy pen from config)
    for dt, k in [(DamageType.PHYSICAL, "Physical"), (DamageType.FIRE, "Fire"), (DamageType.COLD, "Cold"),
                  (DamageType.LIGHTNING, "Lightning"), (DamageType.CHAOS, "Chaos")]:
        ds = DefensiveStats(life=s["Life"], energy_shield=s["EnergyShield"], armor=s["Armour"], evasion=0,
                            fire_res=s["FireResist"], cold_res=s["ColdResist"],
                            lightning_res=s["LightningResist"], chaos_res=s["ChaosResist"])
        r = EHPCalculator().calculate_ehp(ds, dt, ThreatProfile(expected_hit_size=5000, attacker_accuracy=acc))
        rows.append((f"{k} max hit", s[f"{k}MaximumHitTaken"], r.effective_hp))
    # 3. resistance handling
    sp = SpellDPSCalculator()
    base = SpellStats(name="t", base_damage_min=100, base_damage_max=100, base_crit_chance=0, base_cast_time=1.0,
                      damage_types=["fire"], damage_effectiveness=1.0)
    for res, expo in [(0, 20), (-30, 0)]:
        out = sp.calculate_dps(base, CharacterModifiers(), EnemyStats(fire_resistance=res, fire_exposure=expo))
        pob_mult = 1 - max(min(res - expo, 90), -200) / 100  # Data.lua ResistFloor/MaxResistCap
        rows.append((f"Fire hit mult enemy res {res} exposure {expo}", round(pob_mult * 100, 1), out["average_hit"]))
    # 4. crit chance: PoB (base+added)*(1+inc/100)*more
    out = sp.calculate_dps(SpellStats(name="t", base_damage_min=100, base_damage_max=100, base_crit_chance=5,
                                      base_cast_time=1.0, damage_types=["fire"], damage_effectiveness=1.0),
                           CharacterModifiers(increased_crit_chance=200), EnemyStats())
    rows.append(("Crit pct base 5, +200% inc", 5 * (1 + 200 / 100), out["crit_chance"]))
    print(f"{'check':46s} {'PoB':>10s} {'python':>10s}  delta")
    for name, a, b in rows:
        flag = "" if abs(a - b) <= max(0.5, abs(a) * 0.005) else "  <-- MISMATCH"
        print(f"{name:46s} {a:>10.1f} {b:>10.1f}{flag}")


if __name__ == "__main__":
    main()
