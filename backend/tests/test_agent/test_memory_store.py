"""Store 长期记忆测试（P1，2026-08-04 计划文档 B.2）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 持久化：写入 → 重建 store（模拟重启）→ 记忆仍可检索
- 噪音阈值：过短回复不写入
- 注入/写入：memory_store 封装读写正确
- store 挂载：create_deep_agent 收到 store（降级 None 兼容）
"""

from __future__ import annotations

import pytest
from langgraph.store.sqlite import SqliteStore


async def _make_store(db_path) -> SqliteStore:
    """建 AsyncSqliteStore（async 执行路径必需——SqliteStore 不支持 async 方法）。"""
    import aiosqlite
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    db_file = db_path / "store.db" if db_path.is_dir() else db_path
    # isolation_level=None：autocommit 连接（AsyncSqliteStore 内部管理事务）
    conn = await aiosqlite.connect(str(db_file), isolation_level=None)
    await conn.execute("PRAGMA journal_mode=WAL")
    store = AsyncSqliteStore(conn)
    await store.setup()
    return store


@pytest.mark.asyncio
async def test_memory_persists_across_store_reload(tmp_path) -> None:
    """持久化：写入 → 重建 store（模拟重启）→ 记忆仍可检索。"""
    from src.agent.memory_store import load_recent_memories, save_conversation_memory

    # 用独立子目录：autouse fixture 的 store 占用了 tmp_path 根（避免 DB 锁冲突）
    db = tmp_path / "mem" / "store.db"
    db.parent.mkdir()
    store1 = await _make_store(db)
    await save_conversation_memory(store1, "用户叫小明，喜欢 Python 编程" * 10)

    # 重建（模拟重启）
    store2 = await _make_store(db)
    memories = await load_recent_memories(store2)
    assert memories, "重启后记忆应仍在（SqliteStore 持久化）"
    assert "小明" in memories[0]


@pytest.mark.asyncio
async def test_memory_noise_threshold(tmp_path) -> None:
    """噪音阈值：过短回复不写入（闲聊过滤）。"""
    from src.agent.memory_store import MEMORY_MIN_LEN, load_recent_memories, save_conversation_memory

    # 独立子目录（避免与 autouse fixture 的 store 锁冲突）
    db = tmp_path / "mem2" / "store.db"
    db.parent.mkdir()
    store = await _make_store(db)

    short = "好的"  # < 阈值
    assert len(short) < MEMORY_MIN_LEN
    await save_conversation_memory(store, short)
    memories = await load_recent_memories(store)
    assert memories == [], "过短回复不应写入记忆"


@pytest.mark.asyncio
async def test_memory_store_none_graceful() -> None:
    """边界：store 为 None（未初始化/降级）→ 读写静默跳过。"""
    from src.agent.memory_store import load_recent_memories, save_conversation_memory

    await save_conversation_memory(None, "测试内容" * 30)  # 不抛
    assert await load_recent_memories(None) == []


def test_agent_builds_with_store(mocker, tmp_path) -> None:
    """挂载：create_deep_agent 收到 store（lifespan 初始化后）。"""
    from src.agent import main_agent

    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mock_create = mocker.patch("src.agent.main_agent.create_deep_agent", return_value=object())

    import asyncio

    async def run() -> None:
        main_agent._agent = None
        await main_agent.init_store(db_path=tmp_path)
        try:
            main_agent.get_agent()
        finally:
            await main_agent.close_store()

    asyncio.run(run())
    _, kwargs = mock_create.call_args
    assert kwargs["store"] is not None, "lifespan 初始化后 store 应挂载到 agent"
