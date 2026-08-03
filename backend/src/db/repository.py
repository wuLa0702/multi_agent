"""数据访问层（DAO）：session CRUD + message 追加，全参数化 SQL。

规范（12-backend.md）：
- 只调用 schema.py 的建表 SQL，业务 SQL 参数化，禁止字符串拼接
- 写操作必须 commit；行工厂 sqlite3.Row（aiosqlite.Row）
- 时间统一 UTC ISO 字符串（模型层 datetime 自动解析）
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from src.schemas.message import Message
from src.schemas.session import Session


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（DB 存储格式）。"""
    return datetime.now(timezone.utc).isoformat()


# ── 行 → 模型 ──

def _row_to_session(row: aiosqlite.Row) -> Session:
    """DB 行 → Session 实体（Pydantic 自动解析 ISO 时间）。"""
    return Session(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: aiosqlite.Row) -> Message:
    """DB 行 → Message 实体。"""
    return Message(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
    )


# ── Session CRUD ──

async def create_session(conn: aiosqlite.Connection, session_id: str, title: str = "新会话") -> Session:
    """创建会话。

    Args:
        conn: SQLite 连接（已初始化 schema）
        session_id: 会话 ID（调用方生成 UUID）
        title: 会话标题

    Returns:
        新建的 Session 实体
    """
    now = _now_iso()
    await conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    await conn.commit()
    return Session(id=session_id, title=title, created_at=now, updated_at=now)


async def get_session(conn: aiosqlite.Connection, session_id: str) -> Session | None:
    """按 ID 查会话；不存在返回 None。"""
    cursor = await conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    return _row_to_session(row) if row else None


async def list_sessions(
    conn: aiosqlite.Connection, limit: int = 50, offset: int = 0
) -> list[Session]:
    """会话列表（更新时间倒序，最新在前）。"""
    cursor = await conn.execute(
        "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_session(r) for r in rows]


async def update_session_title(
    conn: aiosqlite.Connection, session_id: str, title: str
) -> bool:
    """更新会话标题；返回是否命中。"""
    cursor = await conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, _now_iso(), session_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_session(conn: aiosqlite.Connection, session_id: str) -> bool:
    """删除会话（messages 由外键 ON DELETE CASCADE 级联清理）；返回是否命中。"""
    cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await conn.commit()
    return cursor.rowcount > 0


# ── Message ──

async def append_message(conn: aiosqlite.Connection, message: Message) -> Message:
    """追加一条消息（会话必须已存在，否则外键报错）。

    Returns:
        带自增 id 的 Message 实体
    """
    cursor = await conn.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (message.session_id, message.role, message.content, message.created_at.isoformat()),
    )
    # 会话更新时间随消息刷新（列表排序用）
    await conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now_iso(), message.session_id),
    )
    await conn.commit()
    return message.model_copy(update={"id": cursor.lastrowid})


async def list_messages(
    conn: aiosqlite.Connection, session_id: str, limit: int = 200
) -> list[Message]:
    """会话消息流（时间正序，最旧在前）。"""
    cursor = await conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
        (session_id, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_message(r) for r in rows]
