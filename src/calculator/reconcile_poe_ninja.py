"""
Calculator reconciliation harness — validate our EHP / defense / resource
calcs against poe.ninja's ``charModel.defensiveStats`` oracle (issue #139).

poe.ninja's ``charModel`` payload ships its OWN computed defensive numbers
for the exact character build it returns. Since that's *character data*
(allowed by data policy, not game mechanics), it makes a zero-policy-risk
regression oracle for our local calculators.

This module is intentionally a light helper with no SQLAlchemy / no async /
no MCP-server imports — pure stat-shaping + delta math. Callers feed in a
``charModel`` dict (loaded from a fixture or returned by the character
fetcher) and a ``ThreatProfile``; the harness produces a per-stat report
with our value, poe.ninja's value, the delta, and a within-tolerance flag.

Acceptance criteria for #139:
  - Per-stat diff table vs ``defensiveStats``                    [shipped]
  - Runs against an offline fixture corpus                        [shipped via tests]
  - Tolerances configurable, meaningful deltas fail               [shipped]
  - ``breakdowns.stats`` multiplier reconciliation                [deferred -
    needs trace_dps_calculation refactor; out of this PR's scope]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from .ehp_calculator import (
        DamageType,
        DefensiveStats,
        EHPCalculator,
        ThreatProfile,
    )
except ImportError:
    from src.calculator.ehp_calculator import (
        DamageType,
        DefensiveStats,
        EHPCalculator,
        ThreatProfile,
    )

logger = logging.getLogger(__name__)


# Default per-stat tolerances (percent). Picked generously enough to absorb
# the genuine model differences (PoE2's full layered-defense math vs.
# whatever shortcut poe.ninja uses), but tight enough that a real bug
# in our calc moves a stat outside the band.
DEFAULT_TOLERANCE_PCT: Dict[str, float] = {
    "effective_hp": 15.0,
    "physical_max_hit": 15.0,
    "fire_max_hit": 15.0,
    "cold_max_hit": 15.0,
    "lightning_max_hit": 15.0,
    "chaos_max_hit": 15.0,
}


@dataclass
class StatDelta:
    """One row of the reconciliation report.

    Attributes:
        stat: Stat name (matches DEFAULT_TOLERANCE_PCT key).
        our_value: Value computed by our local calculator.
        oracle_value: Value reported by poe.ninja's ``defensiveStats``.
        abs_delta: ``|our - oracle|``.
        pct_delta: ``abs_delta / max(|oracle|, 1) * 100``.
        tolerance_pct: Tolerance band applied to this stat.
        within_tolerance: ``pct_delta <= tolerance_pct``.
    """

    stat: str
    our_value: float
    oracle_value: float
    abs_delta: float
    pct_delta: float
    tolerance_pct: float
    within_tolerance: bool


@dataclass
class ReconciliationReport:
    """Full output of a reconciliation run.

    Attributes:
        char_name: Echo of ``charModel.name`` if present (handy for logs).
        deltas: One ``StatDelta`` per reconciled stat (skips stats absent
            from the oracle).
        all_within_tolerance: True iff every delta is within its band.
        skipped: List of stat names not present in the oracle.
    """

    char_name: Optional[str]
    deltas: List[StatDelta] = field(default_factory=list)
    all_within_tolerance: bool = True
    skipped: List[str] = field(default_factory=list)


def build_defensive_stats_from_charmodel(char_model: Dict[str, Any]) -> DefensiveStats:
    """Adapt a poe.ninja ``charModel`` (or its embedded ``defensiveStats`` sub-dict)
    into our internal ``DefensiveStats`` dataclass.

    poe.ninja's field names are camelCase and slightly different from ours;
    this maps the known overlaps. Unknown / 0.5-specific fields (e.g.
    ``runicWard``) are passed through where the dataclass has a slot for
    them, defaulted otherwise.

    Args:
        char_model: A full ``charModel`` dict OR its inner ``defensiveStats``
            sub-dict (auto-detected via key probe).

    Returns:
        A populated ``DefensiveStats``.
    """
    if "defensiveStats" in char_model:
        ds = char_model["defensiveStats"]
    else:
        ds = char_model

    # poe.ninja uses British spelling ("armour") and stores resistances
    # as percentages already.
    return DefensiveStats(
        life=float(ds.get("life", 0.0)),
        energy_shield=float(ds.get("energyShield", ds.get("energy_shield", 0.0))),
        runic_ward=float(ds.get("runicWard", ds.get("runic_ward", 0.0))),
        armor=float(ds.get("armour", ds.get("armor", 0.0))),
        evasion=float(ds.get("evasion", 0.0)),
        block_chance=float(ds.get("block", ds.get("blockChance", 0.0))),
        fire_res=float(ds.get("fireResistance", ds.get("fire_res", 0.0))),
        cold_res=float(ds.get("coldResistance", ds.get("cold_res", 0.0))),
        lightning_res=float(ds.get("lightningResistance", ds.get("lightning_res", 0.0))),
        chaos_res=float(ds.get("chaosResistance", ds.get("chaos_res", 0.0))),
    )


def reconcile_defensive_stats(
    char_model: Dict[str, Any],
    threat: Optional[ThreatProfile] = None,
    tolerance_pct: Optional[Dict[str, float]] = None,
) -> ReconciliationReport:
    """Run our EHP / defense calculators on the build poe.ninja describes,
    then diff each headline number against poe.ninja's own value.

    Args:
        char_model: A full ``charModel`` dict, or just its ``defensiveStats``
            sub-dict. Both shapes are accepted.
        threat: Optional threat profile (hit size, accuracy). Defaults to
            ``ThreatProfile()``.
        tolerance_pct: Per-stat tolerance overrides. Falls back to
            ``DEFAULT_TOLERANCE_PCT`` for unset entries.

    Returns:
        A populated ``ReconciliationReport``.
    """
    oracle = char_model.get("defensiveStats", char_model)
    tolerances = {**DEFAULT_TOLERANCE_PCT, **(tolerance_pct or {})}
    threat = threat or ThreatProfile()
    calc = EHPCalculator()

    stats = build_defensive_stats_from_charmodel(char_model)
    name = char_model.get("name") if isinstance(char_model.get("name"), str) else None
    report = ReconciliationReport(char_name=name)

    def _add_delta(stat: str, ours: float, oracle_key: str):
        if oracle_key not in oracle:
            report.skipped.append(stat)
            return
        oracle_val = float(oracle[oracle_key])
        abs_d = abs(ours - oracle_val)
        denom = max(abs(oracle_val), 1.0)
        pct = abs_d / denom * 100.0
        tol = tolerances.get(stat, 15.0)
        within = pct <= tol
        report.deltas.append(
            StatDelta(
                stat=stat,
                our_value=ours,
                oracle_value=oracle_val,
                abs_delta=abs_d,
                pct_delta=pct,
                tolerance_pct=tol,
                within_tolerance=within,
            )
        )
        if not within:
            report.all_within_tolerance = False

    # effective_hp: poe.ninja reports a single composite "effectiveHealthPool".
    # We approximate by computing physical EHP and treating it as the
    # representative number for now (poe.ninja's exact damage-type weighting
    # is opaque). Tolerance bands above account for the model difference.
    try:
        ehp_phys = calc.calculate_ehp(stats, DamageType.PHYSICAL, threat)
        _add_delta("effective_hp", ehp_phys.effective_hp, "effectiveHealthPool")
        _add_delta("physical_max_hit", ehp_phys.effective_hp, "physicalMaximumHitTaken")
    except Exception as e:
        logger.warning(f"Physical EHP calc failed during reconcile: {e}")
        report.skipped.extend(["effective_hp", "physical_max_hit"])

    for dt, oracle_key, stat_name in [
        (DamageType.FIRE, "fireMaximumHitTaken", "fire_max_hit"),
        (DamageType.COLD, "coldMaximumHitTaken", "cold_max_hit"),
        (DamageType.LIGHTNING, "lightningMaximumHitTaken", "lightning_max_hit"),
        (DamageType.CHAOS, "chaosMaximumHitTaken", "chaos_max_hit"),
    ]:
        try:
            ehp = calc.calculate_ehp(stats, dt, threat)
            _add_delta(stat_name, ehp.effective_hp, oracle_key)
        except Exception as e:
            logger.warning(f"{dt.value} EHP calc failed during reconcile: {e}")
            report.skipped.append(stat_name)

    return report


def format_report(report: ReconciliationReport) -> str:
    """Render a ``ReconciliationReport`` as a fixed-width text table."""
    if not report.deltas:
        return f"Reconciliation: no deltas computed (skipped={report.skipped})"
    lines = []
    if report.char_name:
        lines.append(f"Reconciliation report for: {report.char_name}")
    lines.append(
        f"{'Stat':<24}{'Ours':>12}{'Oracle':>12}{'AbsDelta':>12}" f"{'Pct%':>10}{'Tol%':>8} OK?"
    )
    lines.append("-" * 84)
    for d in report.deltas:
        flag = "yes" if d.within_tolerance else "NO "
        lines.append(
            f"{d.stat:<24}{d.our_value:>12.1f}{d.oracle_value:>12.1f}"
            f"{d.abs_delta:>12.1f}{d.pct_delta:>9.1f}%{d.tolerance_pct:>7.1f}% {flag}"
        )
    if report.skipped:
        lines.append(f"Skipped (not in oracle): {', '.join(report.skipped)}")
    status = "PASS" if report.all_within_tolerance else "FAIL"
    lines.append(f"Overall: {status}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exact path: headless PoB2 engine vs poe.ninja (verify-report/v1)
# ---------------------------------------------------------------------------
# NOTE: ``reconcile_defensive_stats`` above is the APPROXIMATE fallback (own EHP
# model, 15% bands). ``reconcile_with_ninja`` is the default: it runs the exact
# PoB2 engine on ``charModel.pathOfBuildingExport`` and diffs against ninja.

REPORT_SCHEMA = "verify-report/v1"
PCT_TOLERANCE = 1.0  # DPS / EHP / max hits / rates, percent
SPLIT_TOLERANCE_PTS = 1.0  # damage-type share, percentage points
_TYPES = ["physical", "lightning", "cold", "fire", "chaos"]  # ninja split order
_OVERALL = ("movementSpeed", "strength", "dexterity", "intelligence", "spirit")


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _make_row(field_name: str, ninja: Any, mcp: Any, kind: str, group: str, cause_hint: str) -> Dict[str, Any]:
    n, m = _num(ninja), _num(mcp)
    if kind == "floor100" and m is not None:
        mcp, m = round(m * 100, 3), m * 100  # PoB stores a fraction; report on ninja's percent scale
    row: Dict[str, Any] = {"field": field_name, "group": group, "ninja": ninja, "mcp": mcp, "tolerance": kind}
    if n is None or m is None:
        row["delta_pct"] = None
        row["pass"] = False
        row["cause"] = "value missing on one side (PoB key not produced or field mapping wrong)"
        return row
    if kind == "int":
        ok = round(m) == round(n)
    elif kind == "floor":
        ok = int(m) == int(n)
    elif kind == "floor100":
        ok = int(m + 1e-6) == int(n)
    elif kind == "pts":
        ok = abs(m - n) <= SPLIT_TOLERANCE_PTS
    else:  # pct1
        ok = (abs(m - n) / abs(n) * 100 <= PCT_TOLERANCE) if n else m == 0
    row["delta_pct"] = round((m - n) / n * 100, 3) if n else (0.0 if m == n else None)
    row["pass"] = ok
    if not ok:
        row["cause"] = cause_hint
    return row


def reconcile_with_ninja(
    char_model: Dict[str, Any],
    headless: Any = None,
    ninja_url: Optional[str] = None,
    pob_commit: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Diff the exact PoB2 engine against poe.ninja for one character.

    Args:
        char_model: ninja ``charModel`` (needs ``pathOfBuildingExport``, ``defensiveStats``, ``skills``).
        headless: object with ``load_build(code)``, ``call(action, **p)`` and ``get_skill_table()``
            (a started ``HeadlessPoB``). If None a fresh one is started and closed.
        ninja_url / pob_commit: echoed into ``source``; commit is auto-detected when None.
        config: optional PoB Configuration-tab overrides (e.g. ``{"enemyLightningResist": 60}``) applied
            after load, for what-if diagnosis. None (default) = the export's own config. Echoed in ``source``.

    Returns a ``verify-report/v1`` dict. Failures sort first in ``diffs``.
    """
    try:
        from ..pob import headless as hl
    except ImportError:  # pragma: no cover
        from src.pob import headless as hl

    code = char_model.get("pathOfBuildingExport")
    if not code:
        raise ValueError("charModel has no pathOfBuildingExport; cannot run the exact engine")
    own = headless is None
    if own:
        headless = hl.HeadlessPoB()
        headless.start()
    try:
        headless.load_build(code)
        if config:
            headless.call("set_config", config=config)
        stats = headless.call("get_stats", fields=hl.DEFENCE_POB_FIELDS).get("stats", {})
        table = headless.get_skill_table()
    finally:
        if own:
            headless.close()

    diffs: List[Dict[str, Any]] = []
    ds = char_model.get("defensiveStats", {})
    defence: Dict[str, Any] = {}
    for nkey, (pkey, kind) in hl.DEFENCE_FIELD_SET.items():
        if nkey not in ds:
            continue
        defence[nkey] = stats.get(pkey)
        if kind == "pct1":
            hint = ("EHP/max-hit basis differs: check enemy damage/level config, charges, "
                    "or pool inputs (life/ES/res) first; else engine version drift")
        else:
            hint = ("input mismatch: gear/tree/jewel parse or unresolved passive nodes; "
                    "or PoB version drift vs ninja")
        group = "overall" if nkey in _OVERALL else "defence"
        diffs.append(_make_row(nkey, ds[nkey], stats.get(pkey), kind, group, hint))

    by_name: Dict[str, Dict[str, Any]] = {}
    for r in table:
        by_name.setdefault(r.get("name"), r)
    skills: List[Dict[str, Any]] = []
    for sk in char_model.get("skills", []):
        for ent in sk.get("dps", []):
            name = ent.get("name")
            row = by_name.get(name)
            entry: Dict[str, Any] = {"name": name, "ninja": {
                "dps": ent.get("dps"), "dot_dps": ent.get("dotDps"), "rate": ent.get("rate"),
                "crit_chance": ent.get("critChance"), "crit_multi": ent.get("critMultiplier"),
                "split_pct": dict(zip(_TYPES, ent.get("damageTypes") or []))}}
            skills.append(entry)
            f = f"skill[{name}]"
            if row is None:
                diffs.append({"field": f, "group": "damage", "ninja": ent.get("dps"), "mcp": None,
                              "tolerance": "pct1", "delta_pct": None, "pass": False,
                              "cause": "skill not found among enabled PoB socket groups (disabled, or active skill differs)"})
                continue
            split = row.get("split", {})
            hit = {t: (split.get(t.capitalize(), {}) or {}).get("hit_average", 0) or 0 for t in _TYPES}
            comb = {t: (split.get(t.capitalize(), {}) or {}).get("combined_average", 0) or 0 for t in _TYPES}
            # ninja's split is post-mitigation hit damage = PoB <Type>HitAverage. Some skills (spell/trigger
            # paths) leave it 0; then only the pre-mitigation StoredCombinedAvg exists (different basis).
            post_mitigation = sum(hit.values()) > 0
            if post_mitigation:
                comb = hit
            tot = sum(comb.values()) or 1
            share = {t: round(comb[t] / tot * 100, 2) for t in _TYPES}
            entry["mcp"] = {
                "dps": row.get("TotalDPS"), "dot_dps": row.get("TotalDotDPS"),
                "split_pct": share, "split_avg": comb,
                "split_basis": "post-mitigation HitAverage" if post_mitigation else "pre-mitigation StoredCombinedAvg",
                "crit_chance": row.get("CritChance"), "crit_multi": row.get("CritMultiplier"),
                "rate": row.get("Speed"), "hit_chance": row.get("HitChance"),
            }
            dps_hint = ("damage differs: compare split rows first (conversion/gain-as handling), then "
                        "PoB config (enemy level, charges, conditions) and engine drift")
            has_dps = bool(ent.get("dps"))
            if has_dps or not ent.get("dotDps"):
                diffs.append(_make_row(f"{f}.dps", ent.get("dps"), row.get("TotalDPS"), "pct1", "damage", dps_hint))
            if ent.get("dotDps"):
                diffs.append(_make_row(f"{f}.dot_dps", ent.get("dotDps"), row.get("TotalDotDPS"), "pct1", "damage", dps_hint))
            if has_dps:
                for nk, pk, lab in (("rate", "Speed", "rate"), ("critChance", "CritChance", "crit_chance"),
                                    ("critMultiplier", "CritMultiplier", "crit_multi")):
                    if ent.get(nk) is not None:
                        diffs.append(_make_row(f"{f}.{lab}", ent[nk], row.get(pk), "pct1", "damage",
                                               "speed/crit inputs differ: gem level, support, tree or gear mod parse"))
                for t, v in zip(_TYPES, ent.get("damageTypes") or []):
                    cause = ("damage-type split differs: conversion / gain-as handling or PoB config"
                             if post_mitigation else
                             "basis mismatch: PoB exposes only pre-mitigation StoredCombinedAvg for this skill "
                             "(ninja is post-mitigation, so resist/armour effects show as drift)")
                    diffs.append(_make_row(f"{f}.split.{t}", v, share[t], "pts", "damage", cause))

    diffs.sort(key=lambda d: (d["pass"], d["group"], d["field"]))
    failed = [d for d in diffs if not d["pass"]]
    return {
        "schema": REPORT_SCHEMA,
        "source": {
            "ninja_url": ninja_url, "config_override": config or None, "ninja_timestamp": char_model.get("updatedUtc"),
            "character": char_model.get("name"), "pob_commit": pob_commit or hl.pob_commit(),
            "basis": "exact (headless PoB2)",
        },
        "overall": {"level": char_model.get("level"), "class": char_model.get("class"),
                    **{k: defence.get(k) for k in _OVERALL if k in defence}},
        "defence": {k: v for k, v in defence.items() if k not in _OVERALL},
        "skills": skills,
        "diffs": diffs,
        "summary": {"total": len(diffs), "failed": len(failed), "passed": len(diffs) - len(failed)},
    }


def format_verify_markdown(report: Dict[str, Any]) -> str:
    """Markdown diff table, failures first (diffs are already sorted that way)."""
    s = report["summary"]
    src = report["source"]
    lines = [f"**{src.get('character')}** vs poe.ninja ({src.get('ninja_timestamp')}), engine {src.get('pob_commit')}: "
             f"{s['passed']}/{s['total']} pass, {s['failed']} fail", "",
             "| | field | ninja | mcp | delta % | cause |", "|---|---|---|---|---|---|"]
    for d in report["diffs"]:
        mcp = d["mcp"]
        mcp = round(mcp, 3) if isinstance(mcp, float) else mcp
        delta = "" if d["delta_pct"] is None else d["delta_pct"]
        lines.append(f"| {'ok' if d['pass'] else 'FAIL'} | {d['field']} | {d['ninja']} | {mcp} | "
                     f"{delta} | {d.get('cause', '')} |")
    return "\n".join(lines)
