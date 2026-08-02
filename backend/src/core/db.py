"""SQLite 异步连接：aiosqlite + schema 初始化（WAL 模式）。

长期记忆地基：sessions / messages 表。
- 连接按需创建（惰性），FastAPI 不在 lifespan 常驻——SQLite 单文件，按请求开连接成本低
- WAL 模式：读写并发不互锁（多 Agent 并行写的前提）
- 测试注入 :memory: 或 tmp_path，天然隔离

用法：
    from src.core import db as core_db
    conn = await core_db.get_connection()       # 文件库（paths 决定位置）
    conn = await core_db.get_connection(Path(":memory:"))  # 测试
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from src.core.paths import get_db_path
from src.db import schema


async def get_connection(db_path: Path | str | None = None) -> aiosqlite.Connection:
    """创建 SQLite 异步连接并应用 schema（幂等）。

    Args:
        db_path: 数据库文件路径；None 时用 paths.get_db_path()
            （本地 dev / 云端 prod 自动切换）；测试传 :memory: 或 tmp_path

    Returns:
        aiosqlite.Connection：行工厂 = aiosqlite.Row，schema 已就绪

    Raises:
        aiosqlite.Error: 文件无法打开/建表失败
    """
    path = db_path if db_path is not None else get_db_path()
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await schema.init_schema(conn)
    return conn
