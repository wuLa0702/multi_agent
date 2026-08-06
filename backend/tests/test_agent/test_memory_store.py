"""Store 长期记忆测试（P1，2026-08-04 计划文档 B.2 + LLM 抽取修正）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- LLM 抽取：有价值对话 → 抽取事实；无价值 → None；LLM 异常 → 降级 None
- 持久化：写入 → 重建 store（模拟重启）→ 记忆仍可检索
- 噪音阈值：过短事实不写入
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
    from src.agent.memory.store import load_recent_memories, save_conversation_memory

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
    from src.agent.memory.store import MEMORY_MIN_LEN, load_recent_memories, save_conversation_memory

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


def test_agent_builds_with_store(mocker, tmp_path) -> None:
    """挂载：create_deep_agent 收到 store（lifespan 初始化后）。"""
    from src.agent import main_agent

    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])  # P1-1：不解析真实 YAML
    mock_create = mocker.patch("src.agent.main_agent.create_deep_agent", return_value=object())

    import asyncio

    async def run() -> None:
        main_agent._agents.clear()
        await main_agent.init_store(db_path=tmp_path)
        try:
            main_agent.get_agent()
        finally:
            await main_agent.close_store()

    asyncio.run(run())
    _, kwargs = mock_create.call_args
    assert kwargs["store"] is not None, "lifespan 初始化后 store 应挂载到 agent"
