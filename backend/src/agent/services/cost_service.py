"""成本数据服务——cost 仓储中转（api 禁直调 db/）。

查询：会话成本汇总 + 告警列表（写入方 TokenUsageMiddleware，本层只读）。
"""

from __future__ import annotations

from src.db import connection as db_conn
from src.db import cost_repository


async def summary(session_id: str) -> dict:
    """会话成本汇总（聚合 token_cost_ledger）。"""
    async with db_conn.connection() as conn:
        return await cost_repository.summary(conn, session_id)


async def list_alerts(session_id: str) -> list[dict]:
    """会话成本告警列表（cost_alerts 表，倒序）。"""
    async with db_conn.connection() as conn:
        return await cost_repository.list_alerts(conn, session_id)
