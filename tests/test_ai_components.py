"""AI components must construct with and without an API key.

Regression: ``Settings`` lacked ANTHROPIC_API_KEY / AI_MODEL / AI_MAX_TOKENS /
AI_TEMPERATURE, so with ENABLE_AI_INSIGHTS=true ``QueryHandler()`` raised
AttributeError and server initialisation aborted before the PoB components.
"""

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from anthropic.types import TextBlock, ThinkingBlock

from src.ai import query_handler as qh_mod
from src.ai import recommendation_engine as re_mod
from src.ai.query_handler import QueryHandler
from src.ai.recommendation_engine import RecommendationEngine
from src.config import Settings


def test_settings_have_ai_fields_with_safe_defaults():
    s = Settings(_env_file=None)
    assert s.ANTHROPIC_API_KEY is None or isinstance(s.ANTHROPIC_API_KEY, str)
    assert isinstance(s.AI_MODEL, str) and s.AI_MODEL
    assert s.AI_MAX_TOKENS > 0
    assert s.AI_TEMPERATURE is None or isinstance(s.AI_TEMPERATURE, float)


def _patch(monkeypatch, mod, key):
    fake = SimpleNamespace(
        ANTHROPIC_API_KEY=key, AI_MODEL="m", AI_MAX_TOKENS=64, AI_TEMPERATURE=0.3
    )
    monkeypatch.setattr(mod, "settings", fake)


@pytest.mark.asyncio
async def test_query_handler_without_key(monkeypatch):
    _patch(monkeypatch, qh_mod, None)
    h = QueryHandler()
    assert h.client is None
    assert "not enabled" in await h.handle_query("hi")


@pytest.mark.asyncio
async def test_recommendation_engine_without_key(monkeypatch):
    _patch(monkeypatch, re_mod, None)
    e = RecommendationEngine(db_manager=None)
    assert e.client is None
    assert "not available" in await e.generate_recommendations({}, {"tier": "A"})


def test_both_construct_with_key(monkeypatch):
    _patch(monkeypatch, qh_mod, "sk-ant-test")
    _patch(monkeypatch, re_mod, "sk-ant-test")
    assert QueryHandler().client is not None
    assert RecommendationEngine(db_manager=None).client is not None


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        # Leading non-text block: content[0].text would have raised AttributeError.
        return SimpleNamespace(
            content=[
                ThinkingBlock(type="thinking", thinking="hmm", signature="s"),
                TextBlock(type="text", text="answer"),
            ]
        )


@pytest.mark.asyncio
async def test_query_handler_filters_text_blocks_and_forwards_temperature(monkeypatch):
    _patch(monkeypatch, qh_mod, "sk-ant-test")
    h = QueryHandler()
    fake = _FakeMessages()
    h.client = SimpleNamespace(messages=fake)  # type: ignore[assignment]
    assert await h.handle_query("q") == "answer"
    assert fake.calls[0]["extra_body"] == {"temperature": 0.3}
    assert fake.calls[0]["model"] == "m" and fake.calls[0]["max_tokens"] == 64


@pytest.mark.asyncio
async def test_recommendation_engine_filters_text_blocks(monkeypatch):
    _patch(monkeypatch, re_mod, "sk-ant-test")
    e = RecommendationEngine(db_manager=None)
    e.client = SimpleNamespace(messages=_FakeMessages())  # type: ignore[assignment]
    assert await e.generate_recommendations({}, {"tier": "A"}) == "answer"
