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

FIELDS = ["FireResistTotal", "ColdResistTotal", "LightningResistTotal", "ChaosResistTotal",
          "FireResistOverCap", "ColdResistOverCap", "LightningResistOverCap", "ChaosResistOverCap",
          "FireEnemyPen", "ColdEnemyPen", "LightningEnemyPen", "CritMultiplier", "CritChance", "Speed",
          "CombinedDPS","Life", "EnergyShield", "Armour", "Evasion", "EvadeChance", "FireResist", "ColdResist",
          "LightningResist", "ChaosResist", "BlockChanceMax", "EnergyShieldRecharge",
          "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
          "LightningMaximumHitTaken", "ChaosMaximumHitTaken"]


def pob_monster_hit_chance(ev, acc):  # CalcDefence.lua calcs.monsterHitChance
    return max(min(round((1 - 0.95 * ev / (ev + 4 * acc)) * 100), 100), 5)


def main():  # always offline: no network, only the headless engine + local charModel
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
    # real per-element max res = ResistTotal - ResistOverCap (CalcDefence.lua)
    rmax = {e: s[f"{e}ResistTotal"] - s[f"{e}ResistOverCap"] for e in ("Fire", "Cold", "Lightning", "Chaos")}
    for e, v in rmax.items():
        rows.append((f"{e} max resist (PoB ResistTotal-OverCap)", v, max(0.0, min(90.0, v))))
    for dt, k in [(DamageType.PHYSICAL, "Physical"), (DamageType.FIRE, "Fire"), (DamageType.COLD, "Cold"),
                  (DamageType.LIGHTNING, "Lightning"), (DamageType.CHAOS, "Chaos")]:
        ds = DefensiveStats(life=s["Life"], energy_shield=s["EnergyShield"], armor=s["Armour"], evasion=0,
                            fire_res=s["FireResist"], cold_res=s["ColdResist"],
                            lightning_res=s["LightningResist"], chaos_res=s["ChaosResist"],
                            # PoB outputs the already-capped value, so max = max(cap seen, 75)
                            fire_res_max=rmax["Fire"], cold_res_max=rmax["Cold"],
                            lightning_res_max=rmax["Lightning"], chaos_res_max=rmax["Chaos"])
        # PoB default config enemy elemental pen = 3 (derived: 4399/maxhit = 1-(res-3)/100)
        r = EHPCalculator().calculate_ehp(ds, dt, ThreatProfile(expected_hit_size=5000, attacker_accuracy=acc,
                                          enemy_fire_pen=s['FireEnemyPen'], enemy_cold_pen=s['ColdEnemyPen'], enemy_lightning_pen=s['LightningEnemyPen']))
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
    # 5. crit multiplier (PoB: 1 + base*inc*more) - split the build's value into the 'more' piece
    cm = SpellDPSCalculator()._calculate_crit_multiplier(100, 0, 0)
    rows.append(("Crit mult base (PoB 1+100% => 2.0)", 2.0, cm))
    cm2 = SpellDPSCalculator()._calculate_crit_multiplier(100, 50, 20)
    rows.append(("Crit mult 100 base,+50% inc,+20% more", 1 + 1.0 * 1.5 * 1.2, cm2))
    # 6. speed rounding / server tick: PoB caps Speed at ServerTickRate = 1/0.033
    rows.append(("Cast speed cap (1/0.033 server tick)", 1 / 0.033, SpellDPSCalculator()._calculate_cast_speed(1.0, 5000)))
    # 7. shock magnitude: PoB default BaseShockMagnitude=20, scales with config effect
    with headless.HeadlessPoB(startup_timeout=300) as p2:
        p2.load_build(m["pathOfBuildingExport"])
        off = p2.call("set_config", config={"conditionEnemyShocked": False}, fields=["CombinedDPS"])["stats"]["CombinedDPS"]
        on = p2.call("set_config", config={"conditionEnemyShocked": True, "conditionShockEffect": 50}, fields=["CombinedDPS"])["stats"]["CombinedDPS"]
    sp2 = SpellDPSCalculator()
    out_s = sp2.calculate_dps(base, CharacterModifiers(), EnemyStats(is_shocked=True, shock_magnitude=50))["average_hit"]
    out_n = sp2.calculate_dps(base, CharacterModifiers(), EnemyStats())["average_hit"]
    rows.append(("Shock 50% effect DPS ratio (PoB engine)", on / off, out_s / out_n))
    print(f"{'check':46s} {'PoB':>10s} {'python':>10s}  delta")
    for name, a, b in rows:
        flag = "" if abs(a - b) <= max(0.5, abs(a) * 0.005) else "  <-- MISMATCH"
        print(f"{name:46s} {a:>10.1f} {b:>10.1f}{flag}")


if __name__ == "__main__":
    main()
