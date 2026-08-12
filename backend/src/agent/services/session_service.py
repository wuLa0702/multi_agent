"""会话数据服务——封装连接管理与会话仓储（api 禁直调 db/，经本服务中转）。

职责：连接生命周期 + session_repo 调用 + 会话删除联动（缓存重建/工作区清理/沙箱销毁）。
"""

from __future__ import annotations

from src.agent import main_agent
from src.core import db as core_db
from src.core.backend import cleanup_workspace
from src.db import session_repo
from src.sandbox.pool import sandbox_pool
from src.schemas.message import Message
from src.schemas.session import Session


async def create_session(session_id: str, title: str = "新会话") -> Session:
    """创建会话（连接托管）。"""
    conn = await core_db.get_connection()
    try:
        return await session_repo.create_session(conn, session_id, title)
    finally:
        await conn.close()


async def get_session(session_id: str) -> Session | None:
    """取会话（不存在返回 None）。"""
    conn = await core_db.get_connection()
    try:
        return await session_repo.get_session(conn, session_id)
    finally:
        await conn.close()


async def list_sessions(limit: int = 50, offset: int = 0) -> tuple[list[Session], int]:
    """会话列表 + 总量（updated_at 倒序）。"""
    conn = await core_db.get_connection()
    try:
        items = await session_repo.list_sessions(conn, limit=limit, offset=offset)
        total = len(await session_repo.list_sessions(conn, limit=10_000))
        return items, total
    finally:
        await conn.close()


async def update_session(
    session_id: str, title: str | None = None, is_pinned: bool | None = None
) -> Session | None:
    """更新标题/置顶（至少一项），返回更新后会话；更新失败（不存在）返回 None。"""
    conn = await core_db.get_connection()
    try:
        if title is not None:
            if not await session_repo.update_session_title(conn, session_id, title):
                return None
        if is_pinned is not None:
            if not await session_repo.update_session_pinned(conn, session_id, is_pinned):
                return None
        return await session_repo.get_session(conn, session_id)
    finally:
        await conn.close()


async def delete_session(session_id: str) -> bool:
    """删除会话 + 联动：缓存图重建 / 工作区清理 / 沙箱销毁（幂等）。"""
    conn = await core_db.get_connection()
    try:
        deleted = await session_repo.delete_session(conn, session_id)
        if deleted:
            main_agent.rebuild_agent(session_id)
            cleanup_workspace(session_id, older_than_days=0)
            sandbox_pool.destroy(session_id)
        return deleted
    finally:
        await conn.close()


async def list_messages(
    session_id: str, limit: int = 50, before_id: int | None = None
) -> list[Message]:
    """历史消息 cursor 分页（id 升序，最旧在前）。"""
    conn = await core_db.get_connection()
    try:
        return await session_repo.list_messages(
            conn, session_id, limit=limit, before_id=before_id
        )
    finally:
        await conn.close()
