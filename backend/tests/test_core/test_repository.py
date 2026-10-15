"""DAO 测试：session CRUD + message 追加（每用例独立 PG schema）。

覆盖（规则 20-testing）：
- 正常路径：建/查/改/删、消息追加与列表
- 边界条件：空表、不存在的 session
- 错误路径：外键约束（消息挂到不存在的会话必须报错）

2026-10-15 PG 迁移：原 `:memory:` SQLite → 本用例独立 PG schema
（schema 由 conftest 的 autouse `pg_schema` 建好并清理）。
"""

from __future__ import annotations

import pytest
from psycopg import AsyncConnection

from src.db import connection as db_conn
from src.db import session_repo as repo
from src.schemas.message import Message


@pytest.fixture
async def conn():
    """本用例 schema 上的 PG 连接（借出即用，退出归还池）。"""
    async with db_conn.connection() as c:
        yield c


# ── Session CRUD ──

@pytest.mark.asyncio
async def test_create_and_get_session(conn: AsyncConnection) -> None:
    """正常路径：创建后可按 ID 查回，字段一致。"""
    created = await repo.create_session(conn, "s1", title="采购分析")
    fetched = await repo.get_session(conn, "s1")

    assert fetched is not None
    assert fetched.id == "s1"
    assert fetched.title == "采购分析"
    assert created.id == fetched.id


@pytest.mark.asyncio
async def test_get_missing_session_returns_none(conn: AsyncConnection) -> None:
    """边界条件：不存在的会话 → None（不抛异常）。"""
    assert await repo.get_session(conn, "not-exist") is None


@pytest.mark.asyncio
async def test_list_sessions_empty(conn: AsyncConnection) -> None:
    """边界条件：空表 → 空列表。"""
    assert await repo.list_sessions(conn) == []


@pytest.mark.asyncio
async def test_list_sessions_newest_first(conn: AsyncConnection) -> None:
    """正常路径：多会话按更新时间倒序（最新在前）。"""
    await repo.create_session(conn, "s1", title="旧")
    await repo.create_session(conn, "s2", title="新")
    await repo.update_session_title(conn, "s1", "旧-已更新")  # 触发 s1 时间刷新

    sessions = await repo.list_sessions(conn)
    assert [s.id for s in sessions] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_update_title_hit_and_miss(conn: AsyncConnection) -> None:
    """正常/错误路径：更新命中返回 True；不存在返回 False。"""
    await repo.create_session(conn, "s1")
    assert await repo.update_session_title(conn, "s1", "新标题") is True
    assert await repo.update_session_title(conn, "ghost", "x") is False


# ── Message ──

@pytest.mark.asyncio
async def test_append_and_list_messages(conn: AsyncConnection) -> None:
    """正常路径：消息追加后按时间正序返回，带自增 id。"""
    await repo.create_session(conn, "s1")
    m1 = await repo.append_message(conn, Message(session_id="s1", role="user", content="你好"))
    m2 = await repo.append_message(
        conn, Message(session_id="s1", role="assistant", content="你好！有什么可以帮你？")
    )

    assert m1.id == 1 and m2.id == 2  # IDENTITY 自增（本用例 schema 全新，从 1 起）
    messages = await repo.list_messages(conn, "s1")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "你好"


@pytest.mark.asyncio
async def test_append_message_foreign_key_error(conn: AsyncConnection) -> None:
    """错误路径：消息挂到不存在的会话 → 外键约束报错（防脏数据）。"""
    await repo.create_session(conn, "s1")
    with pytest.raises(Exception):
        await repo.append_message(
            conn, Message(session_id="ghost", role="user", content="孤儿消息")
        )


@pytest.mark.asyncio
async def test_delete_session_cascades_messages(conn: AsyncConnection) -> None:
    """正常路径：删会话级联删消息（外键 ON DELETE CASCADE）。"""
    await repo.create_session(conn, "s1")
    await repo.append_message(conn, Message(session_id="s1", role="user", content="m1"))
    await repo.append_message(conn, Message(session_id="s1", role="user", content="m2"))

    assert await repo.delete_session(conn, "s1") is True
    assert await repo.get_session(conn, "s1") is None
    assert await repo.list_messages(conn, "s1") == []

# ── 按需声明：本模块测试需要数据库（2026-10-15 起 pg_schema 不再 autouse）──
@pytest.fixture(autouse=True)
def _needs_db(pg_schema) -> None:
    """本模块每个用例都要独立 PG schema（隔离 + 用完即删）。"""
    return None
