"""子代理容错包装测试（面试描述点-容错：重试 + 错误摘要回传主 Agent）。

覆盖：
- 可重试异常（TimeoutError）→ 自动重试后成功
- 可重试异常重试耗尽 → 返回错误摘要 state（含 messages + 重试次数）
- 不可重试异常 → 不重试，直接错误摘要
- 同步 / 异步双路径（async 用 asyncio.run，不依赖 pytest-asyncio）
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

import src.agent.subagents.guard as guard
from src.agent.subagents.guard import GuardedSubAgent, SUBAGENT_RETRIES


class _FlakyRunnable:
    """测试桩：前 fail_first 次抛异常，之后返回成功结果。"""

    def __init__(self, fail_first: int = 0, exc: Exception = TimeoutError("boom")) -> None:
        self._fail_first = fail_first
        self._exc = exc
        self.calls = 0

    def invoke(self, input, config=None):
        self.calls += 1
        if self.calls <= self._fail_first:
            raise self._exc
        return {"messages": [AIMessage(content="成功结果")]}

    async def ainvoke(self, input, config=None):
        self.calls += 1
        if self.calls <= self._fail_first:
            raise self._exc
        return {"messages": [AIMessage(content="成功结果")]}


def test_retry_then_success_sync(monkeypatch) -> None:
    """可重试异常 → 自动重试后成功（第 1 次抛超时，第 2 次成功）。"""
    monkeypatch.setattr(guard, "SUBAGENT_RETRY_DELAY", 0)
    inner = _FlakyRunnable(fail_first=1)
    guarded = GuardedSubAgent(inner, "search_agent")

    result = guarded.invoke({"messages": []})

    assert inner.calls == 2, "可重试异常应自动重试一次"
    assert result["messages"][0].content == "成功结果"


def test_retry_exhausted_sync(monkeypatch) -> None:
    """可重试异常重试耗尽 → 返回错误摘要（含 messages + 已重试次数），不抛异常。"""
    monkeypatch.setattr(guard, "SUBAGENT_RETRY_DELAY", 0)
    inner = _FlakyRunnable(fail_first=10)
    guarded = GuardedSubAgent(inner, "search_agent")

    result = guarded.invoke({"messages": []})

    assert inner.calls == SUBAGENT_RETRIES + 1, "重试耗尽后停止"
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    assert f"已重试 {SUBAGENT_RETRIES} 次" in msg.content
    assert "search_agent" in msg.content


def test_non_retryable_no_retry_sync() -> None:
    """不可重试异常 → 不重试，直接返回错误摘要（重试 0 次）。"""
    inner = _FlakyRunnable(fail_first=1, exc=ValueError("参数错"))
    guarded = GuardedSubAgent(inner, "review_agent")

    result = guarded.invoke({"messages": []})

    assert inner.calls == 1, "不可重试异常不重试"
    assert "已重试 0 次" in result["messages"][0].content


def test_retry_then_success_async(monkeypatch) -> None:
    """异步路径：可重试异常 → 自动重试后成功（asyncio.sleep 不阻塞事件循环）。"""
    monkeypatch.setattr(guard, "SUBAGENT_RETRY_DELAY", 0)
    inner = _FlakyRunnable(fail_first=1)
    guarded = GuardedSubAgent(inner, "search_agent")

    result = asyncio.run(guarded.ainvoke({"messages": []}))

    assert inner.calls == 2
    assert result["messages"][0].content == "成功结果"


def test_guard_subagent_idempotent() -> None:
    """guard_subagent 幂等：已包装的不重复包。"""
    inner = _FlakyRunnable()
    guarded = GuardedSubAgent(inner, "search_agent")

    assert guard.guard_subagent(guarded, "search_agent") is guarded


def test_compile_guarded_active_throw_returns_error_summary(mocker) -> None:
    """真实编译路径 + 主动抛错：子代理模型调用抛超时 → guard 重试 1 次 → 错误摘要回传。

    走 loader._compile_guarded（真实 create_deep_agent 编译）+ BaseChatModel.ainvoke
    主动抛 TimeoutError——验证容错包装在生产路径上不冒泡、重试、附重试次数回传。
    """
    import asyncio

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    from src.agent.subagents import loader

    model = ChatOpenAI(model="deepseek-v4-flash", api_key="x", base_url="https://x")
    mocker.patch.object(
        BaseChatModel, "ainvoke", autospec=True, side_effect=TimeoutError("模拟 LLM 超时")
    )
    spec = {
        "name": "throwing_agent",
        "description": "x",
        "system_prompt": "p",
        "tools": [],
        "permissions": [],
    }
    compiled = loader._compile_guarded(spec, model)

    result = asyncio.run(compiled["runnable"].ainvoke({"messages": [HumanMessage("hi")]}))

    assert isinstance(compiled["runnable"], GuardedSubAgent), "编译路径应挂容错包装"
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage), "错误摘要经 AIMessage 回传（主 Agent 可见）"
    assert "TimeoutError" in msg.content
    assert "已重试 1 次" in msg.content, "可重试异常应重试 1 次后仍失败才降级"
    assert "不要重试" in msg.content
