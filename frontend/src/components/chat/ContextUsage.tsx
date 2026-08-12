/**
 * ContextUsage — 上下文用量（v3 §3.2 工具栏，📊 已用/总 token + 进度条）。
 * 2026-08-12 P3 交互优化：上限可调——点击齿轮弹出滑杆(64k~1M)+数字输入，localStorage 持久化。
 * 2026-08-04 评审改版（中间件存库方案）：TokenUsageMiddleware 图执行完
 * 自动写入 sessions.context_used → 前端直接查表 `GET /v1/context-usage?session_id=`
 */

import { useEffect, useState } from "react";
import { BarChart3, Settings2 } from "lucide-react";
import { useChatStore } from "@/lib/stores/chatStore";
import { api } from "@/lib/api/client";

const LIMIT_KEY = "multi-agent.contextLimit";
const DEFAULT_LIMIT = 128_000;
const MIN_LIMIT = 64_000;
const MAX_LIMIT = 1_000_000;

function loadLimit(): number {
  try {
    const raw = localStorage.getItem(LIMIT_KEY);
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) && n >= MIN_LIMIT ? n : DEFAULT_LIMIT;
  } catch {
    return DEFAULT_LIMIT;
  }
}

export default function ContextUsage() {
  const sessionId = useChatStore((s) => s.sessionId);
  const streamStatus = useChatStore((s) => s.streamStatus);
  const storeUsed = useChatStore((s) => s.contextUsed);
  const storeTotal = useChatStore((s) => s.contextTotal);
  const [used, setUsed] = useState(storeUsed);
  const [total, setTotal] = useState(loadLimit());
  const [editing, setEditing] = useState(false);

  // done 后同步 store 值
  useEffect(() => {
    if (storeUsed > 0) {
      setUsed(storeUsed);
      setTotal(storeTotal > 0 ? storeTotal : total);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeUsed, storeTotal]);

  // 真实模式：会话切换 / 流结束后查表
  useEffect(() => {
    if (!sessionId) {
      if (storeUsed === 0) {
        setUsed(0);
        setTotal(loadLimit());
      }
      return;
    }
    if (storeUsed > 0) return;
    void api
      .getContextUsage(sessionId)
      .then((r) => {
        setUsed(r.used);
        setTotal(r.total || loadLimit());
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, streamStatus]);

  const applyLimit = (next: number) => {
    const clamped = Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, next));
    setTotal(clamped);
    localStorage.setItem(LIMIT_KEY, String(clamped));
    useChatStore.setState({ contextTotal: clamped });
  };

  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const showPlaceholder = used === 0;

  return (
    <div className="relative">
      <div
        className="flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground hover:bg-accent/40"
        title={`上下文用量 ${(used / 1000).toFixed(1)}k / ${Math.round(total / 1000)}k（点击设置上限）`}
        onClick={() => setEditing((v) => !v)}
        data-testid="context-usage"
      >
        <BarChart3 className="size-3.5 text-primary" />
        <span className="hidden lg:inline">上下文</span>
        <span className="font-mono">
          {showPlaceholder ? "—" : `${(used / 1000).toFixed(1)}k/${Math.round(total / 1000)}k`}
        </span>
        <div className="ml-0.5 h-1 w-10 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary transition-all duration-300" style={{ width: `${pct}%` }} />
        </div>
        <Settings2 className="size-3 opacity-60" />
      </div>

      {/* 上限设置弹层（P3 交互优化，2026-08-12） */}
      {editing && (
        <div
          className="absolute bottom-10 right-0 z-30 w-56 rounded-lg border border-border bg-popover p-3 shadow-md"
          data-testid="context-limit-editor"
        >
          <div className="mb-1 text-xs font-medium">上下文上限（token）</div>
          <input
            type="range"
            min={MIN_LIMIT}
            max={MAX_LIMIT}
            step={64_000}
            value={total}
            onChange={(e) => applyLimit(Number(e.target.value))}
            className="w-full"
            aria-label="上下文上限滑杆"
          />
          <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
            <span>{(total / 1000).toFixed(0)}k</span>
            <span className="flex-1" />
            <input
              type="number"
              min={MIN_LIMIT}
              max={MAX_LIMIT}
              step={64_000}
              value={total}
              onChange={(e) => applyLimit(Number(e.target.value))}
              className="h-6 w-20 rounded border border-border bg-background px-1 text-right text-xs"
              aria-label="上下文上限输入"
            />
            <span>token</span>
          </div>
          <div className="mt-1 text-[10px] text-muted-foreground">
            范围 {(MIN_LIMIT / 1000)}k ~ {(MAX_LIMIT / 1000_000)}M（为更大模型预留）
          </div>
        </div>
      )}
    </div>
  );
}
