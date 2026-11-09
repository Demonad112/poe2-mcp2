"""search_for_upgrades must build category + pseudo-stat queries for any supported slot."""
import asyncio
from unittest.mock import AsyncMock

from src.api.trade_api import TradeAPI


def _api(items=None):
    api = TradeAPI(poesessid="x" * 32)
    api.search_items = AsyncMock(return_value=items or [])
    return api


def test_ring_slot_builds_category_and_pseudo_res_filters():
    api = _api([{"name": "r", "price": {"currency": "chaos", "amount": 5}}])
    out = asyncio.run(
        api.search_for_upgrades(
            "Forbidden Rites",
            {"item_slots": ["ring"], "missing_resistances": {"lightning": 2, "chaos": 6}},
        )
    )
    assert list(out) == ["rings"]
    league, filters = api.search_items.call_args.args[:2]
    assert league == "Forbidden Rites"
    assert filters["item_filters"]["type_filters"]["filters"]["category"]["option"] == "accessory.ring"
    ids = {s["id"]: s["min"] for s in filters["stats"]}
    assert ids == {
        "pseudo.pseudo_total_lightning_resistance": 2,
        "pseudo.pseudo_total_chaos_resistance": 6,
    }


def test_unsupported_slot_is_reported_not_silent():
    api = _api()
    out = asyncio.run(api.search_for_upgrades("Standard", {"item_slots": ["wand"]}))
    assert out == {}
    assert api.last_error.startswith("[unsupported-slot]")
    api.search_items.assert_not_called()


def test_price_cap_filters_results():
    api = _api(
        [
            {"price": {"currency": "chaos", "amount": 900}},
            {"price": {"currency": "chaos", "amount": 10}},
        ]
    )
    out = asyncio.run(
        api.search_for_upgrades(
            "Standard", {"item_slots": ["amulet"], "missing_resistances": {"cold": 5}}, 100
        )
    )
    assert len(out["amulets"]) == 1
