"""Store 长期记忆测试（P1，2026-08-04 计划文档 B.2 + LLM 抽取修正）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- LLM 抽取：有价值对话 → 抽取事实；无价值 → None；LLM 异常 → 降级 None
- 持久化：写入 → 重建 store（模拟重启）→ 记忆仍可检索
- 噪音阈值：过短事实不写入
- store 挂载：create_deep_agent 收到 store（降级 None 兼容）
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest


@asynccontextmanager
async def _make_store(search_path: str):
    """建 AsyncPostgresStore（async 执行路径必需——sync 版 aput/asearch 抛 NotImplementedError）。

    Args:
        search_path: 记忆表所在 schema（用例独占，setup() 在此建表）

    Yields:
        已完成 setup 的 AsyncPostgresStore（退出时关连接，不污染用例池）
    """
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg.rows import dict_row

    from src.db import connection as db_conn

    conn = await db_conn.connect_with_schema(
        search_path=search_path,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        store = AsyncPostgresStore(conn)
        await store.setup()
        yield store
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_memory_persists_across_store_reload(pg_schema) -> None:
    """持久化：写入 → 重建 store（模拟重启）→ 记忆仍可检索。"""
    from src.agent.memory.store import load_recent_memories, save_conversation_memory

    async with _make_store(pg_schema) as store1:
        await save_conversation_memory(store1, "用户叫小明，喜欢 Python 编程" * 10)

    # 重建（模拟重启）
    async with _make_store(pg_schema) as store2:
        memories = await load_recent_memories(store2)
    assert memories, "重启后记忆应仍在（PostgresStore 持久化）"
    assert "小明" in memories[0]


@pytest.mark.asyncio
async def test_memory_noise_threshold(pg_schema) -> None:
    """噪音阈值：过短回复不写入（闲聊过滤）。"""
    from src.agent.memory.store import (
        MEMORY_MIN_LEN,
        load_recent_memories,
        save_conversation_memory,
    )

    async with _make_store(pg_schema) as store:
        short = "好的"  # < 阈值
        assert len(short) < MEMORY_MIN_LEN
        await save_conversation_memory(store, short)
        memories = await load_recent_memories(store)
    assert memories == [], "过短回复不应写入记忆"


@pytest.mark.asyncio
async def test_memory_store_none_graceful() -> None:
    """边界：store 为 None（未初始化/降级）→ 读写静默跳过。"""
    from src.agent.memory.store import load_recent_memories, save_conversation_memory

    await save_conversation_memory(None, "用户叫小明，喜欢 Python" * 10)  # 不抛
    assert await load_recent_memories(None) == []


# ── LLM 抽取（2026-08-04 修正：记忆只存抽取事实，非对话全文）──

class _FakeLLM:
    """fake LLM：返回预设抽取结果（raise_error=True 模拟调用异常）。"""

    def __init__(self, result: str, raise_error: bool = False) -> None:
        self._result = result
        self._raise = raise_error

    async def ainvoke(self, messages):
        if self._raise:
            raise RuntimeError("llm down")
        return type("R", (), {"content": self._result})()


@pytest.mark.asyncio
async def test_extract_memory_fact_valuable() -> None:
    """抽取：有价值对话（用户事实）→ 返回抽取的事实。"""
    from src.agent.memory.store import extract_memory_fact

    from src.llm.adapter import LLMAdapter

    adapter = LLMAdapter(model=_FakeLLM("用户叫小明，喜欢 Python 编程"))
    fact = await extract_memory_fact(
        adapter, "我叫小明，平时喜欢用 Python 写爬虫", "好的，记住了。你可以用 Python 的 requests 库…"
    )
    assert fact == "用户叫小明，喜欢 Python 编程"


@pytest.mark.asyncio
async def test_extract_memory_fact_no_value() -> None:
    """抽取：无价值对话（普通问答）→ 返回 None（不写入）。"""
    from src.agent.memory.store import extract_memory_fact

    from src.llm.adapter import LLMAdapter

    adapter = LLMAdapter(model=_FakeLLM("无"))
    fact = await extract_memory_fact(adapter, "帮我搜索一下天气", "今天北京晴，25 度…")
    assert fact is None


@pytest.mark.asyncio
async def test_extract_memory_fact_llm_error() -> None:
    """抽取：LLM 异常 → 降级 None（记忆是旁路能力，不阻断对话）。"""
    from src.agent.memory.store import extract_memory_fact

    from src.llm.adapter import LLMAdapter

    adapter = LLMAdapter(model=_FakeLLM("", raise_error=True))
    fact = await extract_memory_fact(adapter, "hi", "hello")
    assert fact is None


@pytest.mark.asyncio
async def test_agent_builds_with_store(mocker, pg_schema) -> None:
    """挂载：create_deep_agent 收到 store（lifespan 初始化后）。

    2026-10-15 PG 迁移：由 sync 测试改为 async——PG 连接要求 Selector 事件循环，
    `asyncio.run` 在 Windows 下拿到的是 Proactor，会直接崩。
    """
    from src.agent import main_agent

    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])  # P1-1：不解析真实 YAML
    mock_create = mocker.patch("src.agent.main_agent.create_deep_agent", return_value=object())

    main_agent._agents.clear()
    await main_agent.init_store(search_path=pg_schema)
    try:
        main_agent.get_agent()
    finally:
        await main_agent.close_store()

    _, kwargs = mock_create.call_args
    assert kwargs["store"] is not None, "lifespan 初始化后 store 应挂载到 agent"
