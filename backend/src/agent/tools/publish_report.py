"""publish_report 工具：输出审核交付闸门（P0 HITL 设计 §4.5/§5.1，评审拍板纳入 P0）。

- 研报完整生成（各章节 + 引用齐全）后模型调用，请求人类审核后交付
- 命中 interrupt_on(approve/edit/reject)——approve 通过交付 / reject+note
  修改意见修订重出 / edit 人类直接改报告后交付
- P0 真实执行 = 返回"报告已交付"标记（落盘/对外发送 P2 扩展）
"""

from __future__ import annotations


def publish_report(report_content: str, title: str = "") -> str:
    """提交研究报告供审核交付。

    研究报告完整生成后调用，请求用户审核确认后再交付。报告内容将展示
    给用户审批（approve=通过交付 / reject=附修改意见退回 / edit=直接修改后交付）。

    Args:
        report_content: 报告全文（markdown）
        title: 报告标题（卡片摘要展示用）

    Returns:
        交付确认信息（approve 通过后执行；reject/edit 不会真执行）
    """
    return "报告已通过审核并交付"
