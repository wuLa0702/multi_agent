/**
 * 工具调用面板（三栏直播台右栏）— 工具/参数/结果。
 * 数据源：chatStore.toolCalls（契约 tool_call 事件，call_id 幂等 upsert）。
 * 结果截断展示（契约 v1 result ≤4KB，前端截断到 800 字符 + 折叠）。
 */

import { useState } from "react";
import { Wrench, ChevronDown, ChevronRight, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore, type ToolCall } from "@/lib/stores/chatStore";

const RESULT_PREVIEW_LEN = 800;

function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const running = call.status === "running";
  const resultText = call.result ?? "";

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
        <div className="mt-6 text-center text-xs text-neutral-400">暂无工具调用</div>
      ) : (
        entries.map((c) => <ToolCallCard key={c.call_id} call={c} />)
      )}
    </div>
  );
}
