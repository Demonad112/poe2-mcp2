"""Offline suggestions from a parsed poe.ninja charModel.

Pure function, no network, no PoB engine. Baseline is ninja's own numbers
(`defensiveStats`, `skills[].dps[]`), which verify_character shows the
PoB2 engine reproduces exactly for defences. Output is a ranked list.
"""
from __future__ import annotations

from typing import Any, Dict, List

_RES = ("fire", "cold", "lightning", "chaos")
_HIT = ("physical", "fire", "cold", "lightning", "chaos")
_ORDER = ("physical", "lightning", "cold", "fire", "chaos")  # ninja damageTypes order


def _s(area: str, sev: int, finding: str, evidence: str, action: str) -> Dict[str, Any]:
    return {"severity": sev, "area": area, "finding": finding, "evidence": evidence, "action": action}


def suggest_from_charmodel(cm: Dict[str, Any]) -> Dict[str, Any]:
    ds = cm.get("defensiveStats") or {}
    out: List[Dict[str, Any]] = []

    # 1. Resistances: shortfall first, then wasted overcap.
    short, over = [], []
    for t in _RES:
        v, mx, oc = ds.get(f"{t}Resistance"), ds.get(f"{t}ResistanceMax"), ds.get(f"{t}ResistanceOverCap", 0) or 0
        if v is None or mx is None:
            continue
        if v < mx:
            short.append((t, mx - v, v, mx))
        if oc >= 20:
            over.append((t, oc))
    for t, gap, v, mx in short:
        out.append(_s("defence", 3 if gap >= 10 else 2, f"{t} resistance {gap}% under cap",
                      f"{v}/{mx}", f"Add {gap}% {t} resistance."))
    if over:
        txt = ", ".join(f"{t} +{oc}" for t, oc in over)
        out.append(_s("defence", 2, "Large resistance overcap is wasted", txt,
                      "Swap overcapped resist affixes for the shortfall types or for life/ES."))

    # 2. Weakest hit vs the rest.
    hits = {t: ds.get(f"{t}MaximumHitTaken") for t in _HIT if ds.get(f"{t}MaximumHitTaken")}
    if hits:
        lo = min(hits, key=hits.get)
        hi = max(hits, key=hits.get)
        ratio = hits[hi] / hits[lo]
        ehp = ds.get("effectiveHealthPool")
        if ratio >= 2:
            out.append(_s("defence", 3 if ratio >= 3 else 2, f"{lo} is the weak point: {hits[lo]:,} max hit",
                          f"{hi} {hits[hi]:,} ({ratio:.2f}x higher); EHP {ehp:,}" if ehp else f"{ratio:.2f}x spread",
                          f"Raise {lo} mitigation (armour/{lo} reduction/more life or ES) before more of anything else."))
        if ehp and hits[lo] and ehp / hits[lo] >= 3:
            out.append(_s("defence", 2, "EHP overstates real survivability",
                          f"EHP {ehp:,} vs smallest killing hit {hits[lo]:,} ({ehp / hits[lo]:.2f}x)",
                          "Judge defence by the smallest max hit, not EHP."))

    # 3. Damage: main skill, split, crit.
    rows = [(sk.get("name") or e.get("name"), e) for sk in cm.get("skills", []) for e in sk.get("dps", [])]
    rows = [(n, e) for n, e in rows if e.get("dps")]
    rows.sort(key=lambda x: -x[1]["dps"])
    if rows:
        n, e = rows[0]
        dt = e.get("damageTypes") or []
        if len(dt) >= 5 and sum(dt) > 0:
            split = {t: dt[i] for i, t in enumerate(_ORDER)}
            top = max(split, key=split.get)
            out.append(_s("damage", 1, f"{n} is the main skill: {e['dps']:,} DPS",
                          "split " + ", ".join(f"{t} {v}%" for t, v in sorted(split.items(), key=lambda x: -x[1]) if v),
                          f"Prefer {top} scaling; penetration/exposure for {top} beats other types."))
        cc, cm_ = e.get("critChance"), e.get("critMultiplier")
        if cc is not None and cc < 50:
            out.append(_s("damage", 2, f"{n} crit chance only {cc:.1f}%", f"multiplier {cm_}x",
                          "Raise crit chance before crit multiplier."))
        if len(rows) > 1 and rows[1][1]["dps"] >= 0.5 * e["dps"]:
            out.append(_s("damage", 1, f"{rows[1][0]} is within 2x of the main skill",
                          f"{rows[1][1]['dps']:,} vs {e['dps']:,}", "Check whether the main-skill choice is right."))

    out.sort(key=lambda r: -r["severity"])
    return {"schema": "ninja-suggestions/v1", "offline": True, "character": cm.get("name"),
            "level": cm.get("level"), "class": cm.get("class"), "suggestions": out}


def format_suggestions_markdown(r: Dict[str, Any]) -> str:
    lines = [f"# Suggestions: {r.get('character')} (L{r.get('level')} {r.get('class')}), offline from ninja data", "",
             "| # | Area | Finding | Evidence | Action |", "|---|---|---|---|---|"]
    for i, s in enumerate(r["suggestions"], 1):
        lines.append(f"| {i} | {s['area']} | {s['finding']} | {s['evidence']} | {s['action']} |")
    return "\n".join(lines)
