"""Checkpointer 断点持久化测试（P0，2026-08-04 计划文档 A/C）。

覆盖（规则 20-testing：正常 / 边界 / 错误）：
- 持久化：checkpoint 写入 PG → 重建 saver（模拟重启）仍可读
- 隔离：多 thread（会话）checkpoint 互不干扰
- config 构造：stream_agent_tokens 内部封装 thread_id + checkpoint_id
- 并发限流：Semaphore 存在且取 settings.stream_concurrency

2026-10-15 PG 迁移：AsyncSqliteSaver → AsyncPostgresSaver；持久化介质由
「同文件」变为「同 schema」（用例 schema 由 conftest 建好并在结束时 DROP）。
"""

from __future__ import annotations

import asyncio

import pytest
from langgraph.checkpoint.base import Checkpoint, CheckpointTuple


async def _make_saver(search_path: str):
    """建 AsyncPostgresSaver（async 执行路径必需——sync 版在 astream 下静默失败）。

    Args:
        search_path: 断点表所在 schema（用例独占，setup() 在此建表）

    Returns:
        已完成 setup 的 AsyncPostgresSaver（调用方负责 close）
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row

    from src.db import connection as db_conn

    conn = await db_conn.connect_with_schema(
        search_path=search_path,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    saver = AsyncPostgresSaver(conn)
    await saver.setup()
    return saver


async def _put_checkpoint(saver, thread_id: str, value: str) -> str:
    """写入一个 checkpoint，返回 checkpoint_id。"""
    checkpoint: Checkpoint = {
        "v": 1,
        "ts": "2026-08-04T00:00:00Z",
        "id": f"checkpoint-{thread_id}-{value}",
        "channel_values": {"messages": [{"role": "user", "content": value}]},
        "channel_versions": {},
        "versions_seen": {},
        "pending_sends": [],
    }
    metadata = {"source": "loop", "step": 1, "writes": None}
    # put 签名：put(config, checkpoint, metadata, new_versions)——config 含 thread_id + checkpoint_ns
    await saver.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        metadata,
        {},
    )
    return checkpoint["id"]


@pytest.mark.asyncio
async def test_checkpoint_persists_across_saver_reload(pg_schema) -> None:
    """持久化：写入 → 重建 saver（模拟重启进程）→ checkpoint 仍可读。"""
    # 第一次"进程"：写入
    saver1 = await _make_saver(pg_schema)
    cid = await _put_checkpoint(saver1, "session-a", "hello")
    await saver1.conn.close()

    # 第二次"进程"：重建 saver 从同一 schema 读取
    saver2 = await _make_saver(pg_schema)
    try:
        tuples: list[CheckpointTuple] = [
            t async for t in saver2.alist({"configurable": {"thread_id": "session-a"}})
        ]
        assert tuples, "重启后 checkpoint 应仍在（PostgreSQL 持久化）"
        assert tuples[0].checkpoint["id"] == cid
    finally:
        await saver2.conn.close()


@pytest.mark.asyncio
async def test_thread_isolation(pg_schema) -> None:
    """隔离：不同 thread（会话）checkpoint 互不干扰。"""
    saver = await _make_saver(pg_schema)
    try:
        await _put_checkpoint(saver, "session-a", "msg-a")
        await _put_checkpoint(saver, "session-b", "msg-b")

        a = [t async for t in saver.alist({"configurable": {"thread_id": "session-a"}})]
        b = [t async for t in saver.alist({"configurable": {"thread_id": "session-b"}})]
        assert len(a) == 1 and len(b) == 1
        assert a[0].checkpoint["id"].endswith("msg-a")
        assert b[0].checkpoint["id"].endswith("msg-b")
    finally:
        await saver.conn.close()


def test_stream_config_builds_thread_id(mocker) -> None:
    """config 构造：stream_agent_tokens 内部封装 thread_id + checkpoint_id。"""
    from src.agent import main_agent

    captured: list[dict] = []
    fake_agent = mocker.MagicMock()

    # mock semaphore 不阻塞（用 async context manager 替身）
    class _NullCM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    mocker.patch.object(main_agent, "_stream_semaphore", new=_NullCM())

    # 捕获 astream_events 的 config 参数（返回空异步生成器）
    async def _capture(*args, **kwargs) -> None:
        captured.append(kwargs)
        if False:
            yield  # pragma: no cover

    fake_agent.astream_events.side_effect = _capture

    async def run() -> None:
        ctx = main_agent.ChatContext(model_id=None, session_id="sess-1")
        async for _ in main_agent.stream_agent_tokens(
            fake_agent, [], context=ctx, checkpoint_id="cp-9"
        ):
            pass

    asyncio.run(run())

    assert captured, "应调用 astream_events"
    config = captured[0]["config"]
    assert config["configurable"]["thread_id"] == "sess-1"
    assert config["configurable"]["checkpoint_id"] == "cp-9"


def test_stream_semaphore_configured() -> None:
    """并发限流：Semaphore 存在且取 settings.stream_concurrency（C.1-2 + 2026-08-10 拍板）。

    硬编码 4 → settings 字段（本地 .env.dev=10 / 云端 .env.prod=2，环境保存可调）。
    2026-08-11 决策 #3：函数工厂惰性获取（get_stream_semaphore）。
    """
    from src.agent import main_agent
    from src.core.config import settings

    sem = main_agent.get_stream_semaphore()
    assert sem is not None
    assert sem._value == settings.stream_concurrency


def test_stream_semaphore_rebuilds_on_settings_change(monkeypatch) -> None:
    """2026-08-11 决策 #3：settings 变化 → 工厂重建信号量（不关心底层只关心获取）。"""
    from src.agent import main_agent
    from src.core.config import settings

    old = settings.stream_concurrency
    try:
        settings.stream_concurrency = old + 5
        sem2 = main_agent.get_stream_semaphore()
        assert sem2._value == old + 5
    finally:
        settings.stream_concurrency = old
        main_agent.get_stream_semaphore()  # 还原


def test_stream_config_without_session_no_thread_id(mocker) -> None:
    """边界：无 session_id 时不构造 thread_id config（不误传）。"""
    from src.agent import main_agent

    captured: list[dict] = []
    fake_agent = mocker.MagicMock()

    class _NullCM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    mocker.patch.object(main_agent, "_stream_semaphore", new=_NullCM())

    async def _capture(*args, **kwargs) -> None:
        captured.append(kwargs)
        if False:
            yield  # pragma: no cover

    fake_agent.astream_events.side_effect = _capture

    async def run() -> None:
        async for _ in main_agent.stream_agent_tokens(fake_agent, [], context=None):
            pass

    asyncio.run(run())
    assert captured[0]["config"] is None, "无 session_id 时不带 config"
