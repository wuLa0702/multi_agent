"""generate_report 工具：研报结构化生成（方案 v2.1 §2.5，2026-08-13）。

主 Agent 撰写内容 → 本工具结构化（标题/章节/来源引用占位）→ 返回给主 Agent
交付（走 publish_report 审核闸门 / write_wiki 归档 / 前端展示）。

Word 渲染（沙箱 python-docx）为增强，当前以结构化 Markdown 交付（demo/前端均兼容）。
输出为 `ToolResult` 信封（阶段 2.2.9）。
"""

from __future__ import annotations

from src.core.errors import ToolErrorCode
from src.tools.contract.result import ToolResult

_TOOL_NAME = "generate_report"

_DEFAULT_TITLE = "研究报告"
_SOURCE_NOTE = "_来源引用：请确保关键论断有可核验来源（编号引用）_"


def generate_report(title: str, content: str) -> ToolResult:
    """生成结构化研报（标题 + 正文 + 来源占位）。

    Args:
        title: 报告标题（空白则用默认标题「研究报告」，仍算成功）
        content: 报告正文（Markdown，多章节）

    Returns:
        `ok` 信封（`data` 带 title / markdown，供程序侧取结构化正文）；
        正文为空 → `error: invalid_arg`
    """
    if not title.strip():
        title = _DEFAULT_TITLE
    if not content.strip():
        return ToolResult(
            status="error",
            message="生成失败：内容为空",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    report = "\n".join(
        [f"# {title}", "", content.strip(), "", "---", _SOURCE_NOTE]
    )
    return ToolResult(
        status="ok",
        message=report,
        data={"title": title, "markdown": report},
        tool=_TOOL_NAME,
    )
