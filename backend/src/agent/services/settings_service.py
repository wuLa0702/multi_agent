"""配置数据服务——settings 仓储中转（api 禁直调 db/）。"""

from __future__ import annotations

from src.db import connection as db_conn
from src.db import settings_repository


async def get_all_settings() -> dict[str, str]:
    """读取全部用户可改配置（key/value）。"""
    async with db_conn.connection() as conn:
        return await settings_repository.get_all(conn)


async def upsert_settings(values: dict[str, str]) -> None:
    """批量写入配置（幂等 upsert）。"""
    async with db_conn.connection() as conn:
        await settings_repository.upsert_many(conn, values)
