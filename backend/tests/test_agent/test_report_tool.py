"""generate_report 工具单测（阶段 2.2.9）。

此前无直接行为测试（只有工具清单里的名字断言），本次补齐。纯本地无外部依赖。
"""

from __future__ import annotations

from src.core.errors import ToolErrorCode
from src.tools.impl.report import generate_report


def test_empty_content_is_invalid_arg() -> None:
    """正文为空 → invalid_arg（不可重试）。"""
    result = generate_report("标题", "  \n ")
    assert result.status == "error"
    assert result.error_code == ToolErrorCode.INVALID_ARG
    assert result.retryable is False
    assert "内容为空" in result.message


def test_success_returns_markdown_and_data() -> None:
    """成功 → ok 信封；data 带 title 与完整 markdown（供程序侧取结构化正文）。"""
    result = generate_report("AI 行业周报", "# 一、概览\n正文")

    assert result.status == "ok"
    assert result.error_code == ""
    assert result.data is not None
    assert result.data["title"] == "AI 行业周报"
    assert result.data["markdown"] == result.message
    assert result.message.startswith("# AI 行业周报")
    assert "来源引用" in result.message


def test_blank_title_falls_back_to_default() -> None:
    """标题空白 → 用默认标题「研究报告」，**仍算成功**（不是错误）。"""
    result = generate_report("   ", "正文")
    assert result.status == "ok"
    assert result.data is not None
    assert result.data["title"] == "研究报告"


def test_content_is_stripped() -> None:
    """正文首尾空白被清理（不把空行带进报告）。"""
    result = generate_report("T", "  正文  ")
    assert "\n正文\n" in result.message
