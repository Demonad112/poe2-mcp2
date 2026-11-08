"""Trade query building: weighted sum groups and shareable link (no network)."""
import asyncio

import httpx

from src.api.trade_api import TradeAPI


def _api():
    return TradeAPI(poesessid="test")


def test_weighted_sum_group_shape():
    q = _api()._build_search_query(
        {
            "type": "Amulet",
            "weighted_sum": {
                "filters": [
                    {"id": "explicit.stat_3299347043", "weight": 1},
                    {"id": "explicit.stat_4220027924", "weight": 2.5},
                ],
                "min": 120,
            },
        }
    )
    groups = q["query"]["stats"]
    assert len(groups) == 1 and groups[0]["type"] == "weight"
    assert groups[0]["value"] == {"min": 120}
    assert groups[0]["filters"][1]["value"] == {"weight": 2.5}
    assert q["sort"] == {"statgroup.0": "desc"}


def test_no_weighted_sum_keeps_default_and_group():
    q = _api()._build_search_query({"type": "Amulet"})
    assert q["query"]["stats"][0]["type"] == "and"
    assert q["sort"] == {"price": "asc"}


def test_search_url_and_auth_error_surface():
    api = _api()

    def handler(req: httpx.Request) -> httpx.Response:
        if "/search/" in req.url.path:
            return httpx.Response(200, json={"id": "abc123", "result": [], "total": 0})
        return httpx.Response(403, json={"error": {"code": 6, "message": "Forbidden"}})

    api.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(api.search_items("Standard", {"type": "Amulet"}))
    assert api.last_search_url == "https://www.pathofexile.com/trade2/search/poe2/Standard/abc123"

    def forbidden(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": 6, "message": "Forbidden"}})

    api.client = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    assert asyncio.run(api.search_items("Standard", {"type": "Amulet"})) == []
    assert "403" in api.last_error and "POESESSID" in api.last_error
