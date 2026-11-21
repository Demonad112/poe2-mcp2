"""Engine-free regression: Python calculators vs recorded PoB engine output (tests/fixtures/pob_golden).
Regenerate goldens with a live engine when the PoB pin changes (see scripts/audit_python_vs_headless.py)."""
import importlib.util
import json
from pathlib import Path

import pytest

from src.calculator.ehp_calculator import EHPCalculator, DefensiveStats, ThreatProfile, DamageType

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit", ROOT / "scripts/audit_python_vs_headless.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
GOLD = sorted((ROOT / "tests/fixtures/pob_golden").glob("*.json"))


@pytest.mark.parametrize("path", GOLD, ids=[p.stem for p in GOLD])
def test_max_hit_and_max_res_match_pob(path):
    g = json.loads(path.read_text())
    s, raw = g["stats"], g["raw_resmax"]
    rmax = {e: audit.python_max_res(raw[f"{e}ResistMax"] + (raw["ElementalResistMax"] if e != "Chaos" else 0))
            for e in audit.ELEM}
    for e in ("Fire", "Cold", "Lightning", "Chaos"):
        if s[f"{e}ResistOverCap"] > 0:
            assert rmax[e] == s[f"{e}ResistTotal"] - s[f"{e}ResistOverCap"]
    ds = DefensiveStats(life=s["Life"], energy_shield=s["EnergyShield"], armor=s["Armour"], evasion=0,
                        runic_ward=s.get("WardOnAllArmourItems", 0),
                        fire_res=s["FireResistTotal"], cold_res=s["ColdResistTotal"],
                        lightning_res=s["LightningResistTotal"], chaos_res=s["ChaosResistTotal"],
                        fire_res_max=rmax["Fire"], cold_res_max=rmax["Cold"],
                        lightning_res_max=rmax["Lightning"], chaos_res_max=rmax["Chaos"])
    for dt, k in [(DamageType.PHYSICAL, "Physical"), (DamageType.FIRE, "Fire"), (DamageType.COLD, "Cold"),
                  (DamageType.LIGHTNING, "Lightning"), (DamageType.CHAOS, "Chaos")]:
        r = EHPCalculator().calculate_ehp(ds, dt, ThreatProfile(
            expected_hit_size=5000, attacker_accuracy=2114, enemy_fire_pen=s["FireEnemyPen"],
            enemy_cold_pen=s["ColdEnemyPen"], enemy_lightning_pen=s["LightningEnemyPen"]))
        assert r.effective_hp == pytest.approx(s[f"{k}MaximumHitTaken"], rel=2e-3), (k, path.stem)
