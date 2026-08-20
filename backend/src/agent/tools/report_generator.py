"""generate_report 工具：研报结构化生成（方案 v2.1 §2.5，2026-08-13）。

主 Agent 撰写内容 → 本工具结构化（标题/章节/来源引用占位）→ 返回给主 Agent
交付（走 publish_report 审核闸门 / write_wiki 归档 / 前端展示）。

Word 渲染（沙箱 python-docx）为增强，当前以结构化 Markdown 交付（demo/前端均兼容）。
"""

from __future__ import annotations


def generate_report(title: str, content: str) -> str:
    """生成结构化研报（标题 + 正文 + 来源占位）。

    Args:
        title: 报告标题
        content: 报告正文（Markdown，多章节）

    Returns:
        结构化报告文本（含标题/来源引用说明），供主 Agent 交付
    """
    if not title.strip():
        title = "研究报告"
    if not content.strip():
        return "生成失败：内容为空"
    lines = [f"# {title}", "", content.strip(), "", "---", "_来源引用：请确保关键论断有可核验来源（编号引用）_"]
    return "\n".join(lines)
