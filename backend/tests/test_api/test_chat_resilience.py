"""chat 降级矩阵单测（计划-容错处理 v1.2，P1-c）。

覆盖：会话落库 SQLite 瞬时错误重试 1 次 → 仍失败降级内存（不阻断响应）。
"""

from __future__ import annotations

import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import chat as chat_module
from src.api.main import app
from tests.test_api.test_chat import _post_stream, parse_sse


class TestSessionPersistRetry:
    """会话落库重试 + 降级（矩阵第一行）。"""

    @pytest.mark.asyncio
    async def test_retries_once_then_success(
        self, monkeypatch, mock_chat_llm, tmp_db_path
    ) -> None:
        """SQLite busy（可重试）→ 重试 1 次 → 第二次成功 → 正常建会话。"""
        from src.db import session_repo as repo

        calls = {"n": 0}
        real_create = repo.create_session

        async def flaky_create(conn, sid):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return await real_create(conn, sid)

        monkeypatch.setattr(repo, "create_session", flaky_create)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            _, body = await _post_stream(client, {"message": "hi"})
        events = parse_sse(body)
        assert calls["n"] == 2  # 重试一次后成功
        assert events[0]["type"] == "start"  # 会话正常创建

    @pytest.mark.asyncio
    async def test_degrades_to_memory_on_persistent_failure(
        self, monkeypatch, mock_chat_llm, tmp_db_path
    ) -> None:
        """SQLite 持续失败（重试仍失败）→ 降级内存会话：start 事件正常、无断流。"""
        from src.db import session_repo as repo

        calls = {"n": 0}

        async def always_fail(conn, sid):
            calls["n"] += 1
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(repo, "create_session", always_fail)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            _, body = await _post_stream(client, {"message": "hi"})
        events = parse_sse(body)
        assert calls["n"] == 2  # 重试 1 次后降级（共 2 次尝试）
        assert events[0]["type"] == "start"  # 降级不阻断：会话 ID 继续，响应正常
        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_retryable_error_also_retried(self, monkeypatch, mock_chat_llm, tmp_db_path) -> None:
        """自定义 RetryableError 同样触发重试（矩阵：可重试异常统一处理）。"""
        from src.core.errors import RetryableError
        from src.db import session_repo as repo

        calls = {"n": 0}
        real_create = repo.create_session

        async def flaky(conn, sid):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RetryableError("SQLite 瞬时锁")
            return await real_create(conn, sid)

        monkeypatch.setattr(repo, "create_session", flaky)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            _, body = await _post_stream(client, {"message": "hi"})
        assert calls["n"] == 2
        assert parse_sse(body)[0]["type"] == "start"
