import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { CostAlertListResponse, CostSummaryResponse } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";

/** 会话成本展示（F2，2026-08-12）：成本汇总 + 告警徽标（ChatPage 会话级） */
export function CostPanel({ sessionId }: { sessionId: string | null }) {
  const [summary, setSummary] = useState<CostSummaryResponse | null>(null);
  const [alerts, setAlerts] = useState<CostAlertListResponse["items"]>([]);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setMissing(false);
    api
      .getCostSummary(sessionId)
      .then((r) => !cancelled && setSummary(r))
      .catch(() => !cancelled && setMissing(true)); // COST_NOT_FOUND → 无成本记录
    api
      .getCostAlerts(sessionId)
      .then((r) => !cancelled && setAlerts(r.items))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (!sessionId) return null;
  if (missing) {
    return <div className="text-xs text-muted-foreground" data-testid="cost-panel">暂无成本记录</div>;
  }
  return (
    <div className="flex items-center gap-3 rounded border px-3 py-1.5 text-xs" data-testid="cost-panel">
      <span>
        成本 <span className="font-medium">¥{summary ? summary.total_cost.toFixed(4) : "…"}</span>
      </span>
      <span className="text-muted-foreground">
        {summary ? `${summary.input_tokens.toLocaleString()}/${summary.output_tokens.toLocaleString()} tokens` : ""}
      </span>
      {alerts.length > 0 && <Badge variant="destructive">{alerts.length} 告警</Badge>}
    </div>
  );
}
