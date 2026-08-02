"""health 接口测试：正常 / Redis 断开 / SQLite 断开（对应 20-testing.md 边界覆盖）。

策略：
- Redis 用 fake 对象（mock get_redis，不连真实服务）
- SQLite 用 :memory: 注入（mock core.db.get_connection）
- 错误路径：ping 抛异常 / 连接抛异常 → 断言降级不崩溃（HTTP 200）
"""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core import db as core_db


class _FakeRedisOk:
    """ping 成功的 Redis 替身。"""

    async def ping(self) -> bool:
        return True


class _FakeRedisDown:
    """ping 抛异常的 Redis 替身（模拟服务不可达）。"""

    async def ping(self) -> bool:
        raise ConnectionError("redis down")


async def _memory_conn() -> aiosqlite.Connection:
    """:memory: 连接工厂（health 只做 SELECT 1 探活，最小初始化即可；
    注意不能复用 core_db.get_connection——会被本文件 patch 导致自递归）。"""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    return conn


@pytest.mark.asyncio
async def test_health_ok(mocker) -> None:
    """正常路径：redis + sqlite 均通 → status=ok，全 connected。"""
    mocker.patch("src.api.health.get_redis", return_value=_FakeRedisOk())
    mocker.patch("src.core.db.get_connection", _memory_conn)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["redis"] == "connected"
    assert body["sqlite"] == "connected"
    assert body["env"] == "dev"


@pytest.mark.asyncio
async def test_health_redis_down_degraded(mocker) -> None:
    """错误路径：redis ping 失败 → redis=disconnected、status=degraded，HTTP 200 不崩。"""
    mocker.patch("src.api.health.get_redis", return_value=_FakeRedisDown())
    mocker.patch("src.core.db.get_connection", _memory_conn)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "disconnected"
    assert body["sqlite"] == "connected"


@pytest.mark.asyncio
async def test_health_sqlite_down_degraded(mocker) -> None:
    """错误路径：sqlite 打不开 → sqlite=disconnected、status=degraded，HTTP 200 不崩。"""
    mocker.patch("src.api.health.get_redis", return_value=_FakeRedisOk())

    async def _broken_conn() -> aiosqlite.Connection:
        raise aiosqlite.Error("cannot open database")

    mocker.patch("src.core.db.get_connection", _broken_conn)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "connected"
    assert body["sqlite"] == "disconnected"
