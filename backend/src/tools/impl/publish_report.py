"""publish_report 工具：输出审核交付闸门（P0 HITL 设计 §4.5/§5.1，评审拍板纳入 P0）。

- 研报完整生成（各章节 + 引用齐全）后模型调用，请求人类审核后交付
- 命中 interrupt_on(approve/edit/reject)——approve 通过交付 / reject+note
  修改意见修订重出 / edit 人类直接改报告后交付
- P0 真实执行 = 返回"报告已交付"标记（落盘/对外发送 P2 扩展）

输出为 `ToolResult` 信封（阶段 2.2.10）。本工具无错误分支——未通过审核时
走的是 HITL 中断/拒绝链路，不落到"工具返回失败"。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from src.tools.contract.result import ToolResult

_TOOL_NAME = "publish_report"


def publish_report(
    report_content: Annotated[
        str,
        Field(description="报告全文（Markdown）；会完整展示给用户审批，须是最终稿"),
    ],
    title: Annotated[
        str,
        Field(description="报告标题；用于审批卡片摘要展示，不传则为空"),
    ] = "",
) -> ToolResult:
    """提交研究报告供审核交付。

    研究报告完整生成后调用，请求用户审核确认后再交付。报告内容将展示
    给用户审批（approve=通过交付 / reject=附修改意见退回 / edit=直接修改后交付）。

    Args:
        report_content: 报告全文（markdown）
        title: 报告标题（卡片摘要展示用）

    Returns:
        `ok` 信封（`data` 带 title）；approve 通过后才走到这里，
        reject/edit 不会真执行
    """
    return ToolResult(
        status="ok",
        message="报告已通过审核并交付",
        data={"title": title},
        tool=_TOOL_NAME,
    )
