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


def test_datc64_corruption_warning_accepts_str_path(monkeypatch, tmp_path):
    # `file_path.name` raised AttributeError when parse_file() got a str path and
    # corrupted string pointers were repaired.
    from src.parsers import datc64_parser as dp

    parser = dp.Datc64Parser()
    monkeypatch.setattr(
        parser, "parse_header", lambda p: {"record_length": 0, "magic_offset": 4, "row_count": 0}
    )
    monkeypatch.setattr(parser, "_repair_string_corruption", lambda rows, cols: 3)
    f = tmp_path / "x.datc64"
    f.write_bytes(b"\x00" * 64)
    assert parser.parse_file(str(f), []) == []


def test_needs_update_branches(monkeypatch):
    from src.data import data_distributor as dd

    def run(local, remote):
        monkeypatch.setattr(dd, "get_local_data_version", lambda: local)
        monkeypatch.setattr(dd, "get_latest_release_info", lambda: remote)
        return dd.needs_update()

    assert run(None, {"tag_name": "data-1"})[0] is True
    assert run(None, None)[0] is False
    assert run({"release_tag": "data-1"}, None)[0] is False
    assert run({"release_tag": "data-1"}, {"tag_name": "data-2"})[0] is True
    assert run({"release_tag": "data-2"}, {"tag_name": "data-2"})[0] is False


def test_get_all_notables_never_contains_none(monkeypatch):
    from src.parsers.passive_tree_resolver import PassiveTreeResolver

    r = PassiveTreeResolver.__new__(PassiveTreeResolver)
    monkeypatch.setattr(r, "_ensure_loaded", lambda: None, raising=False)
    # empty-dict node makes resolve() return None
    r._nodes = {1: {}, 2: {"name": "N", "is_notable": True}}
    r._nodes[1]["is_notable"] = True
    out = r.get_all_notables()
    assert all(n is not None for n in out)


def test_game_config_reader_preserves_key_case(tmp_path):
    from src.api.game_config_reader import GameConfigReader

    ini = tmp_path / "poe2_production_Config.ini"
    ini.write_text("[LOGIN]\nSomeKey=1\n", encoding="utf-8")
    parser = GameConfigReader(config_path=ini)._load()
    assert parser is not None and "SomeKey" in parser["LOGIN"]
