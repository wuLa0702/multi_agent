"""事件流分发测试（引入方案 P0：token + tool_call + subagent 三类事件）。

核心断言（评审问题 1 回归）：**事件按实际发生顺序交错输出**——
不是"先全部 token 再全部工具调用"的串行错乱；seq 自增供前端排序。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage

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


def _tool_end_msg(
    name: str,
    status: str,
    error_code: str = "",
    content: str = "文本",
    retryable: bool = False,
) -> dict:
    """真实链路形态的 on_tool_end：output 是带 artifact 信封的 ToolMessage。"""
    return {
        "event": "on_tool_end",
        "name": name,
        "data": {
            "output": ToolMessage(
                content=content,
                tool_call_id="tc1",
                name=name,
                artifact={
                    "status": status,
                    "error_code": error_code,
                    "retryable": retryable,
                    "data": None,
                },
            )
        },
    }


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


class TestToolOutcome:
    """工具三态落 SSE 事件（阶段 2.3.2）：生命周期与结果三态**各管一件事**。"""

    @pytest.mark.parametrize(
        ("result_status", "error_code", "expect_lifecycle"),
        [
            ("ok", "", "completed"),
            ("degraded", "", "completed"),  # 跑完了，只是结果不完整
            ("error", "rate_limited", "error"),
            ("error", "not_configured", "error"),
        ],
    )
    async def test_result_status_and_lifecycle(
        self, result_status: str, error_code: str, expect_lifecycle: str
    ) -> None:
        """有信封：三态与错误码带出；生命周期按三态映射（degraded 不算 error）。"""
        out = await _collect(
            [_tool_end_msg("fetch_url", result_status, error_code)]
        )

        evt = out[0]
        assert evt["status"] == expect_lifecycle
        assert evt["result_status"] == result_status
        assert evt["error_code"] == error_code

    async def test_degraded_is_visible(self) -> None:
        """回归锁：`degraded` 必须能从 SSE 看到——它正是 ToolMessage.status 盖不住的那档。"""
        out = await _collect([_tool_end_msg("download_sandbox_file", "degraded")])

        assert out[0]["status"] == "completed", "调用本身跑完了"
        assert out[0]["result_status"] == "degraded", "但结果不完整，必须如实告知前端"

    async def test_no_envelope_yields_none(self) -> None:
        """无信封（测试替身 / 旧形态输出）→ 三态 None，生命周期 completed（不猜）。"""
        out = await _collect([_tool_end("fetch_url", "plain text output")])

        assert out[0]["status"] == "completed"
        assert out[0]["result_status"] is None
        assert out[0]["error_code"] == ""

    async def test_output_uses_message_content_not_repr(self) -> None:
        """output 取 ToolMessage.content，不是其 repr（否则前端看到一坨对象字面量）。"""
        out = await _collect([_tool_end_msg("fetch_url", "ok", content="抓取到的正文")])

        assert out[0]["output"] == "抓取到的正文"
        assert "ToolMessage" not in str(out[0]["output"])

    async def test_start_event_has_no_result_status(self) -> None:
        """事中（running）不该有三态——结果还没出来，填了就是编。"""
        out = await _collect([_tool_start("fetch_url", "{}")])

        assert out[0]["status"] == "running"
        assert out[0]["result_status"] is None

    async def test_retryable_carried_on_failure(self) -> None:
        """失败的可重试性上事件（阶段 4 批次 3）——与 error_code 同族的运行时事实。"""
        out = await _collect(
            [_tool_end_msg("internet_search", "error", "rate_limited", retryable=True)]
        )

        assert out[0]["error_code"] == "rate_limited"
        assert out[0]["retryable"] is True

    async def test_retryable_false_on_success_and_start(self) -> None:
        """成功与事中恒 False（无失败可言）——形状统一，前端不必判键存在。"""
        out = await _collect([_tool_start("fetch_url", "{}"), _tool_end_msg("fetch_url", "ok")])

        assert out[0]["retryable"] is False, "事中还没结果"
        assert out[1]["retryable"] is False, "成功无失败可言"

    async def test_no_envelope_retryable_defaults_false(self) -> None:
        """无信封（测试替身 / 旧形态）→ retryable False（不猜）。"""
        out = await _collect([_tool_end("fetch_url", "plain text")])

        assert out[0]["retryable"] is False
