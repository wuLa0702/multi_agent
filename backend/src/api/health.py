"""健康检查：GET /v1/health。

验收点（方案-后端基础架构-v1 §3.3）：只验证地基（Redis + PostgreSQL），
不依赖 LLM / 沙箱。任一断开 → 对应字段 disconnected、status=degraded，
但服务照常响应（HTTP 200）——本地没 Redis 也能开发。

2026-10-15 PG 迁移：探活对象 SQLite → PostgreSQL；响应字段 `sqlite` 更名
`database`（前端 types.ts 同步）——字段名不绑实现，以后再换库不必再动契约。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import settings
from src.core.redis import get_redis
from src.db import connection as db_conn

router = APIRouter(prefix="/v1", tags=["health"])


class HealthResponse(BaseModel):
    """健康检查响应体（API 规范：响应含 status 字段）。"""

    status: str = "ok"  # ok / degraded
    redis: str = "connected"  # connected / disconnected
    database: str = "connected"  # connected / disconnected（PostgreSQL）
    env: str = "dev"  # 当前运行环境


@router.get(
    "/health", response_model=HealthResponse, summary="健康检查：Redis + PostgreSQL 探活"
)
async def health() -> HealthResponse:
    """Redis ping + PG 探活（SELECT 1）；断开只降级标记，不抛异常。"""
    # Redis 探活（连接池可能未就绪 → ping 自会建连）
    redis_status = "connected"
    try:
        await get_redis().ping()
    except Exception:  # noqa: BLE001 - 探活失败只降级标记，不抛（health 语义）
        redis_status = "disconnected"

    # PG 探活（从连接池借连接 + SELECT 1，退出自动归还）
    database_status = "connected"
    try:
        async with db_conn.connection() as conn:
            await conn.execute("SELECT 1")
    except Exception:  # noqa: BLE001 - 探活失败只降级标记，不抛（health 语义）
        database_status = "disconnected"

    return HealthResponse(
        status=(
            "ok"
            if redis_status == "connected" and database_status == "connected"
            else "degraded"
        ),
        redis=redis_status,
        database=database_status,
        env=settings.app_env,
    )
