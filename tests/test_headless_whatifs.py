"""First-class headless what-if args, bridge version in status + cache key, headless-first validate routing."""

import asyncio
import json
from pathlib import Path

import pytest

from src.mcp_server import PoE2BuildOptimizerMCP as M
from src.pob import cache, headless


def test_build_config_maps_whatifs():
    cfg = headless.build_config(
        {
            "enemy_level": 85,
            "shock_effect": 30,
            "fire_exposure": True,
            "power_charges": 3,
            "frenzy_charges": 0,
        }
    )
    assert cfg == {
        "enemyLevel": 85,
        "conditionEnemyShocked": True,
        "conditionShockEffect": 30,
        "conditionEnemyFireExposure": True,
        "usePowerCharges": True,
        "overridePowerCharges": 3,
        "useFrenzyCharges": False,
    }


def test_build_config_raw_config_wins_and_empty_is_none():
    assert headless.build_config({}) is None
    assert headless.build_config({"enemy_level": 80, "config": {"enemyLevel": 82}}) == {
        "enemyLevel": 82
    }


def test_bridge_version_in_status_and_cache_key(monkeypatch):
    assert headless.bridge_version() not in ("", "unknown")
    assert headless.find_environment()["bridge_version"] == headless.bridge_version()
    k1 = cache.cache_key("<x/>", commit="abc")
    monkeypatch.setattr(headless, "bridge_version", lambda: "999")
    assert cache.cache_key("<x/>", commit="abc") != k1


def test_whatif_props_exposed_on_calc_and_validate_schemas():
    props = M._whatif_schema_props()
    assert {"enemy_level", "enemy_shocked", "shock_effect", "power_charges"} <= set(props)
    src = open("src/mcp_server.py", encoding="utf-8").read()
    assert src.count("_whatif_schema_props()") >= 4


def test_validate_build_constraints_fallback_is_labelled_approximate():
    out = asyncio.run(
        M._handle_validate_build_constraints(
            M.__new__(M),
            {
                "character_data": {
                    "fire_resistance": 75,
                    "cold_resistance": 75,
                    "lightning_resistance": 75,
                }
            },
        )
    )
    text = out[0].text
    assert text.startswith("[approximate")
    assert "Build Constraint Validation" in text


FIXTURE = Path(__file__).parent / "fixtures" / "builds" / "synthetic_spell_fireball.json"


@pytest.mark.skipif(not headless.find_environment()["ready"], reason="headless engine not ready")
def test_engine_whatifs_and_validate_route(tmp_path):
    xml = json.loads(FIXTURE.read_text())["pob_xml"]
    f = tmp_path / "b.txt"
    f.write_text(xml)
    base = headless.calc(xml, None, ["Life"])["stats"]["Life"]
    assert base > 0
    server = M.__new__(M)
    out = asyncio.run(
        server._handle_headless_pob_calc(
            {"pob_file_path": str(f), "enemy_level": 85, "fields": ["TotalDPS"]}
        )
    )
    assert json.loads(out[0].text)["stats"]["TotalDPS"] > 0
    val = asyncio.run(server._handle_validate_build_constraints({"pob_file_path": str(f)}))
    assert val[0].text.startswith("[PoB-exact")
