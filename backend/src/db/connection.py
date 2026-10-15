"""PostgreSQL 连接池——全项目唯一连接出口（2026-10-15 PG 迁移，替代 core/db.py）。

职责（规则 06 §5「第三方中间件统一单例封装」）：
- 持有 psycopg_pool.AsyncConnectionPool 单例，DSN 从 settings.pg_dsn 读
- 对外只暴露 async 上下文管理器：`connection()`（借连接）/ `transaction()`（显式事务）
- repository / service **只接受连接**，不自己建连——建连唯一出口在本文

行工厂 dict_row：repository 以 `row["col"]` 取值（对齐迁移前 sqlite3.Row 用法）。
借出的连接退出上下文即**归还池**，不关闭物理连接——调用方禁止对借出连接调用
`close()`（那会真的销毁池连接）。

用法：
    from src.db import connection as db_conn

    async with db_conn.connection() as conn:
        session = await session_repo.get_session(conn, session_id)

生命周期：main.py lifespan 启动时 `await init_pool()`，关闭时 `await close_pool()`。
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.core.config import settings
from src.db import schema

logger = logging.getLogger(__name__)

# 池参数兜底默认值（配置项为 0 时生效）——2核4g 单机单用户场景：
# min=1 保 1 条常驻热连接省握手；max=10 远高于并发流上限；
# timeout=30s 借出等待上限（超时抛 PoolTimeout，不无限阻塞请求）
_FALLBACK_MIN_SIZE = 1
_FALLBACK_MAX_SIZE = 10
_FALLBACK_TIMEOUT = 30.0

_pool: AsyncConnectionPool | None = None

# schema 名合法性（标识符拼接前的护栏，防注入；schema 名来自 settings/测试生成，非用户输入）
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_schema_name(schema: str) -> None:
    """校验 schema 名是合法标识符（拼接进 DDL 前的护栏）。

    Args:
        schema: 待校验的 schema 名

    Raises:
        ValueError: 不是合法标识符
    """
    if not _IDENTIFIER_RE.match(schema):
        raise ValueError(f"schema 名必须是合法标识符：{schema!r}")


async def _create_schema_if_absent(conninfo: str, schema: str) -> None:
    """用**库默认 search_path**的临时连接建 schema（幂等）。

    ⚠️ 必须在目标连接/连接池带上 `search_path=<schema>` **之前**调用：
    search_path 指向不存在的 schema 时 PG 会静默忽略它，随后
    `CREATE TABLE` 会报 `no schema has been selected to create in`（实测踩坑）。

    Args:
        conninfo: 连接串
        schema: 目标 schema（已过标识符校验）
    """
    conn = await AsyncConnection.connect(conninfo, autocommit=True)
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        await conn.close()


async def init_pool(dsn: str | None = None, *, search_path: str | None = None) -> None:
    """创建并打开连接池（lifespan 启动调用，幂等）。

    Args:
        dsn: 覆盖连接串（测试隔离用；缺省读 settings.pg_dsn）
        search_path: 覆盖默认 schema（测试「每用例独立 schema」隔离用；缺省用库默认）

    Raises:
        RuntimeError: DSN 未配置（.env.dev / .env.prod 缺 PG_DSN）
        PoolTimeout: 打开池时建连超时（PG 未起 / 连接串错）
    """
    global _pool
    if _pool is not None:
        return

    conninfo = dsn or settings.pg_dsn
    if not conninfo:
        raise RuntimeError(
            "PG_DSN 未配置：请在 .env.dev / .env.prod 设置 PG_DSN 后重启后端"
        )

    kwargs: dict = {"row_factory": dict_row}
    if search_path:
        # 先建 schema 再让池指向它（顺序不可颠倒，见 _create_schema_if_absent）
        _validate_schema_name(search_path)
        await _create_schema_if_absent(conninfo, search_path)
        # libpq options 下发默认 schema：本池每条连接生效（测试按用例隔离）
        kwargs["options"] = f"-c search_path={search_path}"

    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=settings.pg_pool_min_size or _FALLBACK_MIN_SIZE,
        max_size=settings.pg_pool_max_size or _FALLBACK_MAX_SIZE,
        timeout=settings.pg_pool_timeout or _FALLBACK_TIMEOUT,
        kwargs=kwargs,
        open=False,  # 先建后开：await open() 时才建连（构造函数内不建连）
    )
    await pool.open()
    _pool = pool
    logger.info(
        "PG 连接池已启动：min=%s max=%s search_path=%s",
        pool.min_size,
        pool.max_size,
        search_path or "（库默认）",
    )


async def close_pool() -> None:
    """关闭连接池（lifespan 关闭调用，幂等）。"""
    global _pool
    if _pool is None:
        return
    pool, _pool = _pool, None
    await pool.close()
    logger.info("PG 连接池已关闭")


def is_initialized() -> bool:
    """连接池是否已初始化（降级路径 / 测试前置判定用）。"""
    return _pool is not None


async def ensure_schema() -> None:
    """确保业务表存在（幂等 DDL；lifespan 启动调用一次）。

    迁移前由 `core/db.py::get_connection()` 在**每次取连接**时执行建表——
    单文件 SQLite 廉价所以无感，PG 上每次请求跑一堆 DDL 则是纯浪费。
    改为启动时一次，测试由 conftest fixture 显式调用。

    Raises:
        RuntimeError: 池未初始化
        psycopg.Error: 建表失败
    """
    async with connection() as conn:
        await schema.init_schema(conn)


async def connect_with_schema(
    dsn: str | None = None,
    *,
    search_path: str,
    **connect_kwargs: object,
) -> AsyncConnection:
    """建一条**独立连接**并指向指定 schema（schema 不存在则创建）。

    与业务连接池分开：LangGraph 的 Checkpointer / Store 需要自有连接
    （各自的 search_path 与 autocommit / prepare_threshold 约定，且不能与
    业务事务互相牵制），故不经 `connection()` 池。调用方负责在生命周期
    结束时 `await conn.close()`。

    Args:
        dsn: 连接串；None → settings.pg_dsn
        search_path: 目标 schema（须为合法标识符；不存在则 CREATE SCHEMA）
        **connect_kwargs: 透传给 psycopg.AsyncConnection.connect

    Returns:
        已设好 search_path 的独立连接

    Raises:
        ValueError: search_path 不是合法标识符
        RuntimeError: DSN 未配置
        psycopg.Error: 连接或建 schema 失败
    """
    _validate_schema_name(search_path)
    conninfo = dsn or settings.pg_dsn
    if not conninfo:
        raise RuntimeError(
            "PG_DSN 未配置：请在 .env.dev / .env.prod 设置 PG_DSN 后重启后端"
        )
    # 先建 schema 再让连接指向它（顺序不可颠倒，见 _create_schema_if_absent）
    await _create_schema_if_absent(conninfo, search_path)
    return await AsyncConnection.connect(
        conninfo, options=f"-c search_path={search_path}", **connect_kwargs
    )


@asynccontextmanager
async def connection() -> AsyncIterator[AsyncConnection]:
    """从池借一条连接，退出自动归还（**不关闭物理连接**）。

    Yields:
        AsyncConnection：行工厂 dict_row（`row["col"]` 取值）

    Raises:
        RuntimeError: 池未初始化（lifespan 未跑 / 测试未建池）
    """
    if _pool is None:
        raise RuntimeError(
            "PG 连接池未初始化：请先 await connection.init_pool()（生产由 lifespan 调用）"
        )
    async with _pool.connection() as conn:
        try:
            yield conn
        except BaseException:
            # 异常路径回滚，避免半成品事务随连接归还池
            await conn.rollback()
            raise
        else:
            # 只读路径收尾：psycopg 隐式开启的事务在此提交；写路径 repository
            # 已自行 commit，此处为幂等空操作（已 IDLE 时 commit() 无副作用）
            await conn.commit()


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncConnection]:
    """借连接 + 显式事务块（正常提交、异常回滚）——「要么全成要么全败」的多语句单元用。

    ⚠️ 与 repository 内部的 `conn.commit()` 兼容（psycopg 允许嵌套），但调用方
    应保持块内只做一组原子写，别把无关读挂进来。

    Yields:
        AsyncConnection：事务内连接
    """
    async with connection() as conn, conn.transaction():
        yield conn
