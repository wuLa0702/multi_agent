"""health 接口测试：正常 / Redis 断开 / PostgreSQL 断开（对应规则 20-testing 边界覆盖）。

策略：
- Redis 用 fake 对象（mock get_redis，不连真实服务）
- PG 正常路径走**真实连接池**（conftest 的 pg_schema 已建池 + 建表）
- 错误路径：打开连接抛异常 → 断言降级不崩溃（HTTP 200）

2026-10-15 PG 迁移：探活对象 SQLite → PostgreSQL，响应字段 `sqlite` → `database`。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


class _FakeRedisOk:
    """ping 成功的 Redis 替身。"""

    async def ping(self) -> bool:
        return True


class _FakeRedisDown:
    """ping 抛异常的 Redis 替身（模拟服务不可达）。"""

    async def ping(self) -> bool:
        raise ConnectionError("redis down")


@asynccontextmanager
async def _broken_conn():
    """取连接即抛异常的替身（模拟 PG 不可达）。"""
    raise psycopg.OperationalError("pg down")
    yield  # pragma: no cover


@pytest.mark.asyncio
async def test_health_ok(mocker) -> None:
    """正常路径：redis + PG 均通 → status=ok，全 connected。"""
    mocker.patch("src.api.health.get_redis", return_value=_FakeRedisOk())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["redis"] == "connected"
    assert body["database"] == "connected"
    assert body["env"] == "dev"


@pytest.mark.asyncio
async def test_health_redis_down_degraded(mocker) -> None:
    """错误路径：redis ping 失败 → redis=disconnected、status=degraded，HTTP 200 不崩。"""
    mocker.patch("src.api.health.get_redis", return_value=_FakeRedisDown())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "disconnected"
    assert body["database"] == "connected"


@pytest.mark.asyncio
async def test_health_database_down_degraded(mocker) -> None:
    """错误路径：PG 取连接失败 → database=disconnected、status=degraded，HTTP 200 不崩。"""
    mocker.patch("src.api.health.get_redis", return_value=_FakeRedisOk())
    # health.py 内 `from src.db import connection as db_conn` 后按属性调用，
    # 故 patch 模块属性即可（不影响 fixture 的池生命周期）
    mocker.patch("src.db.connection.connection", _broken_conn)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "connected"
    assert body["database"] == "disconnected"
