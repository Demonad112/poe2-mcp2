"""Live engine test for get_skill_table. Skipped unless the headless engine is set up."""
import json
from pathlib import Path

import pytest

from src.pob import headless

pytestmark = [
    pytest.mark.pob_required,
    pytest.mark.skipif(not headless.find_environment()["ready"], reason="headless PoB2 engine not set up"),
]

FIX = Path(__file__).parent / "fixtures" / "ninja_yykiuy_charmodel.json"


def test_skill_table_rows_and_main_group_restored():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    m = d.get("charModel", d)
    with headless.HeadlessPoB(startup_timeout=240) as p:
        p.load_build(m["pathOfBuildingExport"])
        before = p.call("get_skills")["main_group"]
        rows = p.get_skill_table()
        assert rows and all("name" in r and "TotalDPS" in r and "split" in r for r in rows)
        assert p.call("get_skills")["main_group"] == before


def test_attack_rows_read_per_hand_output():
    """Attacks write AverageHit/TotalMin/TotalMax/<Type>HitAverage to output.MainHand, not the
    global output (docs/calcOffence.md); the table must still report them."""
    d = json.loads(FIX.read_text(encoding="utf-8"))
    m = d.get("charModel", d)
    with headless.HeadlessPoB(startup_timeout=240) as p:
        p.load_build(m["pathOfBuildingExport"])
        rows = {r["name"]: r for r in p.get_skill_table()}
    checked = 0
    for r in rows.values():
        if r.get("TotalDPS", 0) > 0 and r.get("Speed", 0) > 0 and r.get("AverageHit") is not None:
            # TotalDPS = AverageHit * HitChance% * Speed for single-hit skills
            if abs(r["AverageHit"] * r["HitChance"] / 100 * r["Speed"] - r["TotalDPS"]) / r["TotalDPS"] < 0.02:
                checked += 1
    assert checked >= 3
    assert rows["Falling Thunder"]["AverageHit"] > 0
    assert sum(v["hit_average"] for v in rows["Falling Thunder"]["split"].values()) > 0
