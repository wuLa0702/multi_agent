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
        last_message=row["last_message"] if "last_message" in row.keys() else None,
        is_pinned=bool(row["is_pinned"]) if "is_pinned" in row.keys() else False,
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
    """会话列表（置顶优先 + 更新时间倒序，2026-08-04 P0 调整）。

    每条附带 last_message：最后一条 user/assistant 消息内容截断 ≤50 字
    （LEFT JOIN 子查询取最新一条，单用户列表量小，性能足够）。
    """
    cursor = await conn.execute(
        """SELECT s.id, s.title, s.is_pinned, s.created_at, s.updated_at,
                  substr(COALESCE(
                    (SELECT m.content FROM messages m
                     WHERE m.session_id = s.id AND m.role IN ('user','assistant')
                     ORDER BY m.id DESC LIMIT 1), ''), 1, 50) AS last_message
           FROM sessions s
           ORDER BY s.is_pinned DESC, s.updated_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_session(r) for r in rows]


async def update_session_pinned(
    conn: aiosqlite.Connection, session_id: str, is_pinned: bool
) -> bool:
    """更新会话置顶状态；返回是否命中。"""
    cursor = await conn.execute(
        "UPDATE sessions SET is_pinned = ?, updated_at = ? WHERE id = ?",
        (int(is_pinned), _now_iso(), session_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


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
    conn: aiosqlite.Connection,
    session_id: str,
    limit: int = 200,
    before_id: int | None = None,
) -> list[Message]:
    """会话消息流（时间正序，最旧在前；分页时取「最新一页」）。

    Args:
        conn: SQLite 连接（已初始化 schema）
        session_id: 会话 ID
        limit: 返回条数上限
        before_id: cursor 分页——只取 id 小于该值的更早消息（契约 §3.4）。
                   第一页（None）返回会话最新 limit 条；调用方需 DESC 取 + 反转保证升序。

    Returns:
        消息实体列表（id 升序）
    """
    if before_id is None:
        sql = "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?"
        params: tuple = (session_id, limit)
    else:
        sql = "SELECT * FROM messages WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?"
        params = (session_id, before_id, limit)
    cursor = await conn.execute(sql, params)
    rows = await cursor.fetchall()
    # DESC 取（最新在前）后反转回 id 升序，保持「会话内自然顺序」契约
    return [_row_to_message(r) for r in reversed(rows)]
