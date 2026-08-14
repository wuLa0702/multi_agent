"""Wiki 导出服务——multi_agent → wiki 知识库的 REST 写通道（P1.5 前端保存通道）。

wiki（llm_wiki_selfbuild）已提供 `POST /v1/pages/{path}`（PageUpdateRequest），
本服务封装 REST 调用：前端「保存到 wiki」→ multi_agent 后端 → wiki 写入。
走 REST（用户手动操作），不走 MCP（MCP 是 Agent 工具通道，见 wiki 设计 §3 双通道澄清）。
"""

from __future__ import annotations

import httpx

from src.core.config import settings


class WikiExportError(Exception):
    """Wiki 导出失败（可区分可重试/不可重试）。"""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


async def export_to_wiki(
    path: str,
    content: str,
    title: str | None = None,
    page_type: str | None = None,
) -> dict:
    """导出内容到 wiki 页面（POST /v1/pages/{path}）。

    Args:
        path: wiki 页面路径（如 对话-xxx 或 产物-类型-时间）
        content: 页面正文（Markdown）
        title: 页面标题（缺省用 path）
        page_type: 页面类型（可选）

    Returns:
        wiki 响应 dict（{status, path, message}）

    Raises:
        WikiExportError: wiki 不可达（可重试）或写入失败（不可重试）
    """
    url = f"{settings.wiki_base_url.rstrip('/')}/v1/pages/{path.strip('/')}"
    payload = {"content": content, "title": title or path}
    if page_type:
        payload["page_type"] = page_type
    try:
        resp = httpx.post(url, json=payload, timeout=15)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise WikiExportError(f"wiki 不可达：{exc}", retryable=True) from exc
    if resp.status_code >= 400:
        raise WikiExportError(f"wiki 写入失败 HTTP {resp.status_code}：{resp.text[:200]}")
    return resp.json()
