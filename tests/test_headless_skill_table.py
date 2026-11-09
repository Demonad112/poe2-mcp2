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
