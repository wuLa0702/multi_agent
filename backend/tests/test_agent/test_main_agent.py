"""main_agent 单测：会话级缓存 + 运行时模型切换 middleware。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 会话级缓存：同 thread 复用同一编译图；不同 thread 独立编译图（v2.0）
- middleware：按 ChatContext.model_id 路由到 get_chat_model(model_id)
- middleware：model_id=None → 回落默认模型
"""

from __future__ import annotations

import pytest

from src.agent import main_agent


@pytest.fixture(autouse=True)
def _reset_agent():
    """单测内隔离：重置模块级会话缓存（每次测试重新构建）。"""
    main_agent._agents.clear()
    yield
    main_agent._agents.clear()


def test_get_agent_session_cache(mocker) -> None:
    """会话级缓存：同会话复用；不同会话独立编译图（v2.0 会话隔离）。"""
    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    # P1-1：真实 YAML 带 model 字段需模型注册表——本测试聚焦缓存，不解析真实子代理
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])
    # side_effect 每次返回新对象——不同会话的编译图必须是不同实例
    mock_create = mocker.patch(
        "src.agent.main_agent.create_deep_agent",
        side_effect=lambda *a, **k: object(),
    )

    a1 = main_agent.get_agent("session-a")
    a2 = main_agent.get_agent("session-a")
    a3 = main_agent.get_agent("session-b")

    assert a1 is a2, "同会话应复用同一编译图"
    assert a1 is not a3, "不同会话应独立编译图（backend 文件根隔离）"
    assert mock_create.call_count == 2
    # 构建参数含运行时切换三件套：middleware + context_schema + backend
    # （2026-08-04 评审改版：middleware 含 TokenUsageMiddleware；v2.0 会话级 backend；
    # v3.0：+ ToolAuditMiddleware + permissions 上层声明式规则）
    _, kwargs = mock_create.call_args
    middleware_types = [type(m) for m in kwargs["middleware"]]
    assert middleware_types == [
        type(main_agent._configurable_model),
        main_agent.TokenUsageMiddleware,
        main_agent.ToolAuditMiddleware,
    ], "中间件栈应含模型切换 + 用量统计 + 工具审计"
    assert kwargs["context_schema"] is main_agent.ChatContext
    assert kwargs["backend"] is not None, "v2.0 会话级 backend 应挂载（文件根隔离）"
    assert kwargs["permissions"][0].mode == "deny", "P0 上层声明式规则应挂载（/skills/** 写 deny）"


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


# ── v3：有界 LRU 缓存治理（深化方案 §2.3）──

def test_agent_cache_lru_eviction(mocker) -> None:
    """T4：缓存超限逐出最久未用会话（只逐内存图，不删磁盘）。"""
    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])  # P1-1：不解析真实 YAML
    mocker.patch("src.agent.main_agent.create_deep_agent", side_effect=lambda *a, **k: object())

    for i in range(main_agent._AGENT_CACHE_MAX + 5):
        main_agent.get_agent(f"t{i}")

    assert len(main_agent._agents) == main_agent._AGENT_CACHE_MAX, "超限应逐出到上限"
    assert "t0" not in main_agent._agents, "最早使用的最先被逐出"
    assert f"t{main_agent._AGENT_CACHE_MAX + 4}" in main_agent._agents, "最近使用的保留"


def test_agent_cache_lru_refresh(mocker) -> None:
    """T4：命中刷新（pop 后放回）——重新访问过的会话不被逐出。"""
    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])  # P1-1：不解析真实 YAML
    mocker.patch("src.agent.main_agent.create_deep_agent", side_effect=lambda *a, **k: object())

    main_agent.get_agent("t0")
    main_agent.get_agent("t1")
    main_agent.get_agent("t0")  # 刷新 t0 为最近使用 → 使用序 [t1, t0]
    for i in range(2, main_agent._AGENT_CACHE_MAX + 1):  # 再加 31 个 → 恰逐出 1 个（最老的 t1）
        main_agent.get_agent(f"t{i}")

    assert "t0" in main_agent._agents, "刷新后的 t0 不应被逐出"
    assert "t1" not in main_agent._agents, "最久未用的 t1 应被逐出"
