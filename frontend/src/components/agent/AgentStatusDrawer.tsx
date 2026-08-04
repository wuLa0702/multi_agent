/**
 * AgentStatusDrawer — 右侧可折叠抽屉（方案 §5.1.2-1）。
 * 替代原常驻右栏：工具调用 + 子代理树，默认收起，点击展开。
 * 展开/收起带 250ms 滑入滑出动效。
 */

import { useState } from "react";
import { Activity, X, Bot } from "lucide-react";
import ToolCallPanel from "@/components/agent/ToolCallPanel";
import AgentTree from "@/components/agent/AgentTree";
import { useChatStore } from "@/lib/stores/chatStore";
import { cn } from "@/lib/utils";

export default function AgentStatusDrawer() {
  const [open, setOpen] = useState(false);
  const toolCount = Object.keys(useChatStore((s) => s.toolCalls)).length;
  const streaming = useChatStore((s) => s.streamStatus === "streaming");

  return (
    <>
      {/* 悬浮入口按钮（右上角） */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="press btn-lift fixed right-4 top-3 z-30 flex h-9 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-xs shadow-md"
        title="Agent 状态（工具调用 + 子代理）"
        aria-label="打开 Agent 状态抽屉"
      >
        {streaming ? (
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
            <span className="relative inline-flex size-2 rounded-full bg-success" />
          </span>
        ) : (
          <Activity className="size-3.5 text-primary" />
        )}
        <span className="font-medium">Agent</span>
        {toolCount > 0 && (
          <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">
            {toolCount}
          </span>
        )}
      </button>

      {/* 抽屉遮罩 */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px] transition-opacity duration-200"
          onClick={() => setOpen(false)}
          aria-hidden
        />
      )}

      {/* 抽屉主体：滑入 250ms */}
      <aside
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full w-[340px] flex-col border-l border-border bg-background shadow-xl transition-transform duration-250 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-label="Agent 状态抽屉"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Bot className="size-4 text-primary" />
            Agent 直播台
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="press rounded-md p-1 text-muted-foreground hover:bg-muted"
            aria-label="关闭抽屉"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="h-1/2 min-h-0 border-b border-border overflow-hidden">
            <ToolCallPanel />
          </div>
          <div className="h-1/2 min-h-0 overflow-hidden">
            <AgentTree />
          </div>
        </div>
      </aside>
    </>
  );
}
