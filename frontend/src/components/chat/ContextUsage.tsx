/**
 * ContextUsage — 上下文用量（v3 §3.2 工具栏，📊 已用/总 token + 进度条）。
 * 2026-08-04 P2 去 mock：读取 chatStore.contextUsed（done 事件由后端
 * CallbackHandler 统计后携带）；contextUsed=0 且未对话过 → 显示占位「—」。
 */

import { BarChart3 } from "lucide-react";
import { useChatStore } from "@/lib/stores/chatStore";

export default function ContextUsage() {
  const used = useChatStore((s) => s.contextUsed);
  const total = useChatStore((s) => s.contextTotal);

  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const showPlaceholder = used === 0;

  return (
    <div
      className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground"
      title={`上下文用量 ${(used / 1000).toFixed(1)}k / ${Math.round(total / 1000)}k`}
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
          style={{ width: `${showPlaceholder ? 0 : pct}%` }}
        />
      </div>
    </div>
  );
}
