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
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sse_starlette.sse import EventSourceResponse

from src.agent.intent import classify_intent
from src.agent.main_agent import (
    ChatContext,
    build_agent,
    stream_agent_events,
    stream_agent_tokens,
)
from src.core import db as core_db
from src.core.config import settings
from src.core.errors import RetryableError
from src.core.constants import PAGINATION_LIMIT_MAX
from src.core.model_registry import get_registry
from src.schemas.events import (
    ApproveEvent,
    CostAlertEvent,
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


class ApproveRequest(BaseModel):
    """审批决策请求体（P0 HITL 设计 §5.3：对齐前端 ApproveRequest 契约 + 透传扩展）。

    Attributes:
        run_id: chat.py 流 run_id（approve 事件原样回传）
        checkpoint_id: 中断点 checkpoint_id（approve 事件原样回传，resume 恢复键）
        call_id: 工具调用 id（v1.2：多 action 顺序匹配键，approve 事件原样回传）
        action: approve=批准 / reject=拒绝+note 反馈 / edit=改参数后批准 /
            respond=回答澄清问题（仅 ask_human）
        note: reject/respond 的文本（respond 时必填——人类回答）
        edited_arguments: edit 时修改后的完整参数
    """

    run_id: str = Field(description="chat.py 流 run_id")
    checkpoint_id: str = Field(description="中断点 checkpoint_id（resume 恢复键）")
    call_id: str = Field(description="工具调用 id（多 action 顺序匹配键）")
    action: Literal["approve", "reject", "edit", "respond"] = Field(
        description="审批决策类型"
    )
    note: str | None = Field(default=None, description="reject/respond 的文本")
    edited_arguments: dict[str, Any] | None = Field(
        default=None, description="edit 时修改后的完整参数"
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


async def _append_message_safe(conn, msg) -> None:
    """消息落库容错（矩阵：落库失败降级不阻断，响应正常）。

    SQLite 瞬时错误（busy/locked）或外键失败（会话未持久化=内存模式）→
    跳过落库记日志告警（消息不持久化，但对话继续）。

    Args:
        conn: SQLite 连接
        msg: Message 实体（session_id/role/content）
    """
    from src.db import session_repo as repo

    try:
        await repo.append_message(conn, msg)
    except (sqlite3.OperationalError, sqlite3.IntegrityError, RetryableError) as exc:
        logger.warning("消息落库失败（降级内存，未持久化）：role=%s %s", msg.role, exc)


async def _create_session_with_retry(conn, session_id: str) -> None:
    """会话落库（容错矩阵：SQLite 瞬时错误重试 1 次，仍失败降级内存，不阻断）。

    计划-容错处理 v1.2 §3.3：会话落库失败 → 重试 1 次 → 降级内存会话
    （仅本次请求降级，后续消息继续尝试落库；失败记日志告警）。

    Args:
        conn: SQLite 连接
        session_id: 新会话 ID
    """
    from src.db import session_repo as repo

    for attempt in (1, 2):
        try:
            await repo.create_session(conn, session_id)
            return
        except (sqlite3.OperationalError, RetryableError) as exc:
            if attempt == 1:
                logger.warning("会话落库失败重试（%s）：%s", type(exc).__name__, session_id)
                continue
            logger.error(
                "会话落库失败（降级内存会话，未持久化）：%s", session_id, exc_info=True
            )
            return  # 降级：跳过落库，session_id 继续（后续消息继续尝试落库）


async def _resolve_session(conn, req: ChatStreamRequest) -> str:
    """建/取会话（session_id=None 自动新建；指定则校验存在）。

    Returns:
        会话 ID

    Raises:
        HTTPException(404): 指定会话不存在（SESSION_NOT_FOUND）
    """
    from src.db import session_repo as repo

    session_id = req.session_id or str(uuid.uuid4())
    if req.session_id is None:
        await _create_session_with_retry(conn, session_id)
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
    # 1. user 消息落库（容错：外键/瞬时失败降级内存，不阻断）
    await _append_message_safe(
        conn, Message(session_id=session_id, role="user", content=req.message or "")
    )

    # 1.5 自动标题（2026-08-04 升级：LLM 后台生成，不拖慢 SSE start——
    #     首条消息时触发后台任务，LLM 失败回退规则截断）
    session_row = await repo.get_session(conn, session_id)
    if session_row is not None and session_row.title == "新会话":
        asyncio.create_task(_generate_title_in_background(session_id, req.message or ""))

    # 2. 组历史（含本条 user 消息）→ LangChain 格式
    history = await repo.list_messages(conn, session_id, limit=PAGINATION_LIMIT_MAX)
    lc_messages = _history_to_langchain(history)

    # 2.5 代理模式注入（P1 先浅后深：仅请求级 SystemMessage）
    if req.mode != "default":
        from src.agent.prompts import MODE_INSTRUCTIONS

        instruction = MODE_INSTRUCTIONS.get(req.mode)
        if instruction:
            lc_messages = [SystemMessage(content=instruction), *lc_messages]

    # 2.6 长期记忆注入（P1 Store）：取最近记忆拼 SystemMessage（失败静默降级）
    from src.agent.main_agent import get_store
    from src.agent.memory.store import load_recent_memories

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
    见 agent/tasks/assistant.py），后台执行不拖慢 SSE start；失败 → 回退消息前 20 字。
    """
    from src.agent.tasks.assistant import generate_title

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
        from src.db import session_repo as repo

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
    from src.agent.memory.store import (
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


async def _resolve_resume_context(
    req: ChatStreamRequest, session_id: str, conn
) -> tuple[bool, dict | None, list[BaseMessage], dict[str, str] | None]:
    """resume 分支准备：consume 待决审批 + 修订上限注入 + checkpoint 校验。

    P0 HITL 设计 §5.4：resume_run_id 命中 Redis 待决审批 → 返回 Command(resume)
    输入（消费即删）；同时注入修订上限 SystemMessage（v1.2）；伪造/过期 checkpoint
    → 返回 error 事件 dict（潜伏 bug 修复，§3.3-③ 实证）。

    Args:
        req: 流式对话请求
        session_id: 会话 ID
        conn: SQLite 连接（新消息模式组装历史用）

    Returns:
        (is_resume, resume_input, lc_messages, error_event_dict)：
        error_event_dict 非 None → 调用方直接 yield 该事件并返回
    """
    from src.db import session_repo as repo

    is_resume = bool(req.resume_run_id)
    resume_input: dict | None = None
    if is_resume:
        from src.agent.hitl.pending import consume, get_revision_count

        resume_input = await consume(req.resume_run_id)

    # 准备输入消息（新消息模式 vs resume 模式；审批恢复不落库 user 消息）
    lc_messages: list[BaseMessage] = (
        []
        if is_resume
        else await _prepare_new_messages(conn, repo, req, session_id)
    )

    # v1.2 修订上限注入：publish_report 修订计数 > settings 上限 → 提示停止
    if resume_input and settings.publish_review_max_revisions:
        revise_count = await get_revision_count(session_id)
        if revise_count > settings.publish_review_max_revisions:
            lc_messages = [
                SystemMessage(
                    content=(
                        f"报告已被拒绝修订 {revise_count} 次（上限 "
                        f"{settings.publish_review_max_revisions}）。已达修订上限："
                        "输出当前版本并停止修订，不再请求交付。"
                    )
                ),
                *lc_messages,
            ]

    # 潜伏 bug 修复（设计 §5.4）：resume 无待决审批时校验 checkpoint 有效性
    if is_resume and resume_input is None:
        from src.agent.main_agent import checkpoint_exists

        if not await checkpoint_exists(session_id, req.resume_run_id):
            error_event = {
                "data": ErrorEvent(
                    code="RESUME_NOT_FOUND",
                    detail="断点已失效（checkpoint 不存在），请重新开始对话",
                    retryable=False,
                ).model_dump_json()
            }
            return True, None, [], error_event

    return is_resume, resume_input, lc_messages, None


async def _emit_agent_events(
    agent,
    lc_messages: list[BaseMessage],
    req: ChatStreamRequest,
    session_id: str,
    resume_input: dict | None,
    run_id: str,
) -> AsyncIterator[tuple[str, dict]]:
    """Agent 事件流 → SSE 事件（token/tool_call/subagent/approve；v2 回退仅 token）。

    v3 多事件分发（2026-08-05 契约 v3）：token 走 chunk、tool_call/subagent 走
    工具/子图事件；HITL（P0 设计 §5.4/§5.5）：审批恢复 → Command(resume) 输入，
    hitl_callback 采集中断，approve 事件透传（含 checkpoint_id/call_id 原样回传）。
    v2 回退（event_stream_v3=False）：仅 token 流。

    Args:
        agent: build_agent 的产物
        lc_messages: 输入消息（新消息/resume 模式）
        req: 流式对话请求
        session_id: 会话 ID
        resume_input: Command(resume) 输入（无待决审批 → None）
        run_id: chat.py 流 run_id（approve 事件流标识）

    Yields:
        (type, event_dict)：type ∈ token/tool_call/subagent/approve
    """
    chat_context = ChatContext(model_id=req.model_id, mode=req.mode, session_id=session_id)
    if not settings.event_stream_v3:
        async for text in stream_agent_tokens(
            agent,
            lc_messages,
            context=chat_context,
            checkpoint_id=req.resume_run_id,  # resume 模式：从精确快照继续
        ):
            yield "token", {"text": text}
        return

    from langgraph.types import Command

    from src.agent.hitl.callback import HitlCallback

    graph_input = Command(resume=resume_input) if resume_input else None
    hitl_callback = HitlCallback() if settings.hitl_enabled else None
    async for event in stream_agent_events(
        agent,
        lc_messages,
        context=chat_context,
        checkpoint_id=req.resume_run_id,
        hitl_callback=hitl_callback,
        run_id=run_id,
        graph_input=graph_input,
    ):
        yield event["type"], event


async def _trigger_memory_after(
    req: ChatStreamRequest,
    session_id: str,
    assistant_text: str,
    lc_messages: list[BaseMessage],
    is_resume: bool,
) -> None:
    """会话结束记忆后台写入（done 前触发不等待，内部全容错）。

    2026-08-04 优化：记忆写入移出 SSE 流——done 不被额外 LLM 抽取调用拖慢。
    memory_agent 子代理（2026-08-05）：入队后台队列（监控/并发限制/指纹幂等）；
    降级路径：单次 LLM 抽取（turn_count<2 短对话跳过省 token）。

    Args:
        req: 流式对话请求
        session_id: 会话 ID
        assistant_text: assistant 全文
        lc_messages: 输入消息（turn_count 计算用）
        is_resume: 是否 resume（resume 不重复写记忆）
    """
    if is_resume or not assistant_text:
        return
    if settings.memory_agent_enabled:
        from src.agent.memory.agent import _fingerprint
        from src.agent.memory.queue import MemoryTask, memory_task_queue

        memory_task_queue.enqueue(
            MemoryTask(
                session_id=session_id,
                user_message=req.message or "",
                assistant_text=assistant_text,
                fingerprint=_fingerprint(session_id, req.message or "", assistant_text),
            )
        )
    else:
        # 降级路径：现状单次 LLM 抽取（extract_memory_typed 保留）
        # v3.1：turn_count = 历史消息轮次（user+assistant 成对）——短对话跳过
        asyncio.create_task(
            _save_memory_in_background(
                req.message or "", assistant_text,
                turn_count=len(lc_messages) // 2,
            )
        )


async def _fetch_latest_cost_alert(conn, session_id: str) -> dict | None:
    """取会话最新成本告警 → SSE data（无告警返回 None）。

    中间件落 cost_alerts 已去重（同阈值一次）；本函数只读最新一条。

    Args:
        conn: SQLite 连接
        session_id: 会话 ID

    Returns:
        SSE data dict（CostAlertEvent 序列化）；无告警 None
    """
    cur = await conn.execute(
        "SELECT threshold, total_cost FROM cost_alerts WHERE session_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "data": CostAlertEvent(
            session_id=session_id,
            total_cost=float(row["total_cost"]),
            threshold=float(row["threshold"]),
        ).model_dump_json()
    }


async def _build_done_event(
    conn, run_id: str, session_id: str, started_at: float
) -> DoneEvent:
    """构建 done 事件（context_used 查库 + 用量告警）。

    TokenUsageMiddleware 在 token 流结束时已落库 context_used，此处取最新值
    带给前端 store 同步；#4 用量告警（2026-08-05）：>80% 窗口 → 前端提示。

    Args:
        conn: SQLite 连接
        run_id: 本次 run 的 ID
        session_id: 会话 ID
        started_at: 流开始时间戳（耗时计算）

    Returns:
        DoneEvent 实例（调用方 model_dump_json）
    """
    duration_ms = int((time.monotonic() - started_at) * 1000)
    cur = await conn.execute(
        "SELECT context_used FROM sessions WHERE id = ?", (session_id,)
    )
    row = await cur.fetchone()
    return DoneEvent(
        run_id=run_id,
        session_id=session_id,
        duration_ms=duration_ms,
        context_used=row["context_used"] if row else None,
        context_warning=(
            row["context_used"] > 0.8 * 128_000 if row and row["context_used"] else False
        ),
    )


async def _fast_stream(
    req: ChatStreamRequest,
    run_id: str,
    session_id: str,
    started_at: float,
) -> AsyncIterator[dict[str, str]]:
    """快通道（方案 v2.1，2026-08-13）：简单问题单次 LLM 流式。

    不建 deepagents agent、不挂搜索/子代理/publish_report 工具——模型没有工具，
    天然不会过度拆解。产出 token 事件（done 由调用方 _build_done_event 补）。
    """
    from src.agent.main_agent import get_stream_semaphore
    from src.llm.adapter import get_chat_model

    model = get_chat_model()
    messages = [
        SystemMessage(
            content="你是简洁助手。问题较简单：直接给出准确、简洁的回答，不要搜索、不要拆解步骤、不要过度展开。"
        ),
        HumanMessage(content=req.message or ""),
    ]
    async with get_stream_semaphore():
        async for chunk in model.astream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                yield {"data": TokenEvent(text=text).model_dump_json()}


async def _event_stream(
    req: ChatStreamRequest,
    session_id: str,
    run_id: str,
    started_at: float,
) -> AsyncIterator[dict[str, str]]:
    """SSE 事件生成器（模块级，独立可测）：start → token×N → done/error。

    resume 模式（P0 断点恢复）：checkpoint 状态接管——不落库 user 消息、
    不注入模式指令；从 checkpoint_id 快照继续执行。审批恢复（P0 HITL 设计 §5.4）：
    resume_run_id 命中待决审批 → Command(resume) 输入（准备逻辑见 _resolve_resume_context）。

    只做编排：resume 准备 / start / 事件分发（_emit_agent_events）/ 落库 /
    记忆后台（_trigger_memory_after）/ done（_build_done_event）逐段调用。
    """
    conn = await core_db.get_connection()
    try:
        from src.db import session_repo as repo

        _cost_alert_sent = False  # 成本告警 run 内发一次（2026-08-11 成本控制 §5.6）

        # 1. resume 准备（consume 待决审批 + 修订注入 + checkpoint 校验）
        is_resume, resume_input, lc_messages, resume_err = await _resolve_resume_context(
            req, session_id, conn
        )
        if resume_err is not None:
            yield resume_err
            return

        # 2. start 事件（resume 带 resumed=true，前端保留挂起前节点）
        yield {
            "data": StartEvent(
                run_id=run_id, session_id=session_id, resumed=is_resume
            ).model_dump_json()
        }

        # 2.5 简单直连快通道（方案 v2.1，2026-08-13）：简单概念题直接 LLM 单轮流式答，
        #     不建 agent、不挂搜索/子代理工具——避免"解释 LangGraph"被过度处理
        if not is_resume and req.mode in ("default", "") and classify_intent(req.message or "") == "simple":
            async for chunk in _fast_stream(req, run_id, session_id, started_at):
                yield chunk
            yield {"data": (await _build_done_event(conn, run_id, session_id, started_at)).model_dump_json()}
            return

        # 3. Agent 流式执行（异常统一转 error 事件）
        full_text_parts: list[str] = []
        try:
            agent = build_agent(thread_id=session_id)  # 会话级缓存（v2.0：文件根绑会话）
            async for evt_type, evt in _emit_agent_events(
                agent, lc_messages, req, session_id, resume_input, run_id
            ):
                if evt_type == "token":
                    full_text_parts.append(evt["text"])
                    yield {"data": TokenEvent(text=evt["text"]).model_dump_json()}
                elif evt_type == "tool_call":
                    yield {"data": ToolCallEvent(**evt).model_dump_json()}
                elif evt_type == "subagent":
                    yield {"data": SubagentEvent(**evt).model_dump_json()}
                elif evt_type == "approve":
                    yield {"data": ApproveEvent(**evt).model_dump_json()}
        except Exception as exc:  # noqa: BLE001 - 流内错误统一转 error 事件
            yield _build_error_event(is_resume, exc)
            return

        # 4. assistant 全文落库（容错：外键/瞬时失败降级内存，不阻断）
        assistant_text = "".join(full_text_parts)
        await _append_message_safe(
            conn,
            Message(session_id=session_id, role="assistant", content=assistant_text),
        )

        # 5. 长期记忆后台写入（done 前触发不等待——2026-08-04 优化）
        await _trigger_memory_after(req, session_id, assistant_text, lc_messages, is_resume)

        # 5.5 成本软告警事件（2026-08-11 成本控制 §5.6）：本 run 有超阈值告警 → yield
        #     中间件落 cost_alerts 已去重；这里 run 内发一次（前端 pushNotice）
        if not _cost_alert_sent:
            alert = await _fetch_latest_cost_alert(conn, session_id)
            if alert is not None:
                yield {"data": alert}
                _cost_alert_sent = True

        # 6. done 事件（流内异常时不发；context_used 查库带前端同步）
        yield {"data": (await _build_done_event(conn, run_id, session_id, started_at)).model_dump_json()}
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


@router.post("/approve", summary="审批决策（202 即返，恢复走新 SSE 流）")
async def approve(req: ApproveRequest) -> dict:
    """审批/澄清决策入口：写入 Redis 待决存储，accepted=True 时前端可 resume。

    P0 HITL 设计 §5.3（v1.2）：决策按 call_id 定位 action index 写入；publish_report
    的 reject 决策额外 INCR 会话修订计数（§5.3，配置化上限由 resume 侧消费）。

    Args:
        req: 审批决策请求（run_id + checkpoint_id + call_id + action + note/edited_arguments）

    Returns:
        {"status": "ok", "accepted": bool}

    Raises:
        HTTPException(404): 无待决审批（APPROVAL_NOT_FOUND）
        HTTPException(400): action 非法 / edit 缺参数 / respond 缺 note / call_id 不匹配
        HTTPException(503): Redis 不可达（审批服务暂不可用）
    """
    from src.agent.hitl.pending import (
        add_decision,
        get_action_name,
        get_session_id,
        incr_revision,
    )

    decision: dict[str, Any] = {"type": req.action}
    if req.action == "edit":
        if not req.edited_arguments:
            raise HTTPException(400, detail="edit 决策必须携带 edited_arguments")
        tool_name = await _resolve_tool_name(req.checkpoint_id)  # Redis 读工具名
        decision["edited_action"] = {"name": tool_name, "args": req.edited_arguments}
    if req.action == "reject" and req.note:
        decision["message"] = req.note
    if req.action == "respond":
        if not req.note:
            raise HTTPException(400, detail="respond 决策必须携带 note（人类回答）")
        decision["message"] = req.note
    try:
        accepted = await add_decision(req.checkpoint_id, req.call_id, decision)
        # v1.2 修订计数：publish_report 被拒 → 会话级 INCR（防无限修订循环）
        if req.action == "reject" and await get_action_name(req.checkpoint_id) == "publish_report":
            session_id = await get_session_id(req.checkpoint_id)
            if session_id:
                await incr_revision(session_id)
    except KeyError:
        raise HTTPException(404, detail="审批已过期或不存在，请重开对话")
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    except RedisError:
        raise HTTPException(503, detail="审批服务暂不可用，请稍后重试")
    return {"status": "ok", "accepted": accepted}


async def _resolve_tool_name(checkpoint_id: str) -> str:
    """待决审批对应的工具名（edit 决策需要 name 定位；Redis 读主 key）。

    Args:
        checkpoint_id: 中断点 checkpoint_id

    Returns:
        工具名（空串 = 无待决，由 add_decision 的 KeyError 兜底）
    """
    from src.agent.hitl.pending import get_action_name

    return await get_action_name(checkpoint_id) or ""
