"""Pure tests for reconcile_with_ninja (stubbed headless engine, no PoB needed)."""
import json
from pathlib import Path

import pytest

from src.calculator import reconcile_poe_ninja as rp
from src.pob import headless as hl

FIX = Path(__file__).parent / "fixtures" / "ninja_yykiuy_charmodel.json"


def _model():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    return d.get("charModel", d)


class StubHeadless:
    """Returns PoB values equal to ninja's, so the baseline report is all-pass for defence."""

    def __init__(self, model, scale=None, skill_dps_scale=1.0):
        self.model, self.scale, self.k = model, scale or {}, skill_dps_scale

    def load_build(self, code):
        assert code

    def call(self, action, **p):
        assert action == "get_stats"
        ds = self.model["defensiveStats"]
        out = {}
        for nkey, (pkey, kind) in hl.DEFENCE_FIELD_SET.items():
            if nkey in ds:
                v = ds[nkey] / 100 if kind == "floor100" else ds[nkey]
                out[pkey] = v * self.scale.get(nkey, 1)
        return {"stats": out}

    def get_skill_table(self):
        rows = []
        for sk in self.model.get("skills", []):
            for e in sk.get("dps", []):
                rows.append({"name": e["name"], "TotalDPS": (e.get("dps") or 0) * self.k, "split": {}})
        return rows


def test_schema_and_defence_pass():
    r = rp.reconcile_with_ninja(_model(), headless=StubHeadless(_model()), pob_commit="x")
    assert r["schema"] == "verify-report/v1"
    assert r["source"]["pob_commit"] == "x"
    assert not [d for d in r["diffs"] if d["group"] in ("defence", "overall") and not d["pass"]]


def test_integer_mismatch_fails_with_cause():
    m = _model()
    r = rp.reconcile_with_ninja(m, headless=StubHeadless(m, scale={"life": 1.01}))
    bad = [d for d in r["diffs"] if d["field"] == "life"][0]
    assert not bad["pass"] and bad["cause"]


def test_ehp_within_one_percent_passes_and_over_fails():
    m = _model()
    ok = rp.reconcile_with_ninja(m, headless=StubHeadless(m, scale={"effectiveHealthPool": 1.005}))
    assert [d for d in ok["diffs"] if d["field"] == "effectiveHealthPool"][0]["pass"]
    bad = rp.reconcile_with_ninja(m, headless=StubHeadless(m, scale={"effectiveHealthPool": 1.02}))
    assert not [d for d in bad["diffs"] if d["field"] == "effectiveHealthPool"][0]["pass"]


def test_failures_sorted_first_and_summary_counts():
    m = _model()
    r = rp.reconcile_with_ninja(m, headless=StubHeadless(m, skill_dps_scale=1.2))
    flags = [d["pass"] for d in r["diffs"]]
    assert flags == sorted(flags)
    s = r["summary"]
    assert s["total"] == len(r["diffs"]) and s["failed"] == flags.count(False)
    assert any(d["field"].endswith(".dps") and not d["pass"] for d in r["diffs"])


def test_missing_export_raises():
    with pytest.raises(ValueError):
        rp.reconcile_with_ninja({"defensiveStats": {}}, headless=object())


def test_markdown_lists_failures_first():
    m = _model()
    r = rp.reconcile_with_ninja(m, headless=StubHeadless(m, scale={"life": 2}))
    md = rp.format_verify_markdown(r)
    assert "life" in md and md.index("life") < md.index("energyShield") if "energyShield" in md else True
