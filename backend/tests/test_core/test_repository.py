"""DAO 测试：session CRUD + message 追加（:memory: SQLite）。

覆盖（20-testing.md）：
- 正常路径：建/查/改/删、消息追加与列表
- 边界条件：空表、不存在的 session
- 错误路径：外键约束（消息挂到不存在的会话必须报错）
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite

from src.core import db as core_db
from src.db import session_repo as repo
from src.schemas.message import Message


@pytest_asyncio.fixture
async def conn() -> aiosqlite.Connection:
    """:memory: 连接（复用产品连接层：PRAGMA/row_factory 与生产一致）。"""
    c = await core_db.get_connection(":memory:")
    yield c
    await c.close()


# ── Session CRUD ──

@pytest.mark.asyncio
async def test_create_and_get_session(conn: aiosqlite.Connection) -> None:
    """正常路径：创建后可按 ID 查回，字段一致。"""
    created = await repo.create_session(conn, "s1", title="采购分析")
    fetched = await repo.get_session(conn, "s1")

    assert fetched is not None
    assert fetched.id == "s1"
    assert fetched.title == "采购分析"
    assert created.id == fetched.id


@pytest.mark.asyncio
async def test_get_missing_session_returns_none(conn: aiosqlite.Connection) -> None:
    """边界条件：不存在的会话 → None（不抛异常）。"""
    assert await repo.get_session(conn, "not-exist") is None


@pytest.mark.asyncio
async def test_list_sessions_empty(conn: aiosqlite.Connection) -> None:
    """边界条件：空表 → 空列表。"""
    assert await repo.list_sessions(conn) == []


@pytest.mark.asyncio
async def test_list_sessions_newest_first(conn: aiosqlite.Connection) -> None:
    """正常路径：多会话按更新时间倒序（最新在前）。"""
    await repo.create_session(conn, "s1", title="旧")
    await repo.create_session(conn, "s2", title="新")
    await repo.update_session_title(conn, "s1", "旧-已更新")  # 触发 s1 时间刷新

    sessions = await repo.list_sessions(conn)
    assert [s.id for s in sessions] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_update_title_hit_and_miss(conn: aiosqlite.Connection) -> None:
    """正常/错误路径：更新命中返回 True；不存在返回 False。"""
    await repo.create_session(conn, "s1")
    assert await repo.update_session_title(conn, "s1", "新标题") is True
    assert await repo.update_session_title(conn, "ghost", "x") is False


# ── Message ──

@pytest.mark.asyncio
async def test_append_and_list_messages(conn: aiosqlite.Connection) -> None:
    """正常路径：消息追加后按时间正序返回，带自增 id。"""
    await repo.create_session(conn, "s1")
    m1 = await repo.append_message(conn, Message(session_id="s1", role="user", content="你好"))
    m2 = await repo.append_message(
        conn, Message(session_id="s1", role="assistant", content="你好！有什么可以帮你？")
    )

    assert m1.id == 1 and m2.id == 2  # 自增
    messages = await repo.list_messages(conn, "s1")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "你好"


@pytest.mark.asyncio
async def test_append_message_foreign_key_error(conn: aiosqlite.Connection) -> None:
    """错误路径：消息挂到不存在的会话 → 外键约束报错（防脏数据）。"""
    await repo.create_session(conn, "s1")
    with pytest.raises(Exception):
        await repo.append_message(
            conn, Message(session_id="ghost", role="user", content="孤儿消息")
        )


@pytest.mark.asyncio
async def test_delete_session_cascades_messages(conn: aiosqlite.Connection) -> None:
    """正常路径：删会话级联删消息（外键 ON DELETE CASCADE）。"""
    await repo.create_session(conn, "s1")
    await repo.append_message(conn, Message(session_id="s1", role="user", content="m1"))
    await repo.append_message(conn, Message(session_id="s1", role="user", content="m2"))

    assert await repo.delete_session(conn, "s1") is True
    assert await repo.get_session(conn, "s1") is None
    assert await repo.list_messages(conn, "s1") == []
