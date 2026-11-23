"""Regression tests for real defects surfaced by enabling check_untyped_defs."""

import asyncio

from src.optimizer import passive_optimizer
from src.optimizer.passive_optimizer import PassiveOptimizer
from src.parsers.passive_tree_resolver import ResolvedNode


class _FakeResolver:
    def get_all_keystones(self):
        return [ResolvedNode(1, "Iron Will", ["+10% armour"], is_keystone=True)]

    def get_all_notables(self):
        return [ResolvedNode(2, "Big Hit", ["20% increased damage"], is_notable=True)]


def test_optimizer_fallback_uses_resolver_not_dummy_data(tmp_path, monkeypatch):
    # The fallback used to import names that don't exist in src.parsers, so the
    # ImportError was swallowed and every no-merged-tree run returned dummy data.
    monkeypatch.setattr(passive_optimizer, "DATA_DIR", tmp_path)  # no merged tree
    monkeypatch.setattr("src.parsers.passive_tree_resolver.get_resolver", lambda: _FakeResolver())
    opt = PassiveOptimizer(db_manager=None)
    out = asyncio.run(opt.optimize({"class": "warrior"}, available_points=5, goal="balanced"))
    assert out["data_source"] == "passive_tree_extractor"
    names = [a["name"] for a in out["suggested_allocations"]]
    assert names == ["Iron Will", "Big Hit"]
