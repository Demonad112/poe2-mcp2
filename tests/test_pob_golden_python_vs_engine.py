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
        if s.get(f"{k}MaximumHitTaken") is None:  # engine omits it when immune (Chaos Inoculation)
            continue
        assert r.effective_hp == pytest.approx(s[f"{k}MaximumHitTaken"], rel=2e-3), (k, path.stem)


@pytest.mark.parametrize("path", GOLD, ids=[p.stem for p in GOLD])
def test_golden_recorded_at_pinned_commit(path):
    from src.pob import headless
    g = json.loads(path.read_text())
    assert g["pob_commit"] == headless.POB_COMMIT_PIN, (
        f"{path.name} was recorded at PoB2 {g['pob_commit']} but POB_COMMIT_PIN is {headless.POB_COMMIT_PIN}. "
        "Regenerate: scripts/audit_python_vs_headless.py --refresh --write-goldens (engine at the pin)."
    )


def test_engine_checkout_matches_pin():
    from src.pob import headless
    env = headless.find_environment()
    if not env.get("pob_src_present"):
        pytest.skip("no PoB2 checkout present")
    assert headless.pob_commit() == headless.POB_COMMIT_PIN, (
        f"PoB2 checkout is {headless.pob_commit()} but POB_COMMIT_PIN is {headless.POB_COMMIT_PIN}. "
        "Run scripts/setup_headless_pob.sh (fetches the pin) or bump the pin AND regenerate the goldens."
    )


DPS_GOLD = [p for p in GOLD if "dps_inputs" in json.loads(p.read_text())]


@pytest.mark.parametrize("path", DPS_GOLD, ids=[p.stem for p in DPS_GOLD])
def test_conversion_chain_dps_matches_pob(path):
    g = json.loads(path.read_text())
    s = g["stats"]
    if not s.get("TotalDPS"):
        pytest.skip("build has no hit DPS (DoT-only)")
    assert audit.python_conversion_dps(s, g["dps_inputs"]) == pytest.approx(s["TotalDPS"], rel=0.02)
