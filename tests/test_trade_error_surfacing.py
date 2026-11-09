"""A trade-site 403 must surface as an error, not as 'No items found'."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.api.trade_api import TradeAPI


def _api_with_status(status: int, body: str = '{"error":{"code":6,"message":"Forbidden"}}'):
    api = TradeAPI(poesessid="x" * 32)
    req = httpx.Request("POST", "https://www.pathofexile.com/api/trade2/search/poe2/Standard")
    resp = httpx.Response(status, text=body, request=req)
    api.client = MagicMock()
    api.client.post = AsyncMock(return_value=resp)
    api.client.get = AsyncMock(return_value=resp)
    api.rate_limiter.acquire = AsyncMock()
    return api


def test_search_items_403_sets_last_error():
    api = _api_with_status(403)
    assert asyncio.run(api.search_items("Standard", {}, limit=5)) == []
    assert "403" in api.last_error and "Forbidden" in api.last_error
    assert api.last_error.startswith("[auth/blocked]")


def test_search_items_429_and_503_classified():
    api = _api_with_status(429, "slow down")
    asyncio.run(api.search_items("Standard", {}))
    assert api.last_error.startswith("[rate-limit]")
    api = _api_with_status(503, "down")
    asyncio.run(api.search_items("Standard", {}))
    assert api.last_error.startswith("[unavailable]")


def test_fetch_details_403_sets_last_error():
    api = _api_with_status(403)
    assert asyncio.run(api._fetch_item_details(["a"], "q")) == []
    assert "403" in api.last_error


def test_search_for_upgrades_keeps_error_when_no_results():
    api = _api_with_status(403)
    out = asyncio.run(api.search_for_upgrades("Standard", {"needs_life": True}))
    assert out == {}
    assert api.last_error and "403" in api.last_error
