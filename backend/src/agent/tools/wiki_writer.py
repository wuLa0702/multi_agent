"""write_wiki 工具：Agent 运行时把内容写入 wiki 知识库（P1.5/P1，2026-08-13）。

走 REST（wiki_export_service 调 wiki POST /v1/pages/{path}）——Agent 工具通道
（MCP 需 wiki 侧暴露 wiki_write，暂用 REST 直连，双通道语义见 wiki 设计 §3）。

失败降级为错误信息，不中断 run。
"""

from __future__ import annotations

from src.agent.services.wiki_export_service import WikiExportError, export_to_wiki


def write_wiki(path: str, content: str, title: str = "") -> str:
    """把内容写入 wiki 知识库页面。

    Args:
        path: wiki 页面路径（如 调研结论-xxx / 知识-xxx）
        content: 页面正文（Markdown）
        title: 页面标题（缺省用 path）

    Returns:
        成功 → "已写入 wiki: {path}"；失败 → 降级错误信息
    """
    if not content.strip():
        return "写入失败：内容为空"
    try:
        result = export_to_wiki(path, content, title or path)
    except WikiExportError as exc:
        return f"写入 wiki 失败：{exc}"
    return f"已写入 wiki: {result.get('path') or path}"
