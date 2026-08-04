"""数据访问层（DAO）：settings 表 key/value 读写。

2026-08-04 后端开发计划 P1：系统配置持久化（前端设置页开关）。
与 repository.py 同款规范：显式 conn、参数化 SQL、写操作 commit。
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


async def get_all(conn: aiosqlite.Connection) -> dict[str, str]:
    """读取全部配置（key → value）。"""
    cursor = await conn.execute("SELECT key, value FROM settings")
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


async def upsert_many(conn: aiosqlite.Connection, values: dict[str, str]) -> None:
    """批量写入配置（INSERT OR REPLACE，幂等）。"""
    now = _now_iso()
    for key, value in values.items():
        await conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
    await conn.commit()
