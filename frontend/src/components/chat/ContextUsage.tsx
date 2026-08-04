/**
 * ContextUsage — 上下文用量（v3 §3.2 工具栏，📊 已用/总 token + 进度条）。
 * 2026-08-04 评审改版（中间件存库方案）：TokenUsageMiddleware 图执行完
 * 自动写入 sessions.context_used → 前端直接查表 `GET /v1/context-usage?session_id=`
 * 会话切换 / 对话 done 后重新拉取；未查询到会话（无值）→ 显示占位「—」。
 */

import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";
import { useChatStore } from "@/lib/stores/chatStore";
import { api } from "@/lib/api/client";

export default function ContextUsage() {
  const sessionId = useChatStore((s) => s.sessionId);
  const streamStatus = useChatStore((s) => s.streamStatus);
  const [used, setUsed] = useState(0);
  const [total, setTotal] = useState(0);

  // 会话切换 / 流结束（done）后查表
  useEffect(() => {
    if (!sessionId) {
      setUsed(0);
      setTotal(0);
      return;
    }
    void api
      .getContextUsage(sessionId)
      .then((r) => {
        setUsed(r.used);
        setTotal(r.total);
      })
      .catch(() => undefined); // 查询失败静默（保持占位）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, streamStatus]);

  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const showPlaceholder = used === 0;

  return (
    <div
      className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground"
      title={`上下文用量 ${(used / 1000).toFixed(1)}k / ${Math.round(total / 1000)}k（中间件自动统计存库）`}
    >
      <BarChart3 className="size-3.5 text-primary" />
      <span className="hidden lg:inline">上下文</span>
      <span className="font-mono">
        {showPlaceholder ? "—" : `${(used / 1000).toFixed(1)}k/${Math.round(total / 1000)}k`}
      </span>
      {/* 进度条小指示 */}
      <div className="ml-0.5 h-1 w-10 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
