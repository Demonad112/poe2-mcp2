"""Regression tests: Python calculators vs headless PoB2 reference values (hard-coded; no engine needed).
Reference: Yykiuy fixture via scripts/audit_python_vs_headless.py."""

import pytest

from src.calculator.ehp_calculator import DamageType, DefensiveStats, EHPCalculator, ThreatProfile
from src.calculator.spell_dps_calculator import (
    CharacterModifiers,
    EnemyStats,
    SpellDPSCalculator,
    SpellStats,
)


def _max_hit(dt, res, res_max, pen=3.0):
    ds = DefensiveStats(
        life=1477,
        energy_shield=2922,
        armor=0,
        fire_res=res,
        cold_res=res,
        lightning_res=res,
        chaos_res=res,
        fire_res_max=res_max,
        cold_res_max=res_max,
        lightning_res_max=res_max,
        chaos_res_max=res_max,
    )
    return (
        EHPCalculator()
        .calculate_ehp(
            ds,
            dt,
            ThreatProfile(
                expected_hit_size=5000,
                enemy_fire_pen=pen,
                enemy_cold_pen=pen,
                enemy_lightning_pen=pen,
            ),
        )
        .effective_hp
    )


@pytest.mark.parametrize(
    "dt,res,rmax,expected",
    [
        (DamageType.FIRE, 75, 75, 15711),  # PoB FireMaximumHitTaken
        (DamageType.COLD, 80, 80, 19126),  # 80% max res (item 2) + pen 3 (item 3)
        (DamageType.LIGHTNING, 74, 75, 15169),
    ],
)
def test_max_hit_matches_pob(dt, res, rmax, expected):
    assert _max_hit(dt, res, rmax) == pytest.approx(expected, abs=1)


def test_res_capped_at_max():
    assert _max_hit(DamageType.COLD, 139, 80) == pytest.approx(19126, abs=1)


def _spell(res=0, expo=0, **mods):
    base = SpellStats(
        name="t",
        base_damage_min=100,
        base_damage_max=100,
        base_crit_chance=5,
        base_cast_time=1.0,
        damage_types=["fire"],
        damage_effectiveness=1.0,
    )
    return SpellDPSCalculator().calculate_dps(
        base, CharacterModifiers(**mods), EnemyStats(fire_resistance=res, fire_exposure=expo)
    )


def test_negative_enemy_res_not_floored():
    # PoB mult = 1 - (-30)/100 = 1.3 on a 100 hit; crit adds 5% * 2x -> compare ratio vs res 0
    assert _spell(res=-30)["average_hit"] / _spell(res=0)["average_hit"] == pytest.approx(
        1.3, abs=0.001
    )


def test_crit_chance_scales_multiplicatively():
    assert _spell(increased_crit_chance=200)["crit_chance"] == pytest.approx(15.0)  # 5*(1+2)
    assert _spell(increased_crit_chance=200, more_crit_chance=100)["crit_chance"] == pytest.approx(
        30.0
    )


def test_crit_multiplier_more():
    c = SpellDPSCalculator()
    assert c._calculate_crit_multiplier(100, 50, 20) == pytest.approx(1 + 1.0 * 1.5 * 1.2)
    assert c._calculate_crit_multiplier(100, 50) == pytest.approx(2.5)
