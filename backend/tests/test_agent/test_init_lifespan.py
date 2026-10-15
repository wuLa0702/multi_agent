"""无参初始化回归测试：防 NameError 再犯（2026-08-04 事故；2026-10-15 PG 迁移改写）。

事故原貌：`init_store()` 无参路径调用了未导入的 `get_store_path()` → NameError，
main.py lifespan 启动即崩。conftest 的 autouse fixture 总是显式传参，
**生产无参路径永不被测**——本文件专门补齐这条链路（规则 20-testing：正常/边界）。

PG 迁移后「无参」语义 = 走 settings 默认（`pg_dsn` + `pg_langgraph_schema`），
断言由「文件落盘」改为「目标 schema 内表已建出 + 连接已建立」。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from src.core.config import settings


async def _reset() -> None:
    """复位全局 store/checkpointer（与 conftest autouse 清理兼容，幂等）。"""
    from src.agent import main_agent

    await main_agent.close_store()
    await main_agent.close_checkpointer()


async def _table_exists(schema: str, table: str) -> bool:
    """查目标 schema 下某表是否存在。"""
    conn = await AsyncConnection.connect(settings.pg_dsn, row_factory=dict_row)
    try:
        cur = await conn.execute(
            "SELECT 1 AS ok FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        return (await cur.fetchone()) is not None
    finally:
        await conn.close()


async def _drop_schema(schema: str) -> None:
    """删除测试自建 schema（幂等）。"""
    conn = await AsyncConnection.connect(settings.pg_dsn, autocommit=True)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_init_store_no_arg_uses_default_schema() -> None:
    """正常：无参 init_store 走 settings.pg_langgraph_schema（曾 NameError 的那条路径）。"""
    from src.agent import main_agent

    await _reset()
    await main_agent.init_store()  # 无参 = main.py lifespan 同款调用

    assert main_agent._store is not None
    assert await _table_exists(settings.pg_langgraph_schema, "store")
    await _reset()


@pytest.mark.asyncio
async def test_init_checkpointer_no_arg_uses_default_schema() -> None:
    """正常：无参 init_checkpointer 走 settings.pg_langgraph_schema。"""
    from src.agent import main_agent

    await _reset()
    await main_agent.init_checkpointer()  # 无参 = main.py lifespan 同款调用

    assert main_agent._checkpointer is not None
    assert await _table_exists(settings.pg_langgraph_schema, "checkpoints")
    await _reset()


@pytest.mark.asyncio
async def test_init_store_custom_schema_isolates_tables() -> None:
    """边界：显式传 search_path → 表建在该 schema 内（测试隔离机制本身）。"""
    from src.agent import main_agent

    schema = f"t_{uuid4().hex[:12]}"
    await _reset()
    try:
        await main_agent.init_store(search_path=schema)
        assert main_agent._store is not None
        assert await _table_exists(schema, "store")
    finally:
        await _reset()
        await _drop_schema(schema)


@pytest.mark.asyncio
async def test_init_checkpointer_custom_schema_isolates_tables() -> None:
    """边界：显式传 search_path → 断点表建在该 schema 内。"""
    from src.agent import main_agent

    schema = f"t_{uuid4().hex[:12]}"
    await _reset()
    try:
        await main_agent.init_checkpointer(search_path=schema)
        assert main_agent._checkpointer is not None
        assert await _table_exists(schema, "checkpoints")
    finally:
        await _reset()
        await _drop_schema(schema)


@pytest.mark.asyncio
async def test_init_idempotent_second_call_noop() -> None:
    """边界：重复无参调用幂等（已初始化 → 直接返回，不重复建连接）。"""
    from src.agent import main_agent

    await _reset()
    await main_agent.init_store()
    first = main_agent._store
    await main_agent.init_store()  # 二次调用 → no-op

    assert main_agent._store is first
    await _reset()
