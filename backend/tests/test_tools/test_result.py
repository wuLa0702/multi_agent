"""工具输出信封单测（阶段 2.1）：`ToolResult` 三态契约 + `render` 渲染。

契约见 `docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md` §2 / §4。
"""

from __future__ import annotations

import dataclasses

import pytest

from src.tools.contract.result import ToolResult, render


class TestToolResultContract:
    """构造与默认值——阶段 2.1 的核心产出就是这份契约。"""

    def test_only_status_and_message_required(self) -> None:
        """status / message 必填，其余字段有默认值。"""
        result = ToolResult(status="ok", message="搜索成功")
        assert result.data is None
        assert result.error_code == ""
        assert result.retryable is False
        assert result.tool == ""

    def test_full_construction(self) -> None:
        """三态各自的完整构造（error 态带码 + 可重试标记）。"""
        result = ToolResult(
            status="error",
            message="抓取失败：HTTP 429 触发限流",
            error_code="rate_limited",
            retryable=True,
            tool="fetch_url",
        )
        assert result.status == "error"
        assert result.data is None
        assert result.error_code == "rate_limited"
        assert result.retryable is True
        assert result.tool == "fetch_url"

    def test_degraded_carries_partial_data(self) -> None:
        """degraded 态：有结果但不完整 → data 有值、status 不是 ok。"""
        result = ToolResult(
            status="degraded",
            message="输出超限，已截断至 8000 字符",
            data={"stdout": "partial", "truncated": True},
            tool="run_code_in_sandbox",
        )
        assert result.status == "degraded"
        assert result.data == {"stdout": "partial", "truncated": True}

    def test_frozen(self) -> None:
        """冻结不可变：信封一经产出不可被下游改写。"""
        result = ToolResult(status="ok", message="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.message = "y"  # type: ignore[misc]

    def test_field_names_are_contract(self) -> None:
        """字段名即契约（2.3 审计 / SSE 按名取，改名必须同步下游）。"""
        assert [f.name for f in dataclasses.fields(ToolResult)] == [
            "status",
            "message",
            "data",
            "error_code",
            "retryable",
            "tool",
        ]


class TestRender:
    """`render()` 三态渲染——LLM 只看文本，结构化走 artifact 旁路。"""

    def test_ok_returns_message_verbatim(self) -> None:
        """ok 态不加任何前缀（保持改造前文案风格）。"""
        result = ToolResult(status="ok", message="已写入 wiki: a.md", tool="write_wiki")
        assert render(result) == "已写入 wiki: a.md"

    def test_degraded_marks_partial(self) -> None:
        """degraded 态加「（部分结果）」前缀，提示 LLM 结果不完整。"""
        result = ToolResult(status="degraded", message="输出超限，已截断至 8000 字符")
        assert render(result) == "（部分结果）输出超限，已截断至 8000 字符"

    def test_error_uses_failure_prefix(self) -> None:
        """error 态加「失败原因：」前缀（对齐 06 §6 中文 + 冒号分隔）。"""
        result = ToolResult(status="error", message="链接格式非法", error_code="invalid_arg")
        assert render(result) == "失败原因：链接格式非法"

    def test_error_code_not_leaked_to_llm(self) -> None:
        """错误码不进 LLM 文本——避免模型对着 code 猜（结构化只走 artifact）。"""
        result = ToolResult(status="error", message="请求超时", error_code="timeout")
        assert "timeout" not in render(result)

    def test_data_not_serialized_into_text(self) -> None:
        """data 不塞进 content——避免 token 膨胀与模型困惑（设计 §4 双通道）。"""
        result = ToolResult(
            status="ok",
            message="搜索到 3 条结果",
            data={"results": [{"title": "a", "url": "https://x.com"}]},
        )
        assert render(result) == "搜索到 3 条结果"
