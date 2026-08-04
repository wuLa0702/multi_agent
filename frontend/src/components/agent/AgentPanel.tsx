/**
 * AgentPanel — 第四栏 Agent 详情面板（v3 §3.5，替代抽屉）。
 * 默认 320px，可拖动分隔线调宽（240-480px）；主内容区挤压不覆盖。
 * 内容：状态卡片（运行/等待/完成 + 当前 Agent + 耗时）+ 工具调用列表 + 子代理树 + 上下文用量。
 */

import { useRef, useState } from "react";
import { Bot, X, GripVertical, Timer, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import ToolCallPanel from "@/components/agent/ToolCallPanel";
import AgentTree from "@/components/agent/AgentTree";

const MIN_WIDTH = 240;
const MAX_WIDTH = 480;
const DEFAULT_WIDTH = 320;

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function AgentPanel({ open, onClose }: Props) {
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const streamStatus = useChatStore((s) => s.streamStatus);
  const toolCount = Object.keys(useChatStore((s) => s.toolCalls)).length;
  const agentTree = useChatStore((s) => s.agentTree);

  const statusText =
    streamStatus === "streaming" ? "运行中" : streamStatus === "awaiting_approval" ? "等待中" : "已完成";
  const statusColor =
    streamStatus === "streaming" ? "bg-success" : streamStatus === "awaiting_approval" ? "bg-warning" : "bg-muted-foreground/50";

  // 拖动分隔线调整宽度（v3 §3.5.3）
  const onDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startW: width };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const delta = dragRef.current.startX - ev.clientX; // 向左拖变宽
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragRef.current.startW + delta)));
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  if (!open) return null;

  return (
    <aside
      className="relative flex h-full shrink-0 flex-col border-l border-border bg-card"
      style={{ width }}
      aria-label="Agent 详情面板"
    >
      {/* 可拖动分隔线（v3 §3.5.3） */}
      <div
        className="group absolute -left-1.5 top-0 z-10 flex h-full w-3 cursor-col-resize items-center justify-center"
        onMouseDown={onDragStart}
        title="拖动调整宽度"
      >
        <GripVertical className="size-3 text-muted-foreground/40 opacity-0 transition-opacity group-hover:opacity-100" />
      </div>

      {/* 顶部标题栏 */}
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
        <Bot className="size-4 text-primary" />
        <span className="text-sm font-semibold">Agent 运行详情</span>
        <button
          type="button"
          onClick={onClose}
          className="press ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted"
          aria-label="关闭面板"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* 当前状态卡片（v3 §3.5.3-2） */}
        <div className="p-3">
          <div className="rounded-xl border border-border bg-muted/40 p-3">
            <div className="flex items-center gap-2">
              <span className={cn("relative flex size-2", streamStatus === "streaming" && "")}>
                <span
                  className={cn(
                    "absolute inline-flex size-full rounded-full opacity-60",
                    streamStatus === "streaming" && "animate-ping",
                    statusColor,
                  )}
                />
                <span className={cn("relative inline-flex size-2 rounded-full", statusColor)} />
              </span>
              <span className="text-xs font-medium">{statusText}</span>
              <span className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground">
                <Timer className="size-3" /> 主 Agent
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-muted-foreground">
              <span>工具调用：{toolCount} 次</span>
              <span>子代理：{agentTree.length} 个</span>
            </div>
            {/* 上下文用量（v3 §3.5.3-5，mock） */}
            <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <BarChart3 className="size-3" /> 上下文 1.2k/128k
              <div className="ml-1 h-1 flex-1 overflow-hidden rounded-full bg-muted">
                <div className="h-full w-[1%] rounded-full bg-primary transition-all duration-300" />
              </div>
            </div>
          </div>
        </div>

        {/* 工具调用列表（ToolCallPanel 自带标题） */}
        <div className="h-1/2 min-h-0 overflow-hidden border-b border-border">
          <ToolCallPanel />
        </div>

        {/* 子代理流转树（AgentTree 自带标题） */}
        <div className="h-1/2 min-h-0 overflow-hidden">
          <AgentTree />
        </div>
      </div>
    </aside>
  );
}
