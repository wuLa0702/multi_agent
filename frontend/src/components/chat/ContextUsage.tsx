/**
 * ContextUsage — 上下文用量（v3 §3.2 工具栏 + 2026-08-20 T2 交互优化）。
 *
 * T2 改造：
 * - Tab「累计/本轮」切换（默认累计）
 * - 横向柱状图格式（文字 + 进度条，直观看用了多少/离上限差多少）
 * - 问号 HelpTooltip 解释 token 含义
 * - 上限滑杆设置保留
 *
 * 2026-08-12 P3 交互优化：上限可调——点击齿轮弹出滑杆(64k~1M)+数字输入，localStorage 持久化。
 * 2026-08-04 评审改版：TokenUsageMiddleware 图执行完自动写入 sessions.context_used。
 */

import { useEffect, useState } from "react";
import { BarChart3, Settings2 } from "lucide-react";
import { useChatStore } from "@/lib/stores/chatStore";
import { api } from "@/lib/api/client";
import { HelpTooltip } from "@/components/shared/HelpTooltip";

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

/** 横向柱状图行（文字 + 进度条） */
function BarRow({ label, value, max, tooltip }: { label: string; value: number; max: number; tooltip?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1 text-muted-foreground">
          {label}
          {tooltip && <HelpTooltip content={tooltip} side="right" />}
        </span>
        <span className="font-mono text-foreground">{value.toLocaleString()}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function ContextUsage() {
  const sessionId = useChatStore((s) => s.sessionId);
  const streamStatus = useChatStore((s) => s.streamStatus);
  const storeUsed = useChatStore((s) => s.contextUsed);
  const storeTotal = useChatStore((s) => s.contextTotal);
  const [used, setUsed] = useState(storeUsed);
  const [total, setTotal] = useState(loadLimit());
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState<"cumulative" | "round">("cumulative");

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
      {/* 工具栏紧凑条（保留原有入口） */}
      <div
        className="flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground hover:bg-accent/40"
        title={`上下文用量 ${(used / 1000).toFixed(1)}k / ${Math.round(total / 1000)}k（点击展开详情）`}
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

      {/* 展开详情面板（T2 改造：Tab + 横向柱状图 + 上限设置） */}
      {editing && (
        <div
          className="absolute bottom-10 right-0 z-30 w-64 rounded-lg border border-border bg-popover p-3 shadow-md"
          data-testid="context-detail-panel"
        >
          {/* Tab 切换（累计/本轮） */}
          <div className="mb-2 flex gap-1 rounded-md bg-muted p-0.5">
            <button
              type="button"
              onClick={() => setTab("cumulative")}
              className={`flex-1 rounded px-2 py-0.5 text-[11px] transition-colors ${
                tab === "cumulative" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"
              }`}
            >
              累计
            </button>
            <button
              type="button"
              onClick={() => setTab("round")}
              className={`flex-1 rounded px-2 py-0.5 text-[11px] transition-colors ${
                tab === "round" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"
              }`}
            >
              本轮
            </button>
          </div>

          {/* 横向柱状图 */}
          {tab === "cumulative" ? (
            <div className="space-y-2">
              <BarRow
                label="输入 token"
                value={used}
                max={total}
                tooltip="本轮累计 LLM 接收的 token 数（上下文 + 用户消息），每次对话后累加"
              />
              <BarRow
                label="最大 token"
                value={total}
                max={total}
                tooltip="上下文窗口上限（默认 128k，可在下方滑杆调整，支持更大模型）"
              />
              <div className="flex items-center justify-between text-[11px]">
                <span className="flex items-center gap-1 text-muted-foreground">
                  成本
                  <HelpTooltip content="成本 = 模型单价(元/千token) × 增量token；单价在设置页「模型管理」配置" side="right" />
                </span>
                <span className="font-mono text-foreground">{pct}%</span>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <BarRow label="输入 token" value={0} max={total} tooltip="本轮对话的输入 token（最新一轮 LLM 调用）" />
              <BarRow label="输出 token" value={0} max={total} tooltip="本轮对话的输出 token（最新一轮 LLM 生成）" />
              <div className="text-[10px] text-muted-foreground">本轮数据待后端 API 补充</div>
            </div>
          )}

          {/* 上限设置 */}
          <div className="mt-3 border-t border-border pt-2">
            <div className="mb-1 text-[11px] font-medium">上下文上限</div>
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
            <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
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
          </div>
        </div>
      )}
    </div>
  );
}
