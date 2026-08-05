"""事件流分发测试（引入方案 P0：token + tool_call + subagent 三类事件）。

核心断言（评审问题 1 回归）：**事件按实际发生顺序交错输出**——
不是"先全部 token 再全部工具调用"的串行错乱；seq 自增供前端排序。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk

from src.agent.main_agent import _truncate, stream_agent_events


class _FakeStreamAgent:
    """假 agent：astream_events 产出合成事件流（按给定顺序）。"""

    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(self, input, **kwargs):  # noqa: ANN001
        for evt in self._events:
            yield evt


def _token_evt(text: str) -> dict:
    return {
        "event": "on_chat_model_stream",
        "data": {"chunk": AIMessageChunk(content=text)},
    }


def _tool_start(name: str, input: str) -> dict:
    return {"event": "on_tool_start", "name": name, "data": {"input": input}}


def _tool_end(name: str, output: str) -> dict:
    return {"event": "on_tool_end", "name": name, "data": {"output": output}}


def _subagent_start(name: str) -> dict:
    return {
        "event": "on_chain_start",
        "metadata": {"lc_agent_name": name},
    }


def _subagent_end(name: str) -> dict:
    return {
        "event": "on_chain_end",
        "metadata": {"lc_agent_name": name},
    }


async def _collect(events: list[dict]) -> list[dict]:
    agent = _FakeStreamAgent(events)
    return [e async for e in stream_agent_events(agent, [])]


@pytest.mark.asyncio
async def test_events_interleaved_in_actual_order() -> None:
    """评审问题 1 回归：交错事件按实际发生顺序输出（非串行分块）。

    token → 工具启动 → token → 子代理 → 工具结束 → token 的交错流，
    产出顺序必须与发生顺序一致——前端才能正确渲染流式效果。
    """
    events = [
        _token_evt("你好"),
        _tool_start("run_code_in_sandbox", '{"code": "x"}'),
        _token_evt("，正在"),
        _subagent_start("search_agent"),
        _tool_end("run_code_in_sandbox", "ok"),
        _token_evt("执行"),
    ]

    out = await _collect(events)

    assert [e["type"] for e in out] == [
        "token", "tool_call", "token", "subagent", "tool_call", "token",
    ], "事件必须按实际发生顺序交错输出（评审问题 1）"
    assert out[1]["status"] == "running" and out[4]["status"] == "completed"
    assert out[3]["name"] == "search_agent" and out[3]["status"] == "started"


@pytest.mark.asyncio
async def test_seq_increments_monotonically() -> None:
    """事件 id 自增（前端去重/排序）。"""
    out = await _collect([_token_evt("a"), _token_evt("b"), _tool_start("t", "i")])

    assert [e["id"] for e in out] == [1, 2, 3]


@pytest.mark.asyncio
async def test_tool_call_input_truncated() -> None:
    """tool_call 入参截断 ≤300（密钥纪律，同 ToolAudit 脱敏）。"""
    out = await _collect([_tool_start("t", "x" * 500)])

    assert len(out[0]["input"]) <= 301
    assert out[0]["input"].endswith("…")


@pytest.mark.asyncio
async def test_empty_token_chunks_skipped() -> None:
    """空 text chunk 不产出 token 事件（工具调用 chunk 天然过滤，同 v2 语义）。"""
    out = await _collect([_token_evt(""), _token_evt("有内容")])

    assert [e["type"] for e in out] == ["token"]
    assert out[0]["text"] == "有内容"


def test_truncate() -> None:
    """事件字段截断工具。"""
    assert _truncate("短文本") == "短文本"
    assert len(_truncate("x" * 500)) <= 301
    assert _truncate("x" * 500).endswith("…")
