#!/usr/bin/env python3
"""Differential audit: src/calculator Python formulas vs the headless PoB2 engine, multi-build.

Usage: python scripts/audit_python_vs_headless.py [--refresh] [--write-goldens] [build.json ...]
Builds: charModel JSON (pathOfBuildingExport) or tests/fixtures/builds/*.json ({"pob_xml": ...}).
Default: the Yykiuy charModel fixture + every tests/fixtures/builds/*.json. PoB = ground truth.
One engine session, results cached under .cache/pob (--refresh to bypass; a full cache hit never
launches luajit). Python-side values are derived from RAW inputs (modDB sums, engine-read hit pools),
never from PoB's own already-derived result for the same row.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.calculator.defense_calculator import DefenseCalculator, DefenseConstants  # noqa: E402
from src.calculator.dot_calculator import AilmentInput, DoTCalculator  # noqa: E402
from src.calculator.ehp_calculator import (  # noqa: E402
    DamageType,
    DefensiveStats,
    EHPCalculator,
    ThreatProfile,
)
from src.calculator.spell_dps_calculator import (  # noqa: E402
    CharacterModifiers,
    EnemyStats,
    SpellDPSCalculator,
    SpellStats,
)
from src.pob import headless  # noqa: E402
from src.pob.cache import CachedEngine  # noqa: E402

ENEMY_PHYS_DR_CAP = 75.0  # Data/Misc.lua monsterConstants["maximum_physical_damage_reduction_%"]
GOLD_DIR = ROOT / "tests/fixtures/pob_golden"
ELEM = ("Fire", "Cold", "Lightning", "Chaos")
FIELDS = [
    "FireResistTotal",
    "ColdResistTotal",
    "LightningResistTotal",
    "ChaosResistTotal",
    "FireResistOverCap",
    "ColdResistOverCap",
    "LightningResistOverCap",
    "ChaosResistOverCap",
    "FireEnemyPen",
    "ColdEnemyPen",
    "LightningEnemyPen",
    "ChaosEnemyPen",
    "PhysicalEnemyPen",
    "CritMultiplier",
    "CritChance",
    "Speed",
    "HitChance",
    "TotalDPS",
    "CombinedDPS",
    "Life",
    "EnergyShield",
    "Armour",
    "Evasion",
    "FireResist",
    "ColdResist",
    "LightningResist",
    "ChaosResist",
    "PhysicalStoredCombinedAvg",
    "MainHand.PhysicalStoredCritAvg",
    "MainHand.PhysicalStoredHitAvg",
    "PreEffectiveCritChance",
    "FireStoredCombinedAvg",
    "ColdStoredCombinedAvg",
    "LightningStoredCombinedAvg",
    "ChaosStoredCombinedAvg",
    "WardOnAllArmourItems",
    "PhysicalMaximumHitTaken",
    "FireMaximumHitTaken",
    "ColdMaximumHitTaken",
    "LightningMaximumHitTaken",
    "ChaosMaximumHitTaken",
    "IgniteDPS",
    "IgniteChanceOnHit",
    "Minion.TotalDPS",
    "Minion.AverageDamage",
    "Minion.Speed",
    "Minion.HitChance",
    "Minion.DpsMultiplier",
]


def _prod(it):
    r = 1.0
    for x in it:
        r *= x
    return r


def pob_monster_hit_chance(ev, acc):  # CalcDefence.lua calcs.monsterHitChance
    return max(min(round((1 - 0.95 * ev / (ev + 4 * acc)) * 100), 100), 5)


def load_builds(args):
    paths = [Path(a) for a in args] or (
        [ROOT / "tests/fixtures/ninja_yykiuy_charmodel.json"]
        + sorted((ROOT / "tests/fixtures/builds").glob("*.json"))
    )
    out = []
    for p in paths:
        d = json.loads(p.read_text(encoding="utf-8"))
        if "pob_xml" in d:
            out.append((d.get("name", p.stem), headless.decode_pob_code(d["pob_xml"])))
        else:
            m = d.get("charModel", d)
            out.append((p.stem, headless.decode_pob_code(m["pathOfBuildingExport"])))
    return out


def python_max_res(raw_sum):
    """Python-derived max res from the raw modDB ResistMax sums (75 base + build mods), clamped at the 90 hard cap.
    Run through DefenseCalculator (overcap value 999 => effective value == cap)."""
    # modDB <Elem>ResistMax BASE already includes the 75 base (verified: FireResistMax == 75 on a vanilla build)
    cap = min(DefenseConstants.RESISTANCE_HARD_CAP, raw_sum)
    return DefenseCalculator().calculate_resistance_dr(999, cap).resistance_percent


def python_conversion_dps(s, inp):
    """TotalDPS rebuilt from the engine's pre-mitigation per-type hit pools, mitigated in Python following
    CalcOffence.lua ~4283-4400: enemy res / DamageTaken read with the skill cfg, penetration from the main
    skill's skillModList (never {t}EnemyPen, which is enemy-vs-player), x HitChance x Speed x DpsMultiplier
    x QuantityMultiplier. `inp` = the sum_mod results recorded by audit_build (also stored in the goldens).
    """
    skill_pen, e_res, t_inc, t_more, extra = (
        inp[k] for k in ("skill_pen", "e_res", "t_inc", "t_more", "extra")
    )
    py_hit = 0.0
    for t in ("Physical",) + ELEM:
        pool = s.get(f"{t}StoredCombinedAvg", 0) or 0
        if not pool:
            continue
        elem = t in ELEM[:3]
        names = ["DamageTaken", f"{t}DamageTaken"] + (["ElementalDamageTaken"] if elem else [])
        taken = (1 + sum(t_inc[n] for n in names) / 100) * _prod(t_more[n] for n in names)
        if t == "Physical":
            # Armour DR is nonlinear in hit size, so mitigate the crit and non-crit hits separately
            # (PoB runs one pass each) instead of the crit-weighted pool.
            # Enemy physical DR is capped at monsterConstants max_physical_damage_reduction (75), not the player's 90.
            def dr(armour, raw):
                r = DefenseCalculator().calculate_armor_dr(armour, raw)
                r.damage_reduction_percent = min(r.damage_reduction_percent, ENEMY_PHYS_DR_CAP)
                return r

            cc = (s.get("PreEffectiveCritChance") or 0) / 100
            hit_a, crit_a = (
                s.get("MainHand.PhysicalStoredHitAvg") or s.get("PhysicalStoredHitAvg") or 0,
                s.get("MainHand.PhysicalStoredCritAvg") or s.get("PhysicalStoredCritAvg") or 0,
            )
            if hit_a and crit_a:
                eff = crit_a * (
                    1 - dr(e_res["Armour"], crit_a).damage_reduction_percent / 100
                ) * cc + hit_a * (1 - dr(e_res["Armour"], hit_a).damage_reduction_percent / 100) * (
                    1 - cc
                )
                mult = eff / pool if pool else 0
            else:
                mult = 1 - dr(e_res["Armour"], pool).damage_reduction_percent / 100
        else:
            res = e_res[f"{t}Resist"] + (e_res["ElementalResist"] if elem else 0)
            pen = skill_pen[f"{t}Penetration"] + (skill_pen["ElementalPenetration"] if elem else 0)
            min_pen = (
                (skill_pen[f"{t}PenetrationMinimum"] + skill_pen["ElementalPenetrationMinimum"])
                if elem
                else 0
            )
            res = max(min(res, DefenseConstants.RESISTANCE_HARD_CAP), -200)
            res = max(res - pen, min_pen) if res > min_pen else res  # calcPenResist
            mult = 1 - res / 100
        py_hit += pool * mult * taken
    qty = max(extra.get("QuantityMultiplier") or 1, 1)
    return py_hit * s["HitChance"] / 100 * s["Speed"] * (extra.get("DpsMultiplier") or 1) * qty


def audit_build(name, xml, eng, base):
    s = eng.stats(xml, fields=FIELDS)
    table = eng.skill_table(xml)
    raw = eng.sum_mod(xml, [f"{e}ResistMax" for e in ELEM] + ["ElementalResistMax"])
    enemy = eng.sum_mod(
        xml, ["FireResist", "ColdResist", "LightningResist", "ChaosResist", "Armour"], db="enemy"
    )
    rows = []
    # max res: python from raw inputs vs engine ResistTotal-OverCap (only valid when over cap)
    rmax = {}
    for e in ELEM:
        rmax[e] = python_max_res(
            raw[f"{e}ResistMax"] + (raw["ElementalResistMax"] if e != "Chaos" else 0)
        )
        eng_cap = s[f"{e}ResistTotal"] - s[f"{e}ResistOverCap"]
        over = s[f"{e}ResistOverCap"] > 0
        if over:
            rows.append((f"{e} max res (raw base75+mods vs PoB total-overcap)", eng_cap, rmax[e]))
        else:  # under cap: engine total-overcap is NOT the cap; compare the engine capped value vs min(total,cap)
            rows.append(
                (
                    f"{e} res applied (under cap; python min(total,cap))",
                    s[f"{e}Resist"],
                    min(s[f"{e}ResistTotal"], rmax[e]),
                )
            )
    acc = 2114
    py = DefenseCalculator().calculate_evasion_chance(s["Evasion"], acc).evade_chance_percent
    rows.append(
        (
            f"Evade pct (evasion={s['Evasion']:.0f}, acc={acc})",
            100 - pob_monster_hit_chance(s["Evasion"], acc),
            py,
        )
    )
    for dt, k in [
        (DamageType.PHYSICAL, "Physical"),
        (DamageType.FIRE, "Fire"),
        (DamageType.COLD, "Cold"),
        (DamageType.LIGHTNING, "Lightning"),
        (DamageType.CHAOS, "Chaos"),
    ]:
        ds = DefensiveStats(
            life=s["Life"],
            energy_shield=s["EnergyShield"],
            armor=s["Armour"],
            evasion=0,
            runic_ward=s.get("WardOnAllArmourItems", 0),
            fire_res=s["FireResistTotal"],
            cold_res=s["ColdResistTotal"],
            lightning_res=s["LightningResistTotal"],
            chaos_res=s["ChaosResistTotal"],
            fire_res_max=rmax["Fire"],
            cold_res_max=rmax["Cold"],
            lightning_res_max=rmax["Lightning"],
            chaos_res_max=rmax["Chaos"],
        )
        r = EHPCalculator().calculate_ehp(
            ds,
            dt,
            ThreatProfile(
                expected_hit_size=5000,
                attacker_accuracy=acc,
                enemy_fire_pen=s["FireEnemyPen"],
                enemy_cold_pen=s["ColdEnemyPen"],
                enemy_lightning_pen=s["LightningEnemyPen"],
            ),
        )
        if (
            s.get(f"{k}MaximumHitTaken") is None
        ):  # engine omits it when immune (e.g. Chaos Inoculation)
            continue
        rows.append((f"{k} max hit", s[f"{k}MaximumHitTaken"], r.effective_hp))
    # conversion-chain total DPS: python mitigation of engine-read per-type pre-mitigation hit pools,
    # following CalcOffence.lua ~4283-4400 (enemy res/DamageTaken read with the skill cfg; penetration
    # read from the main skill's skillModList; player-vs-enemy only, so no {t}EnemyPen).
    skill_pen = eng.sum_mod(
        xml,
        [f"{e}Penetration" for e in ELEM]
        + ["ElementalPenetration"]
        + [f"{e}PenetrationMinimum" for e in ELEM[:3]]
        + ["ElementalPenetrationMinimum"],
        db="skill",
    )
    e_res = eng.sum_mod(
        xml, [f"{e}Resist" for e in ELEM] + ["ElementalResist", "Armour"], db="enemy", cfg="skill"
    )
    taken_names = ["DamageTaken", "ElementalDamageTaken"] + [
        f"{t}DamageTaken" for t in ("Physical",) + ELEM
    ]
    t_inc = eng.sum_mod(xml, taken_names, db="enemy", mod_type="INC", cfg="skill")
    t_more = eng.sum_mod(xml, taken_names, db="enemy", mod_type="MORE", cfg="skill")
    extra = eng.stats(xml, fields=["DpsMultiplier", "QuantityMultiplier"])
    dps_inputs = {
        "skill_pen": skill_pen,
        "e_res": e_res,
        "t_inc": t_inc,
        "t_more": t_more,
        "extra": extra,
    }
    rows.append(
        (
            "Conversion-chain TotalDPS (python mitigation of pools)",
            s["TotalDPS"],
            python_conversion_dps(s, dps_inputs),
        )
    )
    # hit-DoT: Ignite DPS. Python ailment math on the engine-read crit-weighted fire hit pool, enemy fire res
    # read from the enemy modDB (skill cfg) and the engine's own hit rate; PoB = IgniteDPS.
    if s.get("IgniteDPS") and s.get("IgniteChanceOnHit"):
        res = e_res["FireResist"] + e_res["ElementalResist"]
        ig = DoTCalculator().calculate_ailment_dot(
            AilmentInput(ailment="ignite", chance_pct=s.get("IgniteChanceOnHit") or 0),
            {"fire": s["FireStoredCombinedAvg"]},
            s["Speed"],
            EnemyStats(fire_resistance=res),
        )
        rows.append(
            (
                "Ignite DPS (python ailment math x chance, engine fire pool)",
                s["IgniteDPS"],
                ig["dps_per_stack"] * min(s["IgniteChanceOnHit"], 100) / 100,
            )
        )
    # minion DPS: engine-read per-hit minion damage x its attack/cast rate x hit chance x DPS multiplier.
    if s.get("Minion.TotalDPS"):
        rows.append(
            (
                "Minion TotalDPS (AverageDamage x Speed x HitChance x DpsMult)",
                s["Minion.TotalDPS"],
                s["Minion.AverageDamage"]
                * s["Minion.Speed"]
                * s["Minion.HitChance"]
                / 100
                * (s.get("Minion.DpsMultiplier") or 1),
            )
        )
    # damage-type split sanity vs skill table (main = highest TotalDPS)
    main = max(table, key=lambda x: x["TotalDPS"]) if table else None
    cats = []
    if main:
        sh = [k for k, v in main["split"].items() if v["combined_average"] > 0]
        if len(sh) >= 3:
            cats.append("conversion")
    if any(rmax[e] >= 80 for e in ELEM):
        cats.append("high-max-res")
    golden = {
        "pob_commit": headless.pob_commit(),
        "raw_resmax": raw,
        "stats": s,
        "dps_inputs": dps_inputs,
    }
    if "spell" in name:
        cats.append("spell")
    return rows, cats, (main["name"] if main else "?"), golden


def shared_rows():
    sp = SpellDPSCalculator()
    base = SpellStats(
        name="t",
        base_damage_min=100,
        base_damage_max=100,
        base_crit_chance=0,
        base_cast_time=1.0,
        damage_types=["fire"],
        damage_effectiveness=1.0,
    )
    rows = []
    for res, expo in [(0, 20), (-30, 0)]:
        out = sp.calculate_dps(
            base, CharacterModifiers(), EnemyStats(fire_resistance=res, fire_exposure=expo)
        )
        rows.append(
            (
                f"Fire hit mult enemy res {res} exposure {expo}",
                round((1 - max(min(res - expo, 90), -200) / 100) * 100, 1),
                out["average_hit"],
            )
        )
    out = sp.calculate_dps(
        SpellStats(
            name="t",
            base_damage_min=100,
            base_damage_max=100,
            base_crit_chance=5,
            base_cast_time=1.0,
            damage_types=["fire"],
            damage_effectiveness=1.0,
        ),
        CharacterModifiers(increased_crit_chance=200),
        EnemyStats(),
    )
    rows.append(("Crit pct base 5, +200% inc", 15.0, out["crit_chance"]))
    rows.append(
        (
            "Crit mult 100 base,+50% inc,+20% more",
            1 + 1.0 * 1.5 * 1.2,
            sp._calculate_crit_multiplier(100, 50, 20),
        )
    )
    rows.append(
        ("Cast speed cap (1/0.033 server tick)", 1 / 0.033, sp._calculate_cast_speed(1.0, 5000))
    )
    return rows


def shock_row(eng, xml):
    off = eng.stats(xml, {"conditionEnemyShocked": False}, ["CombinedDPS"])["CombinedDPS"]
    on = eng.stats(
        xml, {"conditionEnemyShocked": True, "conditionShockEffect": 50}, ["CombinedDPS"]
    )["CombinedDPS"]
    sp = SpellDPSCalculator()
    base = SpellStats(
        name="t",
        base_damage_min=100,
        base_damage_max=100,
        base_crit_chance=0,
        base_cast_time=1.0,
        damage_types=["fire"],
        damage_effectiveness=1.0,
    )
    a = sp.calculate_dps(
        base, CharacterModifiers(), EnemyStats(is_shocked=True, shock_magnitude=50)
    )["average_hit"]
    b = sp.calculate_dps(base, CharacterModifiers(), EnemyStats())["average_hit"]
    return ("Shock 50% effect DPS ratio (PoB engine)", on / off, a / b)


def fmt(rows):
    n_bad = 0
    print(f"{'check':64s} {'PoB':>11s} {'python':>11s}  delta%")
    for name, a, b in rows:
        d = (b - a) / a * 100 if a else 0.0
        bad = abs(a - b) > max(0.5, abs(a) * 0.005)
        n_bad += bad
        print(f"{name:64s} {a:>11.1f} {b:>11.1f}  {d:+6.1f}%{'  <-- MISMATCH' if bad else ''}")
    return n_bad


def main():
    argv = sys.argv[1:]
    refresh = "--refresh" in argv
    write_goldens = "--write-goldens" in argv
    builds = load_builds([a for a in argv if not a.startswith("--")])
    total_bad, all_cats = 0, set()
    with CachedEngine(refresh=refresh) as eng:
        for i, (name, xml) in enumerate(builds):
            rows, cats, main_skill, golden = audit_build(name, xml, eng, i)
            if write_goldens:
                (GOLD_DIR / f"{name}.json").write_text(
                    json.dumps(golden, indent=1, sort_keys=True) + "\n"
                )
            if i == 0:
                rows += shared_rows() + [shock_row(eng, xml)]
            all_cats |= set(cats)
            print(
                f"\n=== {name}  (main skill: {main_skill}; categories: attack, {', '.join(cats) or '-'}) ==="
            )
            total_bad += fmt(rows)
        launches = eng.engine_launches
    missing = [c for c in ("spell", "high-max-res") if c not in all_cats]
    # spell builds cannot be auto-detected from the engine; none of the supplied builds is a spell build
    if "spell" not in all_cats:
        print("\nspell build: no build supplied (not synthesised)")
    if "high-max-res" in missing:
        print("high-max-res (>=80 on all elements): no build supplied")
    print(
        f"\n{total_bad} mismatching row(s) across {len(builds)} build(s); engine launches: {launches}"
    )


if __name__ == "__main__":
    main()
