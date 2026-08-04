"""上下文用量查询（2026-08-04 评审改版：TokenUsageMiddleware 存库 → 前端查表）。

- 写入方：TokenUsageMiddleware.aafter_agent（图执行完自动算全量 messages token
  写入 sessions.context_used）
- 本接口只读：前端 ContextUsage 组件拉取渲染（当前使用 / 上限）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.agent.token_middleware import DEFAULT_CONTEXT_WINDOW
from src.core import db as core_db

router = APIRouter(prefix="/v1/context-usage", tags=["context-usage"])


@router.get("")
async def get_context_usage(session_id: str = Query(..., description="会话 ID")):
    """查询指定会话的上下文用量。

    Returns:
        {"session_id": ..., "used": int, "total": int, "percent": float}
        used 为 TokenUsageMiddleware 上次图执行后落库的累计值；未执行过为 0
    """
    conn = await core_db.get_connection()
    try:
        cursor = await conn.execute(
            "SELECT context_used FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
    finally:
        await conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail={
            "error": "ErrorResponse", "detail": "会话不存在", "code": "SESSION_NOT_FOUND",
        })

    used = row["context_used"] or 0
    total = DEFAULT_CONTEXT_WINDOW
    return {
        "session_id": session_id,
        "used": used,
        "total": total,
        "percent": round(used / total * 100, 2),
    }
