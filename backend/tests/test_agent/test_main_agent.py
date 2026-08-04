"""main_agent 单测：进程单例 + 运行时模型切换 middleware。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 单例：多次 get_agent() 只构建一次编译图
- middleware：按 ChatContext.model_id 路由到 get_chat_model(model_id)
- middleware：model_id=None → 回落默认模型
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
    # （2026-08-04 评审改版：middleware 含 TokenUsageMiddleware——图执行完自动统计用量存库）
    _, kwargs = mock_create.call_args
    middleware_types = [type(m) for m in kwargs["middleware"]]
    assert middleware_types == [
        type(main_agent._configurable_model),
        main_agent.TokenUsageMiddleware,
    ], "中间件栈应含模型切换 + 用量统计"
    assert kwargs["context_schema"] is main_agent.ChatContext


async def _route_model_id(mocker, model_id: int | None) -> tuple[list[int | None], list[object]]:
    """构造 ModelRequest 走 middleware，返回 get_chat_model 收到的参数与 handler 收到的模型。"""
    from langchain.agents.middleware.types import ModelRequest
    from langgraph.runtime import Runtime

    calls: list[int | None] = []
    sentinel_model = object()

    def _fake_get_chat_model(model_id: int | None = None):
        calls.append(model_id)
        return sentinel_model

    mocker.patch.object(main_agent, "get_chat_model", side_effect=_fake_get_chat_model)

    request = ModelRequest(
        model=object(),
        messages=[],
        runtime=Runtime(context=main_agent.ChatContext(model_id=model_id)),
    )
    received: list[object] = []

    async def _handler(req):
        received.append(req.model)
        return "ok"

    result = await main_agent._configurable_model.awrap_model_call(request, _handler)

    assert result == "ok"
    return calls, received


@pytest.mark.asyncio
async def test_configurable_model_routes_model_id(mocker) -> None:
    """middleware：ChatContext(model_id=3) → get_chat_model(model_id=3) 换模型。"""
    calls, received = await _route_model_id(mocker, model_id=3)

    assert calls == [3], "模型工厂应按请求上下文 model_id 调用"
    assert received, "handler 应收到 override 后的模型"


@pytest.mark.asyncio
async def test_configurable_model_default_model_id(mocker) -> None:
    """middleware：model_id=None → get_chat_model(None) 回落默认模型。"""
    calls, _ = await _route_model_id(mocker, model_id=None)

    assert calls == [None], "不指定 model_id 时应回落默认模型"
