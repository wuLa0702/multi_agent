"""FastAPI 入口：lifespan 连接管理 + CORS + 路由注册。

分层（规则 06 §2）：api → agent → 能力层 → db/，禁止反向依赖。
- lifespan 启动：PG 连接池 + 建表 + Redis 预热（失败不阻断——health 降级标记）
- lifespan 启动：模型注册表 + MCP 客户端加载（失败不阻断——降级）
- lifespan 关闭：释放 Redis 连接池 / PG 连接池
- /mcp：ASGI 中间件转发 FastMCP http_app（见 McpMountMiddleware 说明）

启动：uvicorn src.api.main:app --reload --port 8010
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.chat import router as chat_router
from src.api.cost import router as cost_router
from src.api.context_usage import router as context_usage_router
from src.api.error_handlers import install_error_handlers
from src.api.export import router as export_router
from src.api.health import router as health_router
from src.api.mcp_servers import router as mcp_servers_router
from src.api.providers import router as providers_router
from src.api.sessions import router as sessions_router
from src.api.settings import router as settings_router
from src.api.skills import router as skills_router
from src.api.uploads import router as uploads_router
from src.db import audit_repository
from src.db import connection as db_conn
from src.core import audit_stream
from src.core.audit import bind_context, install_sink
from src.core.config import settings
from src.agent.main_agent import (
    close_checkpointer,
    close_store,
    init_checkpointer,
    init_store,
)
from src.agent.memory.queue import (
    _WORKER_COUNT,
    memory_task_queue,
)
from src.agent.memory.agent import build_memory_agent
from src.llm.adapter import get_chat_model
from src.core.logging import setup_logging
from src.core.model_registry import get_registry
from src.core.redis import close_redis, get_redis
from src.tools.channels.mcp_client import get_mcp_client_manager
from src.tools.channels.mcp_meta import load_policies as load_mcp_policies
from src.tools.channels.mcp_server import mcp as mcp_server

# 日志配置（UTF-8 + 双滚动 + 2 周保留，见 .claude/rules/04-logging.md）
setup_logging()


# FastMCP http_app 实例（middleware 转发 + lifespan 执行共用同一个）
_mcp_http_app = mcp_server.http_app()

# 记忆抽取队列 worker 任务句柄（lifespan 管理）
_memory_workers: list[asyncio.Task] = []


async def _memory_consumer(task) -> str:
    """队列消费：ainvoke memory_agent（工具内部 get_store() 运行时解析，方案 B）。

    Args:
        task: MemoryTask（对话历史 + session_id）

    Returns:
        抽取结果摘要（供队列 audit 记录）
    """
    from src.core.config import settings

    # 模型策略（用户拍板 2026-08-05）：memory_agent_model 空 → 主模型兜底
    agent = build_memory_agent(get_chat_model(model_id=None))
    result = await agent["runnable"].ainvoke(
        {
            "messages": [
                {"role": "user", "content": task.user_message},
                {"role": "assistant", "content": task.assistant_text},
            ]
        }
    )
    return str(result)[:200]


async def start_memory_queue() -> None:
    """启动记忆队列（lifespan 启动调用）：create_task × _WORKER_COUNT 多 worker。

    ⚠️ 不能 await run_worker（常驻循环会阻塞启动）——create_task 后台运行。
    """
    for _ in range(_WORKER_COUNT):
        _memory_workers.append(
            asyncio.create_task(memory_task_queue.run_worker(_memory_consumer))
        )


async def stop_memory_queue() -> None:
    """关闭记忆队列（lifespan 关闭调用）：先 join 再 cancel（优雅停止）。

    用户拍板（2026-08-05）：接受关闭时丢弃未处理任务（demo 个人版——
    记忆旁路、幂等去重保证下轮不重复写）。
    """
    await memory_task_queue._queue.join()   # 等当前处理中的任务完成
    for worker in _memory_workers:
        worker.cancel()
    _memory_workers.clear()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动预热 Redis + Checkpointer + 加载注册表/MCP；关闭释放连接池。"""
    try:
        await get_redis().ping()
    except Exception:  # noqa: BLE001 - 启动预热降级：本地没 Redis 也能起，/v1/health 标记 disconnected
        pass

    # PG 连接池（全项目唯一连接出口）+ 建表：必须最先，后续 checkpointer /
    # 注册表加载都依赖它（业务表所在 schema 由此建立）
    await db_conn.init_pool()
    await db_conn.ensure_schema()

    # Checkpointer 断点持久化（P0）+ Store 长期记忆（P1）：生命周期随进程
    await init_checkpointer()
    await init_store()

    # 记忆抽取队列（memory_agent 后台任务）：多 worker 并发常驻
    # （方案 §7.6：启动 create_task ×N 不 await；关闭先 join 再 cancel）
    await start_memory_queue()

    # 审计双写第二路（2026-10-16 设计 §5）：装投递 sink + 起消费 worker
    # ⚠️ 顺序：先确保消费组存在，再装 sink（否则先投递的消息无组可读）
    audit_task: asyncio.Task | None = None
    audit_retention_task: asyncio.Task | None = None
    if settings.audit_stream_enabled:
        try:
            await asyncio.to_thread(audit_stream.ensure_group)
            install_sink(audit_stream.stream_sink)
            if settings.audit_worker_mode == "embedded":
                audit_task = asyncio.create_task(
                    audit_stream.run_worker(_audit_insert), name="audit-worker"
                )
            audit_retention_task = asyncio.create_task(
                audit_stream.run_retention_loop(_audit_purge), name="audit-retention"
            )
            logging.info(
                "审计双写已启用（worker_mode=%s）", settings.audit_worker_mode
            )
        except Exception:  # noqa: BLE001 —— 降级：审计仍写 JSONL（底账不受影响）
            logging.exception("审计双写启动失败——降级为只写 JSONL（可事后重放追平）")

    # FastMCP 要求：父 ASGI 应用执行其 lifespan（初始化 session manager task group）
    async with _mcp_http_app.lifespan(_):
        # 模型注册表 + MCP 客户端 + MCP 治理元数据：seed + 加载
        # （失败不阻断——降级为仅内部工具）
        # ⚠️ 治理元数据必须在此**预加载**：get_agent/_build_agent 是同步函数，
        #    装配时读不到异步 DB（见 tools/channels/mcp_meta.py §为什么是"缓存"）
        try:
            async with db_conn.connection() as conn:
                await get_registry().load(conn)
                await get_mcp_client_manager().connect_all(conn)
                await load_mcp_policies(conn)
        except Exception:  # noqa: BLE001 - 加载失败降级：运行时模型回落 .env，agent 仅用内部工具
            logging.exception("注册表/MCP 加载失败——运行时模型回落 .env，agent 仅用内部工具")

        yield
    # 审计 worker 先停（在关池之前）：装 sink 卸载 → 不再投递 → 再取消 worker
    install_sink(None)
    if audit_task is not None:
        audit_task.cancel()
    if audit_retention_task is not None:
        audit_retention_task.cancel()
    await stop_memory_queue()
    await close_store()
    await close_checkpointer()
    await db_conn.close_pool()
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

# 错误响应统一收口（2026-10-16，见 docs/临时/2026-10-16-汇总问题-v1.md B1/B4）：
# 把 HTTPException / Pydantic 校验失败 / 未捕获异常都归一为**扁平** ErrorResponse。
# ⚠️ 必须在首次请求前注册（Starlette 首次请求后冻结中间件栈）。
install_error_handlers(app)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(cost_router)
app.include_router(providers_router)
app.include_router(sessions_router)
app.include_router(skills_router)
app.include_router(mcp_servers_router)
app.include_router(settings_router)
app.include_router(uploads_router)
app.include_router(context_usage_router)
app.include_router(export_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> str:
    """根路径友好页（2026-08-12 提升易用性）：API 入口 + 前端地址，替代裸 404。"""
    return """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>multi-agent · API</title>
<style>body{font-family:system-ui;max-width:720px;margin:48px auto;padding:0 20px;color:#333}
a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}
.card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 20px;margin:12px 0}
code{background:#eef2f7;padding:1px 5px;border-radius:4px}</style></head>
<body>
<h1>🕸️ multi-agent API</h1>
<p>后端 FastAPI 已启动。以下入口：</p>
<div class="card"><b>🖥️ 前端页面</b>（完整 UI，推荐）<br>
<a href="http://localhost:5176">http://localhost:5176</a>
<span style="color:#94a3b8">（若打不开，运行 <code>scripts/dev.sh</code> 或 <code>dev-restart.sh</code> 会自动拉起）</span></div>
<div class="card"><b>📚 API 文档</b>（Swagger 交互式）<br><a href="/docs">/docs</a></div>
<div class="card"><b>❤️ 健康检查</b><br><a href="/v1/health">/v1/health</a></div>
<p style="color:#94a3b8;font-size:13px">REST 接口统一 <code>/v1/</code> 前缀（providers/sessions/skills/cost/settings…）。</p>
</body></html>"""


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


async def _audit_insert(record: dict) -> bool:
    """审计 worker 的入库回调：一行事件 → PG（幂等）。

    每条开一次连接（从池借出，非新建）。审计属低频事件（估算 < 1 万条/天），
    该开销可忽略——**不做批量攒批**是刻意的：攒批会让"崩溃丢失的窗口"变大。

    Args:
        record: 扁平审计行

    Returns:
        True = 新插入；False = 幂等跳过（同 `(trace_id, seq)` 已存在）
    """
    async with db_conn.connection() as conn:
        return await audit_repository.insert_event(conn, record)


#: 保留期分档（设计稿 B4.1）：安全/审批类长期（追责），读类短
_AUDIT_RETENTION_DAYS: dict[str, int] = {
    "security": 365 * 3,
    "hitl": 365 * 3,
    "tool_call": 365,
    "file_access": 365,
    "api": 365,
    "sandbox": 90,
    "memory_agent": 90,
}


async def _audit_purge() -> int:
    """按 layer 分档清理过期审计（保留任务调用）。

    Returns:
        删除行数合计
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    removed = 0
    async with db_conn.connection() as conn:
        for layer, days in _AUDIT_RETENTION_DAYS.items():
            removed += await audit_repository.delete_before(
                conn, now - timedelta(days=days), (layer,)
            )
    if removed:
        logging.info("审计保留清理：删除 %d 条过期事件", removed)
    return removed


def _incoming_trace_id(scope: dict) -> str:
    """从请求头取 `X-Trace-Id`；无则生成 UUID4。

    Args:
        scope: ASGI scope（headers 是原始 bytes 键值对）

    Returns:
        透传的 trace_id 或新生成的
    """
    for key, value in scope.get("headers") or []:
        if key.lower() == b"x-trace-id":
            incoming = value.decode("latin-1").strip()
            if incoming:
                return incoming
    return str(uuid.uuid4())


class TraceIdMiddleware:
    """请求入口中间件：为每个 HTTP 请求绑定审计 `trace_id`（设计稿 §4.1）。

    规则：
    - 请求头带 `X-Trace-Id` → **复用**（跨系统串联：前端 / 网关 / 其他服务传下来）
    - 未带 → 生成 UUID4
    - 绑定进 ContextVar（`core.audit.bind_context`）→ 本请求内所有 `emit()` 自动带上，
      请求内派生的子任务（`create_task`）**自动继承**

    ⚠️ **纯 ASGI 中间件**（与 `McpMountMiddleware` 同款），不用 FastAPI 的
    `BaseHTTPMiddleware`——后者会再包一层 anyio task group，多一层任务边界，
    **contextvar 的传播语义反而绕**；直接调内层 app 保留原始执行上下文。

    ⚠️ **长驻消费者（记忆 worker）不适用**：worker 在进程启动时创建，取不到请求
    上下文 → 那条路必须**随消息显式携带** trace_id（见设计稿 §4.2）。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # websocket / lifespan 不绑（无"请求"语义）
            await self.app(scope, receive, send)
            return
        bind_context(_incoming_trace_id(scope))
        await self.app(scope, receive, send)


# 审计贯穿：请求入口绑定 trace_id
# ⚠️ 注册顺序：`add_middleware` 是**后加的先执行**（Starlette 由外向内包裹），
#    故放在 McpMount 之后 → 先绑 trace，覆盖**全部**请求（含转发给 MCP 的那条）
app.add_middleware(TraceIdMiddleware)
