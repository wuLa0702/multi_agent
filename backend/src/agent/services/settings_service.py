"""配置数据服务——settings 仓储中转（api 禁直调 db/）。"""

from __future__ import annotations

from src.core import db as core_db
from src.db import settings_repository


async def get_all_settings() -> dict[str, str]:
    """读取全部用户可改配置（key/value）。"""
    conn = await core_db.get_connection()
    try:
        return await settings_repository.get_all(conn)
    finally:
        await conn.close()


async def upsert_settings(values: dict[str, str]) -> None:
    """批量写入配置（幂等 upsert）。"""
    conn = await core_db.get_connection()
    try:
        await settings_repository.upsert_many(conn, values)
    finally:
        await conn.close()
