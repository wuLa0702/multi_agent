"""成本仓储（成本控制唯一 SQL 出口，2026-08-11）。

06-structure-optimization §2：db/ 是唯一 SQL 出口——api/agent 禁直接写 SQL。
本 repo 收敛成本流水（token_cost_ledger）与告警（cost_alerts）全部读写。

用途：TokenUsageMiddleware（成本核算落流水/告警）+ api/cost（查询）。
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite


def _now_utc_str() -> str:
    """当前 UTC 时间字符串（ISO 格式，created_at）。"""
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


async def insert_cost_ledger(
    conn: aiosqlite.Connection,
    session_id: str,
    model_id: int,
    input_tokens: int,
    output_tokens: int,
    input_cost: float,
    output_cost: float,
    total_cost: float,
) -> None:
    """写成本流水（成本核算调用）。"""
    await conn.execute(
        """INSERT INTO token_cost_ledger
           (session_id, model_id, input_tokens, output_tokens,
            input_cost, output_cost, total_cost, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, model_id, input_tokens, output_tokens,
         input_cost, output_cost, total_cost, _now_utc_str()),
    )


async def sum_session_cost(conn: aiosqlite.Connection, session_id: str) -> float:
    """会话累计成本（告警判定 + summary API）。

    Returns:
        累计 total_cost（无记录 → 0.0）
    """
    cur = await conn.execute(
        "SELECT COALESCE(SUM(total_cost),0) AS tc FROM token_cost_ledger WHERE session_id = ?",
        (session_id,),
    )
    row = await cur.fetchone()
    return float(row["tc"]) if row else 0.0


async def highest_alert_threshold(
    conn: aiosqlite.Connection, session_id: str
) -> float | None:
    """已告警的最高档位阈值（分级告警去重判定：只对已跨越档位去重）。

    2026-08-12 分级告警：用 MAX(threshold) 而非最新一条——created_at 同秒不稳，
    且分级语义是"该档位是否已告警"（最高档即代表已覆盖的档位集合）。

    Returns:
        最高已告警阈值；无告警 → None
    """
    cur = await conn.execute(
        "SELECT MAX(threshold) AS t FROM cost_alerts WHERE session_id = ?",
        (session_id,),
    )
    row = await cur.fetchone()
    return float(row["t"]) if row and row["t"] is not None else None


async def insert_cost_alert(
    conn: aiosqlite.Connection,
    session_id: str,
    threshold: float,
    total_cost: float,
) -> None:
    """写成本告警（软告警落库）。"""
    await conn.execute(
        """INSERT INTO cost_alerts (session_id, threshold, total_cost, message, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            session_id, threshold, total_cost,
            f"会话成本已达 ¥{total_cost:.2f}，超阈值 ¥{threshold:.2f}", _now_utc_str(),
        ),
    )


async def summary(conn: aiosqlite.Connection, session_id: str) -> dict:
    """会话成本汇总（summary API：token 聚合 + 告警计数）。

    Returns:
        {"input_tokens", "output_tokens", "total_cost", "alert_count"}
    """
    cur = await conn.execute(
        """SELECT COALESCE(SUM(input_tokens),0) AS it, COALESCE(SUM(output_tokens),0) AS ot,
                  COALESCE(SUM(total_cost),0) AS tc FROM token_cost_ledger
           WHERE session_id = ?""",
        (session_id,),
    )
    row = await cur.fetchone()
    cur2 = await conn.execute(
        "SELECT COUNT(*) AS n FROM cost_alerts WHERE session_id = ?", (session_id,)
    )
    alert = await cur2.fetchone()
    return {
        "input_tokens": int(row["it"]) if row else 0,
        "output_tokens": int(row["ot"]) if row else 0,
        "total_cost": float(row["tc"]) if row else 0.0,
        "alert_count": int(alert["n"]) if alert else 0,
    }


async def list_alerts(conn: aiosqlite.Connection, session_id: str) -> list[dict]:
    """会话告警列表（倒序）。"""
    cur = await conn.execute(
        "SELECT threshold, total_cost, message, created_at FROM cost_alerts "
        "WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]
