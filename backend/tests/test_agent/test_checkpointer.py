"""Checkpointer 断点持久化测试（P0，2026-08-04 计划文档 A/C）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 持久化：checkpoint 写入 SQLite → 重建 saver（模拟重启）仍可读
- 隔离：多 thread（会话）checkpoint 互不干扰
- config 构造：stream_agent_tokens 内部封装 thread_id + checkpoint_id
- 并发限流：Semaphore 存在且值为 4
"""

from __future__ import annotations

import sqlite3

import pytest

from src.core.paths import CHECKPOINTER_DB_FILE, STORE_DB_FILE

from langgraph.checkpoint.base import CheckpointTuple
from langgraph.checkpoint.sqlite import SqliteSaver


def _make_saver(db_path) -> SqliteSaver:
    """建同步 SqliteSaver（直接构造自管连接；不用 from_conn_string——
    @contextmanager 退出即关连接，不适合持久的 saver）。"""
    # db_path 是目录（tmp_path）时拼 checkpoints.db；已是文件路径直接用
    db_file = db_path / CHECKPOINTER_DB_FILE if db_path.is_dir() else db_path
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _put_checkpoint(saver: SqliteSaver, thread_id: str, value: str) -> str:
    """写入一个 checkpoint，返回 checkpoint_id。"""
    from langgraph.checkpoint.base import Checkpoint

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
    saver.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        metadata,
        {},
    )
    return checkpoint["id"]


def test_checkpoint_persists_across_saver_reload(tmp_path) -> None:
    """持久化：写入 → 重建 saver（模拟重启进程）→ checkpoint 仍可读。"""
    db = tmp_path / CHECKPOINTER_DB_FILE

    # 第一次"进程"：写入
    saver1 = _make_saver(db)
    cid = _put_checkpoint(saver1, "session-a", "hello")
    saver1.conn.close()

    # 第二次"进程"：重建 saver 从同一 SQLite 读取
    saver2 = _make_saver(db)
    tuples: list[CheckpointTuple] = list(
        saver2.list({"configurable": {"thread_id": "session-a"}})
    )
    assert tuples, "重启后 checkpoint 应仍在（SQLite 持久化）"
    assert tuples[0].checkpoint["id"] == cid


def test_thread_isolation(tmp_path) -> None:
    """隔离：不同 thread（会话）checkpoint 互不干扰。"""
    saver = _make_saver(tmp_path)
    _put_checkpoint(saver, "session-a", "msg-a")
    _put_checkpoint(saver, "session-b", "msg-b")

    a = list(saver.list({"configurable": {"thread_id": "session-a"}}))
    b = list(saver.list({"configurable": {"thread_id": "session-b"}}))
    assert len(a) == 1 and len(b) == 1
    assert a[0].checkpoint["id"].endswith("msg-a")
    assert b[0].checkpoint["id"].endswith("msg-b")


def test_stream_config_builds_thread_id(mocker) -> None:
    """config 构造：stream_agent_tokens 内部封装 thread_id + checkpoint_id。"""
    from src.agent import main_agent

    captured: list[dict] = []
    fake_agent = mocker.MagicMock()

    # mock semaphore 不阻塞（用 async context manager 替身）
    import asyncio

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

    import asyncio

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
