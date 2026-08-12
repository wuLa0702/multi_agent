"""成本查询（设计 §5.5）：会话成本汇总 + 告警列表。

- 写入方：TokenUsageMiddleware 成本核算落 token_cost_ledger / cost_alerts
- 本接口只读：前端成本展示（P2 UI）或调试/审计
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.agent.services import cost_service

router = APIRouter(prefix="/v1/cost", tags=["cost"])


@router.get("/summary")
async def get_cost_summary(session_id: str = Query(..., description="会话 ID")):
    """会话成本汇总（聚合 token_cost_ledger）。

    Returns:
        {"session_id", "total_cost", "input_tokens", "output_tokens", "alert_count"}
    """
    s = await cost_service.summary(session_id)

    if s["input_tokens"] == 0 and s["output_tokens"] == 0 and s["total_cost"] == 0:
        raise HTTPException(
            status_code=404,
            detail={"error": "会话无成本记录", "detail": f"session_id={session_id} 无成本流水", "code": "COST_NOT_FOUND"},
        )
    return {
        "session_id": session_id,
        "total_cost": round(s["total_cost"], 4),
        "input_tokens": s["input_tokens"],
        "output_tokens": s["output_tokens"],
        "alert_count": s["alert_count"],
    }


@router.get("/alerts")
async def get_cost_alerts(session_id: str = Query(..., description="会话 ID")):
    """会话成本告警列表（cost_alerts 表，倒序）。"""
    items = await cost_service.list_alerts(session_id)
    return {"status": "ok", "items": items, "total": len(items)}
