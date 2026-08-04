"""会话与消息 REST 路由（契约 §4）：POST/GET/PATCH/DELETE /v1/sessions + 消息分页。

契约：方案-后端接口定义-v1 §4.2-4.6。
- 创建会话：无请求体，标题默认「新会话」
- 会话列表：按 updated_at 倒序（最近活跃在前）
- 消息分页：cursor 分页（limit ≤200 + before_id），响应 items 升序 + next_before_id/has_more
- 错误统一 ErrorResponse（契约 §3.3），404 用 SESSION_NOT_FOUND（契约 §7）

依赖单向：api → core/db + db/repository，不反向。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.core import db as core_db
from src.db import repository as repo
from src.schemas.message import Message
from src.schemas.session import Session

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


# ── 响应/请求模型（契约 §4 逐字段对齐）──

class SessionUpdateRequest(BaseModel):
    """修改会话标题 / 置顶（契约 §4.4 + 2026-08-04 P0）。

    title 与 is_pinned 至少提供一个（由 handler 校验）；标题长度 1-100 校验在 handler。
    """

    title: str | None = Field(default=None, description="新标题，1-100 字符")
    is_pinned: bool | None = Field(default=None, description="置顶状态（2026-08-04 P0）")


class SessionListResponse(BaseModel):
    """会话列表（契约 §4.3）。"""

    status: str = "ok"
    items: list[Session]
    total: int


class MessagePage(BaseModel):
    """历史消息分页（契约 §4.6）。"""

    status: str = "ok"
    items: list[Message]
    next_before_id: int | None = None
    has_more: bool = False


class DeleteResponse(BaseModel):
    """删除会话（契约 §4.5）。"""

    status: str = "ok"


class ErrorResponse(BaseModel):
    """统一错误响应（契约 §3.3）。"""

    error: str
    detail: str
    code: str


def _raise_404(session_id: str) -> None:
    """会话不存在（契约 §7：SESSION_NOT_FOUND）。"""
    raise HTTPException(
        status_code=404,
        detail=ErrorResponse(
            error="会话不存在",
            detail=f"session_id={session_id} 未找到",
            code="SESSION_NOT_FOUND",
        ).model_dump(),
    )


# ── 路由 ──

@router.post("", summary="创建会话（契约 §4.2）")
async def create_session() -> Session:
    """创建新会话，标题默认「新会话」（首条消息后由后端流程维护）。

    Returns:
        Session 实体（UUID + 创建/更新时间）
    """
    conn = await core_db.get_connection()
    try:
        return await repo.create_session(conn, str(uuid.uuid4()))
    finally:
        await conn.close()


@router.get("", summary="会话列表（契约 §4.3）")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200, description="条数上限"),
    offset: int = Query(default=0, ge=0, description="跳过条数"),
) -> SessionListResponse:
    """会话列表（updated_at 倒序，最近活跃在前）。

    Args:
        limit: 分页条数（默认 50）
        offset: 分页偏移

    Returns:
        SessionListResponse（status + items + total）
    """
    conn = await core_db.get_connection()
    try:
        items = await repo.list_sessions(conn, limit=limit, offset=offset)
        total = len(await repo.list_sessions(conn, limit=10_000))
        return SessionListResponse(items=items, total=total)
    finally:
        await conn.close()


@router.patch("/{session_id}", summary="修改会话标题/置顶（契约 §4.4 + P0）")
async def update_session_title(
    session_id: str, req: SessionUpdateRequest
) -> Session:
    """修改会话标题 / 置顶状态（title 与 is_pinned 至少提供一个）。

    Args:
        session_id: 会话 ID
        req: 新标题（1-100 字符）和/或置顶状态

    Returns:
        更新后的 Session 实体

    Raises:
        HTTPException: 404 会话不存在；400 参数为空/标题超长
    """
    if req.title is None and req.is_pinned is None:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="参数缺失",
                detail="title 或 is_pinned 至少提供一个",
                code="BAD_REQUEST",
            ).model_dump(),
        )
    if req.title is not None and not (1 <= len(req.title) <= 100):
        # 契约 §4.4：标题 1-100 字符；手动校验统一 400（Pydantic 自动校验是 422）
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="参数非法",
                detail="标题长度需在 1-100 字符之间",
                code="BAD_REQUEST",
            ).model_dump(),
        )
    conn = await core_db.get_connection()
    try:
        if req.title is not None:
            if not await repo.update_session_title(conn, session_id, req.title):
                _raise_404(session_id)
        if req.is_pinned is not None:
            if not await repo.update_session_pinned(conn, session_id, req.is_pinned):
                _raise_404(session_id)
        updated = await repo.get_session(conn, session_id)
        assert updated is not None  # 刚更新成功必然存在
        return updated
    finally:
        await conn.close()


@router.delete("/{session_id}", summary="删除会话（契约 §4.5）")
async def delete_session(session_id: str) -> DeleteResponse:
    """删除会话（消息由外键 ON DELETE CASCADE 级联清理）。

    Args:
        session_id: 会话 ID

    Returns:
        DeleteResponse（status=ok）

    Raises:
        HTTPException: 404 会话不存在
    """
    conn = await core_db.get_connection()
    try:
        if not await repo.delete_session(conn, session_id):
            _raise_404(session_id)
        return DeleteResponse()
    finally:
        await conn.close()


@router.get("/{session_id}/messages", summary="历史消息分页（契约 §4.6）")
async def list_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="条数上限"),
    before_id: int | None = Query(default=None, description="cursor：取 id 小于该值的更早消息"),
) -> MessagePage:
    """历史消息 cursor 分页（id 升序，最旧在前）。

    Args:
        session_id: 会话 ID
        limit: 条数上限（默认 50，≤200）
        before_id: 上一页最旧消息 id 之前的分页游标

    Returns:
        MessagePage（items + next_before_id + has_more）

    Raises:
        HTTPException: 404 会话不存在
    """
    conn = await core_db.get_connection()
    try:
        if await repo.get_session(conn, session_id) is None:
            _raise_404(session_id)
        # 多取 1 条判断是否还有更早页（契约 §3.4 cursor 语义）；
        # repo 返回升序（最新在后），尾部 limit 条 = 最新一页，next_before_id = 本页最旧一条 id
        rows = await repo.list_messages(conn, session_id, limit=limit + 1, before_id=before_id)
        has_more = len(rows) > limit
        page = rows[-limit:] if has_more else rows
        next_before_id = page[0].id if has_more else None
        return MessagePage(items=page, next_before_id=next_before_id, has_more=has_more)
    finally:
        await conn.close()
