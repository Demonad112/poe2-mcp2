"""Regression tests for real defects surfaced by the mypy cleanup."""

import json

from src.analyzer.character_comparator import CharacterComparator
from src.data import game_data


def test_bad_per_skill_json_returns_none_instead_of_nameerror(tmp_path, monkeypatch):
    # `logger` was never defined in game_data; the except handler itself raised
    # NameError on corrupt JSON instead of returning None.
    bad = tmp_path / "per_skill.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(game_data, "PER_SKILL_STAT_DESCRIPTIONS", bad)
    monkeypatch.setattr(game_data, "_PER_SKILL_CACHE", None)
    assert game_data.load_per_skill_stat_descriptions() is None


def test_is_support_gem_returns_bool():
    r = CharacterComparator()._is_support_gem("Faster Casting Support")
    assert r is True
    assert CharacterComparator()._is_support_gem("Fireball") is False


def test_compare_passives_tolerates_null_nodes():
    # dict.get(key, default) returns None when the key is present with a null value.
    c = CharacterComparator()
    user = {"passives": {"hashes": None}}
    top = [{"passives": {"nodes": None}}, {"passives": [1, 2]}]
    out = c._compare_passives(user, top)
    assert isinstance(out, dict)
