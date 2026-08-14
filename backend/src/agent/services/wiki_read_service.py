"""Wiki 读取服务——multi_agent ← wiki 知识库的 REST 读通道（2026-08-13）。

wiki（llm_wiki_selfbuild）已提供 `GET /v1/pages/{path}`（PageDetailResponse），
本服务封装 REST 调用：前端「从 wiki 拉取」→ multi_agent 后端 → wiki 读取。
与写通道（wiki_export_service）对称——双向打通，走 REST 手动通道不走 MCP。
"""

from __future__ import annotations

import httpx

from src.core.config import settings
from src.agent.services.wiki_export_service import WikiExportError


class WikiPageNotFoundError(WikiExportError):
    """wiki 页面不存在（业务错误，非重试问题）。"""


async def get_page_from_wiki(path: str) -> dict:
    """读取 wiki 页面（GET /v1/pages/{path}）。

    Args:
        path: wiki 页面路径（如 对话-xxx 或 产物-类型-时间）

    Returns:
        wiki 页面 dict（{path, title, content, page_type, tags}——读回关键字段）

    Raises:
        WikiPageNotFoundError: 页面不存在（HTTP 404）
        WikiExportError: wiki 不可达（可重试）或读取失败（不可重试）
    """
    url = f"{settings.wiki_base_url.rstrip('/')}/v1/pages/{path.strip('/')}"
    try:
        resp = httpx.get(url, timeout=15)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise WikiExportError(f"wiki 不可达：{exc}", retryable=True) from exc
    if resp.status_code == 404:
        raise WikiPageNotFoundError(f"wiki 页面不存在：{path}")
    if resp.status_code == 403:
        raise WikiExportError(f"wiki 页面需权限（可能 restricted）：{path}")
    if resp.status_code >= 400:
        raise WikiExportError(f"wiki 读取失败 HTTP {resp.status_code}：{resp.text[:200]}")
    data = resp.json()
    return {
        "path": data.get("path", path),
        "title": data.get("title", path),
        "content": data.get("content", ""),
        "page_type": data.get("page_type", ""),
        "tags": data.get("tags", []),
    }
