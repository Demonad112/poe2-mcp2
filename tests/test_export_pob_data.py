"""Schema + spot-check tests for the committed data/pob/*.json (scripts/export_pob_data.py).

These never need the PoB2 checkout or lupa: they validate the committed JSON. The staleness test at
the bottom runs ``--check`` only when both are available.
"""

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
POB_DIR = ROOT / "data" / "pob"

_spec = importlib.util.spec_from_file_location(
    "export_pob_data", ROOT / "scripts/export_pob_data.py"
)
assert _spec is not None and _spec.loader is not None
exp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exp)


def load(name: str) -> Dict[str, Any]:
    return json.loads((POB_DIR / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def constants() -> Dict[str, Any]:
    return load("constants.json")


@pytest.fixture(scope="module")
def bosses() -> Dict[str, Any]:
    return load("bosses.json")


@pytest.fixture(scope="module")
def config() -> Dict[str, Any]:
    return load("config_options.json")


# ---- all files ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", exp.OUTPUT_FILES)
def test_meta_header_and_pin(name: str) -> None:
    data = load(name)
    m = data["_meta"]
    assert m["generator"] == "scripts/export_pob_data.py"
    assert m["schema"] == exp.SCHEMA_VERSION
    assert re.fullmatch(r"[0-9a-f]{40}", m["pob_commit"])
    assert m["pob_commit"] == exp.pob_pin(), "committed JSON was exported from a different PoB2 pin"
    assert m["source"]


@pytest.mark.parametrize("name", exp.OUTPUT_FILES)
def test_files_are_canonical_text(name: str) -> None:
    """Committed bytes equal the exporter's own serialisation of their parsed content."""
    text = (POB_DIR / name).read_text(encoding="utf-8")
    assert text.endswith("}\n") and "\r" not in text
    assert exp.fmt(json.loads(text), exp.EXPAND[name]) + "\n" == text


def test_fmt_sorted_and_compact() -> None:
    assert exp.fmt({"b": 1, "a": [1, 2]}, 1) == '{\n "a": [1,2],\n "b": 1\n}'
    assert exp.fmt({"b": {"y": 1, "x": 2}}, 0) == '{"b":{"x":2,"y":1}}'


# ---- constants ----------------------------------------------------------------------------


def test_constants_tables(constants: Dict[str, Any]) -> None:
    for t in (
        "monsterDamageTable",
        "monsterArmourTable",
        "monsterEvasionTable",
        "monsterAccuracyTable",
    ):
        arr = constants[t]
        assert isinstance(arr, list) and len(arr) == 100
        assert all(isinstance(x, (int, float)) and x > 0 for x in arr)
        assert arr == sorted(arr), "%s should be non-decreasing by level" % t
    assert constants["characterConstants"] and constants["gameConstants"]
    assert constants["gameConstants"]["MonsterArmourBase"] == 2
    assert constants["misc"]["MaxEnemyLevel"] == 85


def test_constants_known_values(constants: Dict[str, Any]) -> None:
    # list index = level - 1
    assert constants["monsterArmourTable"][0] == 3
    assert constants["monsterArmourTable"][84] == 6355
    assert constants["monsterAccuracyTable"][99] == 4011
    assert constants["monsterDamageTable"][0] == pytest.approx(9.16, abs=1e-6)


# ---- bosses -------------------------------------------------------------------------------


def test_boss_stats_recomputed(bosses: Dict[str, Any]) -> None:
    table = bosses["bosses"]
    assert len(table) == 22 and sum(1 for b in table.values() if b["isUber"]) == 7
    for b in table.values():
        assert set(b) == {"armourMult", "evasionMult", "isUber"}
    s = bosses["bossStats"]
    assert s == exp.compute_boss_stats(table)
    assert s["PinnacleArmourMean"] == 150.0
    assert s["UberArmourMean"] == 125.0
    assert s["PinnacleEvasionMean"] == pytest.approx(100 + 274 / 11)
    assert s["UberEvasionMean"] == pytest.approx(100 + 116 / 7)


def test_pinnacle_armour_spot_check(bosses: Dict[str, Any], constants: Dict[str, Any]) -> None:
    """ConfigOptions.lua: enemyArmour = round(ARM[L] * (PinnacleArmourMean / 100)) for Pinnacle."""
    mean = bosses["bossStats"]["PinnacleArmourMean"]
    arm = constants["monsterArmourTable"]
    assert arm[85 - 1] * mean / 100 == pytest.approx(9532.5)
    assert arm[1 - 1] * mean / 100 == pytest.approx(4.5)


def test_boss_multipliers_and_skills(bosses: Dict[str, Any]) -> None:
    m = bosses["bossMultipliers"]
    assert m["stdBossDPSMult"] == pytest.approx(4 / 4.40)
    assert m["pinnacleBossDPSMult"] == pytest.approx(8 / 4.40)
    assert m["pinnacleBossPen"] == pytest.approx(3.0)
    assert m["uberBossDPSMult"] == pytest.approx(10 / 4.25)
    assert m["uberBossPen"] == pytest.approx(8.0)
    skills = bosses["bossSkills"]
    listed = {e["val"] for e in bosses["bossSkillsList"]} - {"None"}
    assert listed == set(skills)
    for name, sk in skills.items():
        assert "DamageType" in sk and "DamageMultipliers" in sk, name


# ---- bases --------------------------------------------------------------------------------


def test_bases_schema() -> None:
    d = load("bases.json")
    bases = d["bases"]
    assert len(bases) > 1000
    assert sum(len(v) for v in d["files"].values()) == len(bases)
    for name, b in bases.items():
        assert isinstance(b["type"], str) and isinstance(b["tags"], dict), name
        assert b["source_file"] in d["files"] and name in d["files"][b["source_file"]]
        assert isinstance(b["implicitModTypes"], list)
        if "weapon" in b:
            w = b["weapon"]
            assert w.get("PhysicalMin", 0) <= w.get("PhysicalMax", 0), name
            assert w["AttackRateBase"] > 0, name
    assert bases["Rusted Cuirass"]["armour"]["Armour"] == 45
    assert any("weapon" in b for b in bases.values())
    assert any("armour" in b for b in bases.values())


# ---- gems ---------------------------------------------------------------------------------


def test_gems_schema() -> None:
    d = load("gems.json")
    gems = d["gems"]
    assert len(gems) > 900
    for key, g in gems.items():
        assert key == "%s|%s" % (g["gameId"], g["variantId"])
        assert g["is_support"] == (g["gemType"] == "Support" or bool(g["tags"].get("support")))
        assert g["grantedEffectId"]
    assert d["supports"] == sorted(k for k, g in gems.items() if g["is_support"])
    assert 0 < len(d["supports"]) < len(gems)
    assert "Metadata/Items/Gems/SupportGemFireInfusion|AddedFireDamageSupport" in d["supports"]


# ---- enums --------------------------------------------------------------------------------


def test_enums() -> None:
    e = load("enums.json")
    mf, kf, st = e["ModFlag"], e["KeywordFlag"], e["SkillType"]
    assert mf["Attack"] == 1 and mf["Spell"] == 2 and mf["Weapon2H"] == 0x800000000
    assert kf["Aura"] == 1 and kf["MatchAll"] == 0x40000000
    assert mf["SourceMask"] == mf["Area"] | mf["Projectile"]
    singles = {k: v for k, v in mf.items() if k not in ("SourceMask", "WeaponMask")}
    assert all(v & (v - 1) == 0 for v in singles.values()), "ModFlag bits must be single bits"
    assert len(set(singles.values())) == len(singles)
    assert len(set(st.values())) == len(st) and st["Attack"] == 1 and st["Spell"] == 2


# ---- modcache -----------------------------------------------------------------------------


def test_modcache_schema() -> None:
    entries = load("modcache.json")["entries"]
    assert len(entries) > 9000
    for text, e in entries.items():
        assert set(e) == {"mods", "rest"}, text
        assert e["mods"] is None or isinstance(e["mods"], list)
        assert e["rest"] is None or isinstance(e["rest"], str)
        for m in e["mods"] or []:
            assert {"name", "type", "value", "flags", "keywordFlags", "tags"} <= set(m), text
            assert isinstance(m["tags"], list)
    crit = entries["+0.08% to Thorns Critical Hit Chance"]["mods"]
    assert crit == [
        {
            "flags": 32,
            "keywordFlags": 0,
            "name": "CritChance",
            "tags": [],
            "type": "BASE",
            "value": 0.08,
        }
    ]
    poison = entries["Any number of Poisons from this Weapon can affect a target at the same time"]
    assert {"$inf": 1} in [m["value"] for m in poison["mods"]]


# ---- config options -----------------------------------------------------------------------


def _walk(x: Any):  # type: ignore[no-untyped-def]
    yield x
    if isinstance(x, dict):
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def test_config_rows_schema(config: Dict[str, Any]) -> None:
    rows = config["rows"]
    assert len(rows) > 600
    assert [r["index"] for r in rows] == list(range(len(rows)))
    assert config["probe_values"] == list(exp.NUMERIC_PROBES)
    for r in rows:
        if r["var"] is None:  # header/label-only rows (e.g. "Arc:")
            assert r["type"] is None and not r.get("has_apply")
            continue
        assert r["type"] in {"check", "count", "countAllowZero", "integer", "float", "list", "text"}
        if r["type"] == "list":
            assert r["list"], r["var"]
        if r.get("reads_input"):
            assert not r.get("has_apply") and "mods" not in r and "by_value" not in r
        else:
            assert r["has_apply"] is True and isinstance(r["code"], bool)
            if r["code"]:
                assert r["code_reasons"] and "mods" not in r
            else:
                assert "mods" in r or "by_value" in r
                assert "code_reasons" not in r


def test_config_templates(config: Dict[str, Any]) -> None:
    by_var: Dict[str, Any] = {}
    for r in config["rows"]:
        by_var.setdefault(r["var"], []).append(r)
    r = by_var["detonateDeadCorpseLife"][0]
    (op,) = r["mods"]["player"]
    assert op["op"] == "add"
    assert op["mod"]["name"] == "SkillData" and op["mod"]["type"] == "LIST"
    assert op["mod"]["value"] == {"key": "corpseLife", "value": "$val"}
    assert r["visibility"] == {"ifSkillData": "explodeCorpse"}
    # clamp / conditional-on-val rows are code, not templates
    assert by_var["multiplierCurrentManaPercentage"][0]["code"] is True
    assert by_var["conditionStationary"][0]["code"] is True
    # flat check rows are plain templates
    moving = by_var["conditionMoving"][0]["mods"]["player"][0]["mod"]
    assert (moving["name"], moving["type"], moving["value"]) == ("Condition:Moving", "FLAG", True)
    # no apply -> reads_input
    assert by_var["resistancePenalty"][0]["reads_input"] is True
    # "$val" / "$affine" markers only ever appear in non-code templates
    for row in config["rows"]:
        if row.get("code"):
            continue
        for node in _walk(row.get("mods", row.get("by_value"))):
            if isinstance(node, dict) and "$affine" in node:
                k, c = node["$affine"]
                assert isinstance(k, (int, float)) and isinstance(c, (int, float))


def test_config_duplicate_var(config: Dict[str, Any]) -> None:
    dup = config["duplicate_vars"]
    assert set(dup) == {"conditionEnemyExitedPresenceRecently"}
    i, j = dup["conditionEnemyExitedPresenceRecently"]
    assert config["by_var"]["conditionEnemyExitedPresenceRecently"] == [i, j]
    rows = config["rows"]
    assert rows[i]["visibility"]["ifEnemyCond"] == "ExitedPresenceRecently"
    assert rows[j]["visibility"]["ifEnemyCond"] == "EnteredPresenceRecently"
    names = [rows[k]["mods"]["enemy"][0]["mod"]["name"] for k in (i, j)]
    assert names == ["Condition:ExitedPresenceRecently", "Condition:EnteredPresenceRecently"]


def test_config_build_reading_rows_are_code(config: Dict[str, Any]) -> None:
    boss = next(r for r in config["rows"] if r["var"] == "enemyIsBoss")
    assert boss["code"] is True and "reads build state" in boss["code_reasons"]
    assert set(boss["by_value"]) == {json.dumps(it["val"]) for it in boss["list"]}


# ---- template_from_probes unit tests (no Lua) ---------------------------------------------


def _mod(value: Any) -> Dict[str, Any]:
    return {"player": [{"op": "add", "mod": {"name": "X", "value": value}}], "enemy": []}


def test_template_identity_and_affine() -> None:
    probes = exp.NUMERIC_PROBES
    t, why = exp.template_from_probes([(v, _mod(v)) for v in probes])
    assert why == "" and t["player"][0]["mod"]["value"] == "$val"
    t, _ = exp.template_from_probes([(v, _mod(-2 * v + 1)) for v in probes])
    assert t["player"][0]["mod"]["value"] == {"$affine": [-2, 1]}
    t, _ = exp.template_from_probes([(v, _mod(7)) for v in probes])
    assert t["player"][0]["mod"]["value"] == 7


@pytest.mark.parametrize(
    "fn",
    [lambda v: min(v, 100), lambda v: max(v, 0), lambda v: v * v, lambda v: round(v / 10)],
)
def test_template_rejects_nonlinear(fn: Any) -> None:
    t, why = exp.template_from_probes([(v, _mod(fn(v))) for v in exp.NUMERIC_PROBES])
    assert t is None and why


def test_template_rejects_shape_change() -> None:
    def out(v: int) -> Dict[str, Any]:
        o = _mod(v)
        if v > 0:
            o["player"].append({"op": "add", "mod": {"name": "Y", "value": True}})
        return o

    t, why = exp.template_from_probes([(v, out(v)) for v in exp.NUMERIC_PROBES])
    assert t is None and "shape" in why


# ---- staleness (needs lupa + the pinned PoB2 checkout) ------------------------------------


def test_committed_json_not_stale() -> None:
    pytest.importorskip("lupa")
    try:
        src = exp.find_pob_src()
    except FileNotFoundError:
        pytest.skip("PoB2 checkout not available")
    head = exp.checkout_commit(src)
    if head is not None and head != exp.pob_pin():
        pytest.skip("PoB2 checkout is not at the pin")
    assert exp.main(["--check", "--pob-src", str(src)]) == 0
