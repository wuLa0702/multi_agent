import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { CostAlertListResponse, CostSummaryResponse } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { HelpTooltip } from "@/components/shared/HelpTooltip";
import { Settings2 } from "lucide-react";

/** 会话成本展示（F2 + T8 优化，2026-08-20）：成本汇总 + 告警 + 问号tooltip + 跳转配置 */
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
      .catch(() => !cancelled && setMissing(true));
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
    <div className="space-y-1.5 rounded border px-3 py-2 text-xs" data-testid="cost-panel">
      {/* 成本总额 + tooltip */}
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-muted-foreground">
          成本
          <HelpTooltip content="成本 = 模型单价(元/千token) × 增量token；单价在设置页「模型管理」配置" side="right" />
        </span>
        <span className="font-medium">¥{summary ? summary.total_cost.toFixed(4) : "…"}</span>
      </div>

      {/* Token 用量 + tooltip */}
      <div className="flex items-center justify-between text-muted-foreground">
        <span className="flex items-center gap-1">
          Token
          <HelpTooltip content="输入token + 输出token = 本轮累计LLM调用消耗的token总数" side="right" />
        </span>
        <span className="font-mono">
          {summary ? `${(summary.input_tokens + summary.output_tokens).toLocaleString()}` : "—"}
        </span>
      </div>

      {/* 告警 */}
      {alerts.length > 0 && (
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">告警</span>
          <Badge variant="destructive">{alerts.length}</Badge>
        </div>
      )}

      {/* 一键跳转配置 */}
      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent("navigate", { detail: "settings" }))}
        className="flex w-full items-center justify-center gap-1 rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
      >
        <Settings2 className="size-3" />
        模型单价配置 →
      </button>
    </div>
  );
}
