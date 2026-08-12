"""成本查询（设计 §5.5）：会话成本汇总 + 告警列表。

- 写入方：TokenUsageMiddleware 成本核算落 token_cost_ledger / cost_alerts
- 本接口只读：前端成本展示（P2 UI）或调试/审计
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.core import db as core_db

router = APIRouter(prefix="/v1/cost", tags=["cost"])


@router.get("/summary")
async def get_cost_summary(session_id: str = Query(..., description="会话 ID")):
    """会话成本汇总（聚合 token_cost_ledger）。

    Returns:
        {"session_id", "total_cost", "input_tokens", "output_tokens", "alert_count"}
    """
    conn = await core_db.get_connection()
    try:
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
    finally:
        await conn.close()

    if row is None or (row["it"] == 0 and row["ot"] == 0 and row["tc"] == 0):
        raise HTTPException(
            status_code=404,
            detail={"error": "会话无成本记录", "detail": f"session_id={session_id} 无成本流水", "code": "COST_NOT_FOUND"},
        )
    return {
        "session_id": session_id,
        "total_cost": round(float(row["tc"]), 4),
        "input_tokens": row["it"],
        "output_tokens": row["ot"],
        "alert_count": int(alert["n"]) if alert else 0,
    }


@router.get("/alerts")
async def get_cost_alerts(session_id: str = Query(..., description="会话 ID")):
    """会话成本告警列表（cost_alerts 表，倒序）。"""
    conn = await core_db.get_connection()
    try:
        cur = await conn.execute(
            "SELECT threshold, total_cost, message, created_at FROM cost_alerts "
            "WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        rows = await cur.fetchall()
    finally:
        await conn.close()
    return {"status": "ok", "items": [dict(r) for r in rows], "total": len(rows)}
