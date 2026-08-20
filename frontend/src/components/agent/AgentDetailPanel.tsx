/**
 * AgentDetailPanel — 第四栏 Agent 详情面板（v6 评审 P0-1：5列→4列，合并 InfoPanel + AgentPanel）。
 *
 * 布局目标（评审方案 §2）：取消常驻 InfoPanel，其内容并入单一面板，默认关（3 列），
 * Agent 按钮展开，可拖动调宽（240-480px）。
 *
 * 结构（自上而下）：
 *   1. 运行状态（常驻摘要卡：状态点 + 工具/子代理计数 + 上下文用量）
 *   2. 任务进度（TodoPanel / 空态，可折叠）
 *   3. 成本 / 告警（CostPanel，可折叠）
 *   4. 关联 Wiki（占位，可折叠）
 *   5. 工具调用（ToolCallPanel，自带标题）
 *   6. Agent 调用链（AgentTree，自带标题）
 *
 * 区块折叠记忆 localStorage（key: multi-agent.agentPanel.sections）。
 */

import { useRef, useState } from "react";
import { Bot, X, GripVertical, Timer, BarChart3, ClipboardList, BookOpen, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import ToolCallPanel from "./ToolCallPanel";
import AgentTree from "./AgentTree";
import TodoPanel from "@/components/todo/TodoPanel";
import { CostPanel } from "@/components/chat/CostPanel";
import EmptyState from "@/components/shared/EmptyState";

const MIN_WIDTH = 240;
const MAX_WIDTH = 480;
const DEFAULT_WIDTH = 320;
const SECTION_KEY = "multi-agent.agentPanel.sections";

function loadSections(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(SECTION_KEY);
    if (raw === null) return {};
    return JSON.parse(raw) as Record<string, boolean>;
  } catch {
    return {};
  }
}

/** 运行状态摘要卡（原 AgentPanel 顶部状态卡：状态 + 计数 + 上下文用量） */
function StatusCard() {
  const streamStatus = useChatStore((s) => s.streamStatus);
  const toolCount = Object.keys(useChatStore((s) => s.toolCalls)).length;
  const agentTree = useChatStore((s) => s.agentTree);
  const contextUsed = useChatStore((s) => s.contextUsed);
  const contextTotal = useChatStore((s) => s.contextTotal);

  const statusText =
    streamStatus === "streaming" ? "运行中" : streamStatus === "awaiting_approval" ? "等待中" : "已完成";
  const statusColor =
    streamStatus === "streaming" ? "bg-success" : streamStatus === "awaiting_approval" ? "bg-warning" : "bg-muted-foreground/50";
  const usedText = contextUsed > 0 ? `${(contextUsed / 1000).toFixed(1)}k` : "—";
  const totalText = contextTotal > 0 ? `${Math.round(contextTotal / 1000)}k` : "—";

  return (
    <div className="rounded-xl border border-border bg-muted/40 p-3">
      <div className="flex items-center gap-2">
        <span className="relative flex size-2">
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
      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <BarChart3 className="size-3" /> 上下文 {usedText}/{totalText}
        <div className="ml-1 h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-300"
            style={{ width: `${contextTotal > 0 ? Math.min(100, (contextUsed / contextTotal) * 100) : 0}%` }}
          />
        </div>
      </div>
    </div>
  );
}

/** 任务进度区块（有任务显示 TodoPanel，无任务统一空态） */
function TaskSection() {
  const todos = useChatStore((s) => s.todos);
  if (todos.length === 0) {
    return <EmptyState compact icon={ClipboardList} title="该项目暂无任务" desc="历史任务已完成" />;
  }
  return <TodoPanel />;
}

/** 关联 Wiki 区块（当前对话参考的 Wiki 知识点，后端 API 待落地时接真实数据） */
function WikiSection() {
  // TODO: 接 wiki 相关 API（当前为占位 UI，后续接真实数据）
  return <EmptyState compact icon={BookOpen} title="暂无关联知识" desc="对话中参考的 Wiki 知识点将显示在这里" />;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function AgentDetailPanel({ open, onClose }: Props) {
  const sessionId = useChatStore((s) => s.sessionId);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);
  const [sections, setSections] = useState<Record<string, boolean>>(loadSections);

  const isOpen = (k: string) => sections[k] ?? true;
  const toggleSection = (k: string) => {
    const next = { ...sections, [k]: !isOpen(k) };
    setSections(next);
    localStorage.setItem(SECTION_KEY, JSON.stringify(next));
  };

  // 拖动分隔线调整宽度（v3 §3.5.3，沿用原 AgentPanel）
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

  const Section = ({ k, title, children }: { k: string; title: string; children: React.ReactNode }) => (
    <div className="border-b border-border">
      <button
        type="button"
        onClick={() => toggleSection(k)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-accent/50"
      >
        <ChevronDown className={cn("size-3.5 transition-transform", isOpen(k) ? "" : "-rotate-90")} />
        {title}
      </button>
      {isOpen(k) && <div className="px-3 pb-3">{children}</div>}
    </div>
  );

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
        <span className="text-sm font-semibold">Agent 详情</span>
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
        <div className="p-3">
          <StatusCard />
        </div>

        <Section k="task" title="任务进度">
          <TaskSection />
        </Section>

        <Section k="cost" title="成本 / 告警">
          <CostPanel sessionId={sessionId} />
        </Section>

        <Section k="wiki" title="关联 Wiki">
          <WikiSection />
        </Section>

        {/* 工具调用 + Agent 调用链（自带标题，直接渲染） */}
        <div className="border-b border-border">
          <ToolCallPanel />
        </div>
        <div>
          <AgentTree />
        </div>
      </div>
    </aside>
  );
}
