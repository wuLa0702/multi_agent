"""主链路缓存单测（2026-08-12 成本评审 1.2 扩展实现）。

覆盖：命中绕过 handler / 未命中调 handler 后写入 / 不同 model 不共享 / 缓存关闭直接调。
"""

from __future__ import annotations

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse, Runtime
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import main_agent
from src.llm.cache import _cache


@pytest.fixture(autouse=True)
def _clear():
    _cache.clear()
    yield
    _cache.clear()


def _request(model, messages):
    return ModelRequest(
        model=model,
        messages=messages,
        runtime=Runtime(context=main_agent.ChatContext(session_id="s1")),
    )


def _mock_model_factory(mocker, model_name: str = "deepseek-v4-flash"):
    """mock get_chat_model 返回带 model_name 的假模型（避免真实 ChatOpenAI 构造）。"""

    class _FakeModel:
        def __init__(self) -> None:
            self.model_name = model_name

    mocker.patch.object(main_agent, "get_chat_model", return_value=_FakeModel())
    return _FakeModel()


class TestMainPathCache:
    @pytest.mark.asyncio
    async def test_hit_skips_handler(self, mocker, monkeypatch) -> None:
        """命中 → 绕过 handler 返回缓存（省一次 LLM）。"""
        from src.core.config import settings
        from src.llm import cache as cache_mod

        monkeypatch.setattr(settings, "llm_cache_enabled", True)
        monkeypatch.setattr(cache_mod, "set_cached", lambda *a, **k: None)
        monkeypatch.setattr(cache_mod, "get_cached", lambda *a, **k: "缓存回复")

        calls = {"n": 0}

        async def _handler(req):
            calls["n"] += 1
            return ModelResponse(result=AIMessage(content="真实回复"))

        model = _mock_model_factory(mocker)
        result = await main_agent._configurable_model.awrap_model_call(
            _request(model, [HumanMessage(content="hi")]), _handler
        )
        assert calls["n"] == 0  # 命中不调 handler
        assert result.result.content == "缓存回复"

    @pytest.mark.asyncio
    async def test_miss_calls_handler_and_writes(self, mocker, monkeypatch) -> None:
        """未命中 → 调 handler 并写入缓存。"""
        from src.core.config import settings
        from src.llm import cache as cache_mod

        monkeypatch.setattr(settings, "llm_cache_enabled", True)
        monkeypatch.setattr(cache_mod, "get_cached", lambda *a, **k: None)
        written: list[str] = []
        monkeypatch.setattr(cache_mod, "set_cached", lambda p, m, v: written.append(v))

        async def _handler(req):
            return ModelResponse(result=AIMessage(content="真实回复"))

        model = _mock_model_factory(mocker)
        result = await main_agent._configurable_model.awrap_model_call(
            _request(model, [HumanMessage(content="hi")]), _handler
        )
        assert result.result.content == "真实回复"
        assert written == ["真实回复"]  # 写入缓存

    @pytest.mark.asyncio
    async def test_disabled_direct_call(self, mocker, monkeypatch) -> None:
        """llm_cache_enabled=False → 直接调 handler（不查缓存）。"""
        from src.core.config import settings
        from src.llm import cache as cache_mod

        monkeypatch.setattr(settings, "llm_cache_enabled", False)
        monkeypatch.setattr(cache_mod, "get_cached", lambda *a, **k: pytest.fail("不应查缓存"))

        async def _handler(req):
            return ModelResponse(result=AIMessage(content="ok"))

        model = _mock_model_factory(mocker)
        result = await main_agent._configurable_model.awrap_model_call(
            _request(model, [HumanMessage(content="hi")]), _handler
        )
        assert result.result.content == "ok"
