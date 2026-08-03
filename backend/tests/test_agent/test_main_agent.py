"""main_agent 单测：进程单例 + 运行时模型切换 middleware。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 单例：多次 get_agent() 只构建一次编译图
- middleware：按 ChatContext.provider 路由到 get_chat_model(provider)
- middleware：provider=None → 回落默认配置
"""

from __future__ import annotations

import pytest

from src.agent import main_agent


@pytest.fixture(autouse=True)
def _reset_agent():
    """单测内隔离：重置模块级单例（每次测试重新构建）。"""
    main_agent._agent = None
    yield
    main_agent._agent = None


def test_get_agent_singleton(mocker) -> None:
    """单例：多次调用只触发一次 create_deep_agent 构建。"""
    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mock_create = mocker.patch(
        "src.agent.main_agent.create_deep_agent", return_value=object()
    )

    a1 = main_agent.get_agent()
    a2 = main_agent.get_agent()

    assert a1 is a2, "编译图应进程内复用（单例）"
    assert mock_create.call_count == 1
    # 构建参数含运行时切换三件套：middleware + context_schema
    _, kwargs = mock_create.call_args
    assert kwargs["middleware"] == [main_agent._configurable_model]
    assert kwargs["context_schema"] is main_agent.ChatContext


@pytest.mark.asyncio
async def test_configurable_model_routes_provider(mocker) -> None:
    """middleware：ChatContext(provider="ark") → get_chat_model("ark") 换模型。"""
    from langchain.agents.middleware.types import ModelRequest
    from langgraph.runtime import Runtime

    calls: list[str | None] = []
    sentinel_model = object()

    def _fake_get_chat_model(provider: str | None = None):
        calls.append(provider)
        return sentinel_model

    mocker.patch.object(main_agent, "get_chat_model", side_effect=_fake_get_chat_model)

    request = ModelRequest(
        model=object(),
        messages=[],
        runtime=Runtime(context=main_agent.ChatContext(provider="ark")),
    )
    received: list[object] = []

    async def _handler(req):
        received.append(req.model)
        return "ok"

    result = await main_agent._configurable_model.awrap_model_call(request, _handler)

    assert calls == ["ark"], "模型工厂应按请求上下文 provider 调用"
    assert received == [sentinel_model], "handler 应收到 override 后的模型"


@pytest.mark.asyncio
async def test_configurable_model_default_provider(mocker) -> None:
    """middleware：provider=None → get_chat_model(None) 回落默认配置。"""
    from langchain.agents.middleware.types import ModelRequest
    from langgraph.runtime import Runtime

    calls: list[str | None] = []
    sentinel_model = object()
    mocker.patch.object(
        main_agent,
        "get_chat_model",
        side_effect=lambda provider=None: (calls.append(provider), sentinel_model)[1],
    )

    request = ModelRequest(
        model=object(),
        messages=[],
        runtime=Runtime(context=main_agent.ChatContext(provider=None)),
    )
    result = await main_agent._configurable_model.awrap_model_call(request, _pass_through)

    assert result == "ok"
    assert calls == [None], "不指定 provider 时应回落默认（settings.llm_provider）"


async def _pass_through(request):
    """handler 桩：透传模型并返回固定值。"""
    return "ok"
