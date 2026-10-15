"""数据访问层（DAO）：settings 表 key/value 读写。

2026-08-04 后端开发计划 P1：系统配置持久化（前端设置页开关）。
与 session_repo 同款规范：显式接收连接、参数化 SQL、写操作 commit。

方言要点（2026-10-15 PG 迁移）：占位符 `?` → `%s`；
原 `INSERT OR REPLACE`（SQLite 专有）→ 标准 `ON CONFLICT (key) DO UPDATE`。
"""

from __future__ import annotations

from datetime import datetime, timezone

from psycopg import AsyncConnection


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


async def get_all(conn: AsyncConnection) -> dict[str, str]:
    """读取全部配置（key → value）。"""
    cursor = await conn.execute("SELECT key, value FROM settings")
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


async def upsert_many(conn: AsyncConnection, values: dict[str, str]) -> None:
    """批量写入配置（PG upsert，幂等）。"""
    now = _now_iso()
    for key, value in values.items():
        await conn.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (%s, %s, %s)
               ON CONFLICT (key) DO UPDATE
               SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at""",
            (key, value, now),
        )
    await conn.commit()
