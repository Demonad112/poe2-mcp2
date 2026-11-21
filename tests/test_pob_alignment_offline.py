"""Engine-free regressions vs PoB2 (hard-coded values from Data/Misc.lua, Data.lua, CalcOffence.lua)."""
import asyncio
import json
from unittest import mock

import pytest

from src.calculator.spell_dps_calculator import (
    CharacterModifiers, EnemyStats, SERVER_TICK_RATE, SpellDPSCalculator, SpellStats)


def _spell():
    return SpellStats(name="t", base_damage_min=100, base_damage_max=100, base_crit_chance=0,
                      base_cast_time=1.0, damage_types=["fire"], damage_effectiveness=1.0)


def test_crit_multiplier_base_inc_more_matches_pob():
    # CalcOffence.lua: extra = base/100 * (1+inc/100) * more ; mult = 1 + extra
    assert SpellDPSCalculator()._calculate_crit_multiplier(100, 50, 20) == pytest.approx(1 + 1.0 * 1.5 * 1.2)
    assert SpellDPSCalculator()._calculate_crit_multiplier(340, 0, 0) == pytest.approx(4.4)  # Yykiuy CritMultiplier 4.4


def test_server_tick_rate_matches_pob_and_caps_speed():
    assert SERVER_TICK_RATE == pytest.approx(1 / 0.033)  # Modules/Data.lua ServerTickRate
    assert SpellDPSCalculator()._calculate_cast_speed(1.0, 5000) == pytest.approx(30.30303, rel=1e-5)
    assert SpellDPSCalculator()._calculate_cast_speed(1.0, 0) == 1.0  # uncapped below the tick


def test_shock_magnitude_default_20_and_scales():
    # Data/Misc.lua BaseShockMagnitude = 20, max 100
    sp, e0 = SpellDPSCalculator(), EnemyStats()
    base = sp.calculate_dps(_spell(), CharacterModifiers(), e0)["average_hit"]
    d = lambda m: sp.calculate_dps(_spell(), CharacterModifiers(), EnemyStats(is_shocked=True, shock_magnitude=m))["average_hit"]
    assert d(20) / base == pytest.approx(1.2)
    assert d(50) / base == pytest.approx(1.5)   # PoB engine ratio with conditionShockEffect=50: 1.5
    assert d(500) / base == pytest.approx(2.0)  # clamped to MaximumShock 100


def test_ehp_uses_real_resist_max_and_pen_from_config():
    from src.calculator.ehp_calculator import EHPCalculator, DefensiveStats, ThreatProfile, DamageType
    # Yykiuy PoB: Cold res 80 (max 80) => cold max hit 19126; pen from config (3)
    ds = DefensiveStats(life=1477, energy_shield=0, armor=0, evasion=0, cold_res=80, cold_res_max=80)
    r = EHPCalculator().calculate_ehp(ds, DamageType.COLD, ThreatProfile(expected_hit_size=5000, enemy_cold_pen=3))
    assert r.effective_hp == pytest.approx(1477 / (1 - 0.77), rel=1e-3)


def test_dps_tool_routes_to_headless_when_ready_and_labels_fallback(tmp_path):
    from src.mcp_server import PoE2BuildOptimizerMCP as S
    f = tmp_path / "b.txt"; f.write_text("x")
    srv = S.__new__(S)
    with mock.patch("src.pob.headless.find_environment", return_value={"ready": True}), \
         mock.patch("src.pob.headless.calc", return_value={"stats": {"CombinedDPS": 251182.44}}) as c:
        out = asyncio.run(srv._handle_calculate_character_dps({"pob_file_path": str(f)}))
    j = json.loads(out[0].text)
    assert j["source"] == "headless_pob" and j["stats"]["CombinedDPS"] == 251182.44 and c.called

    async def fake_py(args):
        return [mock.Mock(text="{}")]
    with mock.patch("src.pob.headless.find_environment", return_value={"ready": False}):
        out = asyncio.run(srv._route_headless_first({"pob_file_path": str(f)}, [], fake_py))
    assert out[0].text.startswith("[approximate")


def test_character_data_export_routes_to_headless_else_labelled_fallback():
    from src.mcp_server import PoE2BuildOptimizerMCP as S
    srv = S.__new__(S)
    for args in ({"character_data": {"pathOfBuildingExport": "CODE"}},
                 {"char_model": {"charModel": {"pathOfBuildingExport": "CODE"}}}):
        with mock.patch("src.pob.headless.find_environment", return_value={"ready": True}), \
             mock.patch("src.pob.headless.calc", return_value={"stats": {"TotalDPS": 1.0}}) as c:
            out = asyncio.run(srv._handle_calculate_character_dps(dict(args)))
        j = json.loads(out[0].text)
        assert j["source"] == "headless_pob" and j["exact"] is True
        assert c.call_args[0][0] == "CODE"

    async def fake_py(a):
        return [mock.Mock(text="{}")]
    with mock.patch("src.pob.headless.find_environment", return_value={"ready": True}), \
         mock.patch("src.pob.headless.calc") as c:
        out = asyncio.run(srv._route_headless_first({"character_data": {"life": 1}}, [], fake_py))
    assert out[0].text.startswith("[approximate") and not c.called


def test_runic_ward_is_layered_into_hit_pool_like_pob():
    """PoB TotalHitPool = life + ES + ward (audited: 1494 + 2621 + 423 = 4538); chaos halves ES only."""
    from src.calculator.ehp_calculator import EHPCalculator, DefensiveStats, ThreatProfile, DamageType
    base = dict(life=1494, energy_shield=2621)
    c = EHPCalculator()
    tp = ThreatProfile(expected_hit_size=5000)
    a = c.calculate_ehp(DefensiveStats(**base, runic_ward=423), DamageType.PHYSICAL, tp).effective_hp
    b = c.calculate_ehp(DefensiveStats(**base), DamageType.PHYSICAL, tp).effective_hp
    assert a - b == pytest.approx(423, rel=1e-3)
    ch = c.calculate_ehp(DefensiveStats(**base, runic_ward=423, chaos_res=0), DamageType.CHAOS, tp).effective_hp
    ch0 = c.calculate_ehp(DefensiveStats(**base, chaos_res=0), DamageType.CHAOS, tp).effective_hp
    assert ch - ch0 == pytest.approx(423, rel=1e-3)


def test_max_res_derived_from_raw_modsum_not_from_engine_output():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("audit", pathlib.Path(__file__).parents[1] / "scripts/audit_python_vs_headless.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert m.python_max_res(75) == 75 and m.python_max_res(80) == 80 and m.python_max_res(120) == 90
