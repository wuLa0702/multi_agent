"""FastAPI 入口：lifespan 连接管理 + CORS + 路由注册。

架构（12-backend.md）：api → core → {db, llm, mcp, sandbox}，禁止反向依赖。
- lifespan 启动：Redis 连接预热（失败不阻断——health 降级标记）
- lifespan 关闭：释放 Redis 连接池
- SQLite 惰性按请求开连接（单文件库，无常驻连接）

启动：uvicorn src.api.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.health import router as health_router
from src.core.config import settings
from src.core.redis import close_redis, get_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动预热 Redis 连接（失败仅日志降级），关闭时释放连接池。"""
    try:
        await get_redis().ping()
    except Exception:
        pass  # 本地没 Redis 也能起，/v1/health 会标记 disconnected
    yield
    await close_redis()


app = FastAPI(
    title="multi-agent",
    description="多 Agent 系统：deepagents 主线 + LangGraph 演进预留",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
