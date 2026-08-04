/**
 * ContextUsage — 上下文用量（v2 §3.2 工具栏，📊 已用/总上下文 + 进度条）。
 * ⚠️ MOCK：后端无 token 统计接口，用量为演示值（已用 1.2k / 总 128k）。
 */

import { BarChart3 } from "lucide-react";

interface Props {
  used?: number; // mock 已用 token
  total?: number; // mock 总上下文
}

export default function ContextUsage({ used = 1200, total = 128000 }: Props) {
  const pct = Math.min(100, Math.round((used / total) * 100));
  return (
    <div
      className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground"
      title={`上下文用量 ${(used / 1000).toFixed(1)}k / ${(total / 1000).toFixed(0)}k（mock）`}
    >
      <BarChart3 className="size-3.5 text-primary" />
      <span className="hidden lg:inline">上下文</span>
      <span className="font-mono">
        {(used / 1000).toFixed(1)}k/{Math.round(total / 1000)}k
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
