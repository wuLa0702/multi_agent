"""流式对话：POST /v1/chat/stream（SSE，项目核心接口）。

契约：方案-后端接口定义-v1 §5。
- 事件流：start → token×N → done / error（首事件 start，尾事件二选一）
- 请求校验：message 与 resume_run_id 互斥（当前阶段 resume 未实现，仅校验）
- 持久化：user 消息先落库，assistant 全文聚合后落库（token 流不落库）

演进预留：resume_run_id（审批断点恢复）、tool_call/subagent/approve 事件
后续阶段按契约接入。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agent.main_agent import ChatContext, build_agent, stream_agent_tokens
from src.core import db as core_db
from src.core.errors import RetryableError
from src.core.model_registry import get_registry
from src.schemas.events import DoneEvent, ErrorEvent, StartEvent, TokenEvent
from src.schemas.message import Message

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


@router.post("/stream", summary="流式对话（SSE 核心接口）")
async def chat_stream(req: ChatStreamRequest) -> EventSourceResponse:
    """新消息驱动 Agent 执行，SSE 事件流推送过程与结果。

    Args:
        req: 会话 ID + 用户消息（resume 模式当前阶段未实现，校验拦截）

    Returns:
        text/event-stream：start → token×N → done（或 error）
    """
    _validate_request(req)

    # 建/取会话（session_id=None 自动新建；指定则校验存在）
    conn = await core_db.get_connection()
    try:
        session_id = req.session_id or str(uuid.uuid4())
        if req.session_id is None:
            from src.db import repository as repo

            await repo.create_session(conn, session_id)
        else:
            from src.db import repository as repo

            if await repo.get_session(conn, session_id) is None:
                raise HTTPException(
                    status_code=404,
                    detail=ErrorResponse(
                        error="会话不存在",
                        detail=f"session_id={session_id} 未找到",
                        code="SESSION_NOT_FOUND",
                    ).model_dump(),
                )
    finally:
        await conn.close()

    run_id = str(uuid.uuid4())
    started_at = time.monotonic()

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        """SSE 事件生成器：start → token×N → done/error。

        resume 模式（P0 断点恢复）：checkpoint 状态接管——不落库 user 消息、
        不注入模式指令、输入传空列表；从 checkpoint_id 快照继续执行。
        """
        nonlocal conn
        conn = await core_db.get_connection()
        try:
            from src.db import repository as repo

            is_resume = bool(req.resume_run_id)

            if not is_resume:
                # ── 新消息模式 ──
                # 1. user 消息落库
                await repo.append_message(
                    conn, Message(session_id=session_id, role="user", content=req.message or "")
                )

                # 1.5 自动标题（2026-08-04 P0）：首条消息且标题仍为默认值 → 取消息前 20 字
                session_row = await repo.get_session(conn, session_id)
                if session_row is not None and session_row.title == "新会话":
                    title = (req.message or "").strip().replace("\n", " ")[:20]
                    if title:
                        await repo.update_session_title(conn, session_id, title)

                # 2. 组历史（含本条 user 消息）→ LangChain 格式
                history = await repo.list_messages(conn, session_id, limit=200)
                lc_messages = _history_to_langchain(history)

                # 2.5 代理模式注入（2026-08-04 P1 先浅后深：仅请求级 SystemMessage）
                if req.mode != "default":
                    from src.agent.main_agent import _MODE_INSTRUCTIONS

                    instruction = _MODE_INSTRUCTIONS.get(req.mode)
                    if instruction:
                        lc_messages = [SystemMessage(content=instruction), *lc_messages]
            else:
                # ── resume 模式：checkpoint 状态接管，已完成步骤不重跑（计划文档 A）──
                lc_messages: list[BaseMessage] = []

            # 3. start 事件（resume 带 resumed=true，前端保留挂起前节点）
            yield {
                "data": StartEvent(
                    run_id=run_id, session_id=session_id, resumed=is_resume
                ).model_dump_json()
            }

            # 4. Agent 流式执行（LLM 异常 → error 事件后关闭）
            #    上下文用量：TokenUsageMiddleware（中间件栈内）图执行完自动存库，
            #    前端查表（GET /v1/context-usage），无需此处手动统计（2026-08-04 评审改版）
            try:
                agent = build_agent()  # 进程单例（模型经 middleware 按请求选择）
                chat_context = ChatContext(model_id=req.model_id, mode=req.mode, session_id=session_id)
                full_text_parts: list[str] = []
                async for text in stream_agent_tokens(
                    agent,
                    lc_messages,
                    context=chat_context,
                    checkpoint_id=req.resume_run_id,  # resume 模式：从精确快照继续
                ):
                    full_text_parts.append(text)
                    yield {"data": TokenEvent(text=text).model_dump_json()}
            except Exception as exc:  # noqa: BLE001 - 流内错误统一转 error 事件
                # resume 校验兜底（计划文档 A.5）：checkpoint 无效/不属于该 thread →
                # RESUME_NOT_FOUND 友好错误（前端提示「断点已失效，可重新开始」），不抛内部异常
                if is_resume:
                    yield {
                        "data": ErrorEvent(
                            code="RESUME_NOT_FOUND",
                            detail=f"断点已失效（{type(exc).__name__}），请重新开始对话",
                            retryable=False,
                        ).model_dump_json()
                    }
                    return
                retryable = isinstance(exc, RetryableError)
                yield {
                    "data": ErrorEvent(
                        code="LLM_UNAVAILABLE" if retryable else "INTERNAL",
                        detail=str(exc)[:500],
                        retryable=retryable,
                    ).model_dump_json()
                }
                return

            # 5. assistant 全文落库
            assistant_text = "".join(full_text_parts)
            await repo.append_message(
                conn,
                Message(session_id=session_id, role="assistant", content=assistant_text),
            )

            # 6. done 事件（流内异常时不发）
            duration_ms = int((time.monotonic() - started_at) * 1000)
            yield {
                "data": DoneEvent(
                    run_id=run_id,
                    session_id=session_id,
                    duration_ms=duration_ms,
                ).model_dump_json()
            }
        finally:
            await conn.close()

    return EventSourceResponse(event_stream())
