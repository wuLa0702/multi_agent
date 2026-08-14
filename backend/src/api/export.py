"""导出/读取 REST 路由（wiki 双向通道，2026-08-13）：写 POST /v1/export/wiki + 读 GET /v1/export/wiki/pages/{path}。

前端「保存到 wiki」→ POST /v1/export/wiki → wiki_export_service 调 wiki /v1/pages；
前端「从 wiki 拉取」→ GET /v1/export/wiki/pages/{path} → wiki_read_service 调 wiki GET。
走 REST（用户手动操作），不走 MCP（MCP 是 Agent 工具通道）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agent.services.wiki_export_service import WikiExportError, export_to_wiki
from src.agent.services.wiki_read_service import (
    WikiPageNotFoundError,
    get_page_from_wiki,
)

router = APIRouter(prefix="/v1/export", tags=["export"])


class WikiExportRequest(BaseModel):
    """导出到 wiki 请求。"""

    path: str = Field(..., min_length=1, max_length=200, description="wiki 页面路径")
    content: str = Field(..., description="页面正文（Markdown）")
    title: str | None = Field(default=None, max_length=200, description="页面标题（缺省用 path）")
    page_type: str | None = Field(default=None, description="页面类型（可选）")


@router.post("/wiki")
async def export_wiki(req: WikiExportRequest) -> dict:
    """导出内容到 wiki 知识库。

    Returns:
        {"status": "ok", "path": str}

    Raises:
        HTTPException: 400 内容为空；502 wiki 不可达/写入失败
    """
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="内容为空，无法导出")
    try:
        result = await export_to_wiki(
            req.path, req.content, req.title, req.page_type
        )
    except WikiExportError as exc:
        # 不可达（可重试）→ 502；写入失败 → 502（前端提示）
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok", "path": result.get("path") or req.path}


@router.get("/wiki/pages/{page_path:path}")
async def read_wiki_page(page_path: str) -> dict:
    """读取 wiki 页面（双向链路读方向，2026-08-13）。

    Returns:
        {"status": "ok", "page": {"path", "title", "content", "page_type", "tags"}}

    Raises:
        HTTPException: 404 页面不存在；502 wiki 不可达/读取失败
    """
    try:
        page = await get_page_from_wiki(page_path)
    except WikiPageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WikiExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok", "page": page}
