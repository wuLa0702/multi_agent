"""FastAPI 入口：lifespan 连接管理 + CORS + 路由注册。

架构（12-backend.md）：api → core → {db, llm, mcp, sandbox}，禁止反向依赖。
- lifespan 启动：Redis 连接预热（失败不阻断——health 降级标记）
- lifespan 启动：模型注册表 + MCP 客户端加载（失败不阻断——降级）
- lifespan 关闭：释放 Redis 连接池
- SQLite 惰性按请求开连接（单文件库，无常驻连接）
- /mcp：ASGI 中间件转发 FastMCP http_app（见 McpMountMiddleware 说明）

启动：uvicorn src.api.main:app --reload --port 8010
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.chat import router as chat_router
from src.api.health import router as health_router
from src.api.mcp_servers import router as mcp_servers_router
from src.api.providers import router as providers_router
from src.api.sessions import router as sessions_router
from src.api.settings import router as settings_router
from src.api.skills import router as skills_router
from src.api.uploads import router as uploads_router
from src.core import db as core_db
from src.core.config import settings
from src.core.logging import setup_logging
from src.core.model_registry import get_registry
from src.core.redis import close_redis, get_redis
from src.mcp.client import get_mcp_client_manager
from src.mcp.server import mcp as mcp_server

# 日志配置（UTF-8 + 双滚动 + 2 周保留，见 .claude/rules/04-logging.md）
setup_logging()


# FastMCP http_app 实例（middleware 转发 + lifespan 执行共用同一个）
_mcp_http_app = mcp_server.http_app()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动预热 Redis + 加载注册表/MCP；关闭释放连接池。"""
    try:
        await get_redis().ping()
    except Exception:
        pass  # 本地没 Redis 也能起，/v1/health 会标记 disconnected

    # FastMCP 要求：父 ASGI 应用执行其 lifespan（初始化 session manager task group）
    async with _mcp_http_app.lifespan(_):
        # 模型注册表 + MCP 客户端：seed + 加载（失败不阻断——降级为仅内部工具）
        conn = await core_db.get_connection()
        try:
            await get_registry().load(conn)
            await get_mcp_client_manager().connect_all(conn)
        except Exception:
            logging.exception("注册表/MCP 加载失败——运行时模型回落 .env，agent 仅用内部工具")
        finally:
            await conn.close()

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
app.include_router(chat_router)
app.include_router(providers_router)
app.include_router(sessions_router)
app.include_router(skills_router)
app.include_router(mcp_servers_router)
app.include_router(settings_router)
app.include_router(uploads_router)


class McpMountMiddleware:
    """把 /mcp* 请求转发给 FastMCP http_app（暴露内部工具给外部 Agent）。

    不用 app.mount() 的原因：Starlette Mount 对无尾斜杠路径 307 到带斜杠
    （/mcp → /mcp/），而 MCP 客户端 httpx follow_redirects=False 不跟随、
    FastMCP 内部路由又只认无斜杠 /mcp——双向都不通。ASGI 转发保持
    path=/mcp 直进 http_app，无重定向。
    """

    def __init__(self, app: ASGIApp, mcp_app: ASGIApp) -> None:
        self.app = app
        self.mcp_app = mcp_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            await self.mcp_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)


# MCP Server：暴露内部工具（internet_search / run_code_in_sandbox）给外部 Agent
app.add_middleware(McpMountMiddleware, mcp_app=_mcp_http_app)
