/**
 * 工具调用面板（三栏直播台右栏）— 工具/参数/结果。
 * 数据源：chatStore.toolCalls（契约 tool_call 事件，call_id 幂等 upsert）。
 * 结果截断展示（契约 v1 result ≤4KB，前端截断到 800 字符 + 折叠）。
 *
 * v6 评审 P2-8：补耗时显示（运行中实时计时 / 完成显示耗时）+ 空态统一 EmptyState。
 */

import { useEffect, useState } from "react";
import { Wrench, ChevronDown, ChevronRight, Circle, Timer } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore, type ToolCall } from "@/lib/stores/chatStore";
import EmptyState from "@/components/shared/EmptyState";

const RESULT_PREVIEW_LEN = 800;

/** 耗时格式化：<1s 显示 ms，≥1s 显示 s（P2-8） */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const running = call.status === "running";
  const resultText = call.result ?? "";

  // P2-8：运行中实时计时（500ms 节流刷新）
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [running]);

  const start = call.started_at ? new Date(call.started_at).getTime() : null;
  const end = call.ended_at ? new Date(call.ended_at).getTime() : null;
  const duration = start != null ? (end ?? now) - start : null;

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
      >
        {open ? <ChevronDown className="size-3.5 text-neutral-400" /> : <ChevronRight className="size-3.5 text-neutral-400" />}
        <Wrench className="size-3.5 text-neutral-400" />
        <span className="flex-1 truncate font-mono text-xs">{call.name}</span>
        {/* 耗时（P2-8：运行中实时计数，完成显示耗时） */}
        {duration != null && (
          <span className={cn("flex shrink-0 items-center gap-0.5 text-[10px]", running ? "text-blue-500" : "text-neutral-400")}>
            <Timer className="size-2.5" />
            {formatDuration(duration)}
          </span>
        )}
        {running ? (
          <Circle className="size-3 animate-pulse text-blue-500" />
        ) : (
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px]",
              call.status === "success" && "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300",
              call.status === "error" && "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
            )}
          >
            {call.status}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t border-neutral-200 dark:border-neutral-800 px-2.5 py-2 text-xs space-y-2">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-neutral-400">参数</div>
            <pre className="mt-0.5 whitespace-pre-wrap break-all rounded bg-neutral-50 dark:bg-neutral-900 p-1.5 text-neutral-600 dark:text-neutral-400">
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
          </div>
          {call.result !== undefined && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-neutral-400">结果</div>
              <pre className="mt-0.5 whitespace-pre-wrap break-all rounded bg-neutral-50 dark:bg-neutral-900 p-1.5 text-neutral-600 dark:text-neutral-400">
                {resultText.length > RESULT_PREVIEW_LEN
                  ? `${resultText.slice(0, RESULT_PREVIEW_LEN)}…（已截断）`
                  : resultText}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ToolCallPanel() {
  const toolCalls = useChatStore((s) => s.toolCalls);
  const entries = Object.values(toolCalls);

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-neutral-500">
        <Wrench className="size-3.5" /> 工具调用
        {entries.length > 0 && (
          <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-1.5 text-[10px] text-neutral-500">
            {entries.length}
          </span>
        )}
      </div>
      {entries.length === 0 ? (
        <EmptyState compact icon={Wrench} title="暂无工具调用" />
      ) : (
        entries.map((c) => <ToolCallCard key={c.call_id} call={c} />)
      )}
    </div>
  );
}
