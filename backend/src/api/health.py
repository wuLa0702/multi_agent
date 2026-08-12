"""健康检查：GET /v1/health。

验收点（方案-后端基础架构-v1 §3.3）：只验证地基（Redis + SQLite），
不依赖 LLM / 沙箱。任一断开 → 对应字段 disconnected、status=degraded，
但服务照常响应（HTTP 200）——本地没 Redis 也能开发。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.core import db as core_db
from src.core.config import settings
from src.core.redis import get_redis

router = APIRouter(prefix="/v1", tags=["health"])


class HealthResponse(BaseModel):
    """健康检查响应体（API 规范：响应含 status 字段）。"""

    status: str = "ok"  # ok / degraded
    redis: str = "connected"  # connected / disconnected
    sqlite: str = "connected"  # connected / disconnected
    env: str = "dev"  # 当前运行环境


@router.get("/health", response_model=HealthResponse, summary="健康检查：Redis + SQLite 探活")
async def health() -> HealthResponse:
    """Redis ping + SQLite 探活；断开只降级标记，不抛异常。"""
    # Redis 探活（连接池可能未就绪 → ping 自会建连）
    redis_status = "connected"
    try:
        await get_redis().ping()
    except Exception:  # noqa: BLE001 - 探活失败只降级标记，不抛（health 语义）
        redis_status = "disconnected"

    # SQLite 探活（惰性开连接 + SELECT 1，用完即关）
    sqlite_status = "connected"
    try:
        conn = await core_db.get_connection()
        await conn.execute("SELECT 1")
        await conn.close()
    except Exception:  # noqa: BLE001 - 探活失败只降级标记，不抛（health 语义）
        sqlite_status = "disconnected"

    return HealthResponse(
        status="ok" if redis_status == "connected" and sqlite_status == "connected" else "degraded",
        redis=redis_status,
        sqlite=sqlite_status,
        env=settings.app_env,
    )
