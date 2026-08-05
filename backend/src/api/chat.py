"""流式对话：POST /v1/chat/stream（SSE，项目核心接口）。

契约：方案-后端接口定义-v1 §5。
- 事件流：start → token×N → done / error（首事件 start，尾事件二选一）
- 请求校验：message 与 resume_run_id 互斥（resume 为 P0 断点真恢复）
- 持久化：user 消息先落库，assistant 全文聚合后落库（token 流不落库）

2026-08-04 拆分（过程中优化记录）：
- chat_stream 171 行 → 拆出 _resolve_session（会话创建/校验）
- event_stream 132 行 → 拆出 _prepare_new_messages（新消息准备）/
  _build_error_event（错误事件）/ _save_memory_in_background（记忆后台写入）
- 记忆写入移出 SSE 流（asyncio.create_task）：done 事件不被额外 LLM 调用拖慢
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agent.main_agent import (
    ChatContext,
    build_agent,
    stream_agent_events,
    stream_agent_tokens,
)
from src.core import db as core_db
from src.core.config import settings
from src.core.errors import RetryableError
from src.core.model_registry import get_registry
from src.schemas.events import (
    DoneEvent,
    ErrorEvent,
    StartEvent,
    SubagentEvent,
    TokenEvent,
    ToolCallEvent,
)
from src.schemas.message import Message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatStreamRequest(BaseModel):
    """流式对话请求体（契约 §5.1 + 2026-08-04 P1 代理模式）。"""

    session_id: str | None = Field(default=None, description="会话 ID；None → 自动新建")
    message: str | None = Field(default=None, description="新消息模式：用户输入")
    resume_run_id: str | None = Field(default=None, description="恢复模式：审批后携带 run_id 重连")
    model_id: int | None = Field(
        default=None,
        description="数据库模型 ID（GET /v1/providers 查询）；None=默认模型",
    )
    mode: str = Field(
        default="default",
        description="代理模式：default/plan/agent/auto（2026-08-04 P1，先浅后深——仅提示词注入）",
    )


class ErrorResponse(BaseModel):
    """统一错误响应（契约 §3.3）。"""

    error: str
    detail: str
    code: str


# ── 辅助函数（2026-08-04 拆分：每个 <80 行，职责单一）──

def _history_to_langchain(history: list[Message]) -> list[BaseMessage]:
    """DB 历史消息 → LangChain 消息列表（tool 消息后续阶段支持）。"""
    lc_messages: list[BaseMessage] = []
    for m in history:
        if m.role == "user":
            lc_messages.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            lc_messages.append(AIMessage(content=m.content))
        # system/tool 消息当前阶段跳过（契约后续阶段接入）
    return lc_messages


def _validate_request(req: ChatStreamRequest) -> None:
    """请求阶段校验（互斥约束，契约 §5.1）；失败抛 HTTPException(400)。"""
    if req.message and req.resume_run_id:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="参数冲突",
                detail="message 与 resume_run_id 互斥，只能提供其一",
                code="BAD_REQUEST",
            ).model_dump(),
        )
    if not req.message and not req.resume_run_id:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="参数缺失",
                detail="message 或 resume_run_id 至少提供一个",
                code="BAD_REQUEST",
            ).model_dump(),
        )
    if req.model_id is not None and get_registry().get_model(req.model_id) is None:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="参数非法",
                detail=f"model_id={req.model_id} 不存在，请先 GET /v1/providers 查询可用模型",
                code="BAD_REQUEST",
            ).model_dump(),
        )
    if req.resume_run_id and not req.session_id:
        # 审批断点恢复（P0 真实现）：resume 必须带 session_id（== thread_id，
        # checkpoint 按执行线隔离，计划文档 A.3）
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="参数缺失",
                detail="resume_run_id（审批断点恢复）必须同时提供 session_id",
                code="BAD_REQUEST",
            ).model_dump(),
        )


async def _resolve_session(conn, req: ChatStreamRequest) -> str:
    """建/取会话（session_id=None 自动新建；指定则校验存在）。

    Returns:
        会话 ID

    Raises:
        HTTPException(404): 指定会话不存在（SESSION_NOT_FOUND）
    """
    from src.db import repository as repo

    session_id = req.session_id or str(uuid.uuid4())
    if req.session_id is None:
        await repo.create_session(conn, session_id)
    elif await repo.get_session(conn, session_id) is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="会话不存在",
                detail=f"session_id={session_id} 未找到",
                code="SESSION_NOT_FOUND",
            ).model_dump(),
        )
    return session_id


async def _prepare_new_messages(
    conn, repo, req: ChatStreamRequest, session_id: str
) -> list[BaseMessage]:
    """新消息模式准备：user 落库 + 自动标题 + 组历史 + 模式/记忆注入。

    Returns:
        LangChain 消息列表（含注入的 SystemMessage）
    """
    # 1. user 消息落库
    await repo.append_message(
        conn, Message(session_id=session_id, role="user", content=req.message or "")
    )

    # 1.5 自动标题（2026-08-04 升级：LLM 后台生成，不拖慢 SSE start——
    #     首条消息时触发后台任务，LLM 失败回退规则截断）
    session_row = await repo.get_session(conn, session_id)
    if session_row is not None and session_row.title == "新会话":
        asyncio.create_task(_generate_title_in_background(session_id, req.message or ""))

    # 2. 组历史（含本条 user 消息）→ LangChain 格式
    history = await repo.list_messages(conn, session_id, limit=200)
    lc_messages = _history_to_langchain(history)

    # 2.5 代理模式注入（P1 先浅后深：仅请求级 SystemMessage）
    if req.mode != "default":
        from src.agent.main_agent import _MODE_INSTRUCTIONS

        instruction = _MODE_INSTRUCTIONS.get(req.mode)
        if instruction:
            lc_messages = [SystemMessage(content=instruction), *lc_messages]

    # 2.6 长期记忆注入（P1 Store）：取最近记忆拼 SystemMessage（失败静默降级）
    from src.agent.main_agent import get_store
    from src.agent.memory_store import load_recent_memories

    memories = await load_recent_memories(get_store())
    if memories:
        memory_text = "以下是你的长期记忆（供参考，可能与本对话无关）：\n" + "\n".join(memories)
        lc_messages = [SystemMessage(content=memory_text), *lc_messages]
    return lc_messages


def _build_error_event(is_resume: bool, exc: Exception) -> dict[str, str]:
    """流内错误 → SSE error 事件（resume 校验兜底 RESUME_NOT_FOUND）。"""
    if is_resume:
        # 计划文档 A.5：checkpoint 无效/不属于该 thread → 友好错误（前端提示可重开）
        return {
            "data": ErrorEvent(
                code="RESUME_NOT_FOUND",
                detail=f"断点已失效（{type(exc).__name__}），请重新开始对话",
                retryable=False,
            ).model_dump_json()
        }
    retryable = isinstance(exc, RetryableError)
    return {
        "data": ErrorEvent(
            code="LLM_UNAVAILABLE" if retryable else "INTERNAL",
            detail=str(exc)[:500],
            retryable=retryable,
        ).model_dump_json()
    }


async def _generate_title_in_background(session_id: str, first_message: str) -> None:
    """后台生成会话标题（LLM → 回退截断；fire-and-forget，异常内部捕获）。

    2026-08-04 升级：标题从规则截断改为 LLM 生成（统一走 LLMAdapter，
    见 agent/assistant_tasks.py），后台执行不拖慢 SSE start；失败 → 回退消息前 20 字。
    """
    from src.agent.assistant_tasks import generate_title

    title = None
    try:
        title = await generate_title(None, first_message)  # None → 默认 LLMAdapter()
    except Exception:  # noqa: BLE001 —— 标题生成失败回退截断
        logger.warning("标题 LLM 生成失败，回退规则截断")
    if not title:
        title = first_message.strip().replace("\n", " ")[:20]
    if not title:
        return

    conn = await core_db.get_connection()
    try:
        from src.db import repository as repo

        await repo.update_session_title(conn, session_id, title)
    finally:
        await conn.close()


async def _save_memory_in_background(
    user_message: str, assistant_text: str, *, turn_count: int = 0
) -> None:
    """后台写记忆（v3 类型化链路）：LLM 抽取 {type, fact} → 类型化落库 + 任务归档检查。

    2026-08-04 优化（过程中优化记录）：记忆写入移出 SSE 流——done 事件
    不被额外 LLM 抽取调用拖慢；本函数内部全部容错，不冒泡。
    v3.1（2026-08-05）：短对话（turn_count < 2）跳过抽取省 token；
    会话结束顺手检查任务归档（开销可忽略）。
    """
    from src.agent.main_agent import get_store
    from src.agent.memory_store import (
        archive_completed_tasks,
        extract_memory_typed,
        save_typed_memory,
    )
    from src.core.backend import create_backend

    try:
        entry = await extract_memory_typed(
            user_message, assistant_text, turn_count=turn_count
        )
        if entry:
            await save_typed_memory(get_store(), entry["type"], entry["fact"])
        # v3.1 归档触发：会话结束顺手检查（tasks.md 全局共享，default backend 即可）
        await archive_completed_tasks(create_backend("default"))
    except Exception:  # noqa: BLE001 —— 记忆是旁路能力，失败不影响对话
        logger.exception("记忆后台任务失败（不影响对话）")


async def _event_stream(
    req: ChatStreamRequest,
    session_id: str,
    run_id: str,
    started_at: float,
) -> AsyncIterator[dict[str, str]]:
    """SSE 事件生成器（模块级，独立可测）：start → token×N → done/error。

    resume 模式（P0 断点恢复）：checkpoint 状态接管——不落库 user 消息、
    不注入模式指令、输入传空列表；从 checkpoint_id 快照继续执行。
    """
    conn = await core_db.get_connection()
    try:
        from src.db import repository as repo

        is_resume = bool(req.resume_run_id)

        # 准备输入消息（新消息模式 vs resume 模式）
        lc_messages = (
            []
            if is_resume
            else await _prepare_new_messages(conn, repo, req, session_id)
        )

        # start 事件（resume 带 resumed=true，前端保留挂起前节点）
        yield {
            "data": StartEvent(
                run_id=run_id, session_id=session_id, resumed=is_resume
            ).model_dump_json()
        }

        # Agent 流式执行（异常统一转 error 事件）
        try:
            agent = build_agent(thread_id=session_id)  # 会话级缓存（v2.0：文件根绑会话）
            chat_context = ChatContext(model_id=req.model_id, mode=req.mode, session_id=session_id)
            full_text_parts: list[str] = []
            if settings.event_stream_v3:
                # 事件流增强（2026-08-05 引入方案 P0）：token + tool_call + subagent
                # 三类事件分发（契约 v3 定稿事件落地）；token 仍逐 chunk（打字机效果）
                async for event in stream_agent_events(
                    agent,
                    lc_messages,
                    context=chat_context,
                    checkpoint_id=req.resume_run_id,
                ):
                    if event["type"] == "token":
                        full_text_parts.append(event["text"])
                        yield {"data": TokenEvent(text=event["text"]).model_dump_json()}
                    elif event["type"] == "tool_call":
                        yield {"data": ToolCallEvent(**event).model_dump_json()}
                    elif event["type"] == "subagent":
                        yield {"data": SubagentEvent(**event).model_dump_json()}
            else:
                # v2 现状：仅 token 流（默认，零行为变化）
                async for text in stream_agent_tokens(
                    agent,
                    lc_messages,
                    context=chat_context,
                    checkpoint_id=req.resume_run_id,  # resume 模式：从精确快照继续
                ):
                    full_text_parts.append(text)
                    yield {"data": TokenEvent(text=text).model_dump_json()}
        except Exception as exc:  # noqa: BLE001 - 流内错误统一转 error 事件
            yield _build_error_event(is_resume, exc)
            return

        # assistant 全文落库
        assistant_text = "".join(full_text_parts)
        await repo.append_message(
            conn,
            Message(session_id=session_id, role="assistant", content=assistant_text),
        )

        # 长期记忆后台写入（v3 类型化：LLM 抽取 {type, fact} + 任务归档检查；
        # done 前触发不等待——2026-08-04 优化）
        if not is_resume and assistant_text:
            # v3.1：turn_count = 历史消息轮次（user+assistant 成对）——短对话跳过抽取
            asyncio.create_task(
                _save_memory_in_background(
                    req.message or "", assistant_text,
                    turn_count=len(lc_messages) // 2,
                )
            )

        # done 事件（流内异常时不发）；context_used 查库（TokenUsageMiddleware
        # 在 token 流结束时已落库，此处取最新值带给前端 store 同步）
        duration_ms = int((time.monotonic() - started_at) * 1000)
        cur = await conn.execute(
            "SELECT context_used FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cur.fetchone()
        yield {
            "data": DoneEvent(
                run_id=run_id,
                session_id=session_id,
                duration_ms=duration_ms,
                context_used=row["context_used"] if row else None,
            ).model_dump_json()
        }
    finally:
        await conn.close()


# ── 主接口 ──

@router.post("/stream", summary="流式对话（SSE 核心接口）")
async def chat_stream(req: ChatStreamRequest) -> EventSourceResponse:
    """新消息/断点恢复驱动 Agent 执行，SSE 事件流推送过程与结果。

    Returns:
        text/event-stream：start → token×N → done（或 error）
    """
    _validate_request(req)

    conn = await core_db.get_connection()
    try:
        session_id = await _resolve_session(conn, req)
    finally:
        await conn.close()

    run_id = str(uuid.uuid4())
    return EventSourceResponse(
        _event_stream(req, session_id, run_id, time.monotonic())
    )
