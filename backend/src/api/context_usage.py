"""上下文用量查询（2026-08-04 评审改版：TokenUsageMiddleware 存库 → 前端查表）。

- 写入方：TokenUsageMiddleware.aafter_agent（图执行完自动算全量 messages token
  写入 sessions.context_used）
- 本接口只读：前端 ContextUsage 组件拉取渲染（当前使用 / 上限）
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.agent.middlewares.token_usage import DEFAULT_CONTEXT_WINDOW
from src.api.error_handlers import api_error
from src.db import connection as db_conn
from src.db import session_repo

router = APIRouter(prefix="/v1/context-usage", tags=["context-usage"])


@router.get("")
async def get_context_usage(session_id: str = Query(..., description="会话 ID")):
    """查询指定会话的上下文用量。

    Returns:
        {"session_id": ..., "used": int, "total": int, "percent": float}
        used 为 TokenUsageMiddleware 上次图执行后落库的累计值；未执行过为 0

    Raises:
        HTTPException(404): 会话不存在（SESSION_NOT_FOUND）
    """
    async with db_conn.connection() as conn:
        # SQL 下沉 `db/`（2026-10-16 B5）：本查询与 chat.py 的 done 事件同源
        used = await session_repo.find_context_used(conn, session_id)

    if used is None:
        raise api_error(404, "SESSION_NOT_FOUND", "会话不存在")

    total = DEFAULT_CONTEXT_WINDOW
    return {
        "session_id": session_id,
        "used": used,
        "total": total,
        "percent": round(used / total * 100, 2),
    }
