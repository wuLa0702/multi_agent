/**
 * SubagentPanel — 子代理模式内嵌面板（v5.0 §2.2，消息流内嵌）。
 * 数据源：chatStore.agentTree（与 Agent 详情第四栏同源，单向数据流）。
 * 结构：顶部整体进度条（完成/总数）+ 子代理卡片列表。
 * 卡片：状态图标（等待○/运行●脉冲/完成✓/错误✕）+ 名称 + 摘要 + 可折叠（运行中默认展开）。
 */

import { useState } from "react";
import { Check, Circle, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import type { AgentNode } from "@/lib/stores/chatStore";

/** 单卡片状态视觉（v5.0 §2.2.4） */
function StatusIcon({ status }: { status: AgentNode["status"] }) {
  if (status === "running") return <Loader2 className="size-4 animate-spin text-primary" />;
  if (status === "done") return <Check className="size-4 text-success" />;
  if (status === "error") return <X className="size-4 text-destructive" />;
  return <Circle className="size-4 text-muted-foreground" />;
}

function SubagentCard({ node, defaultOpen }: { node: AgentNode; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-border bg-card/60 shadow-sm">
      {/* 头部：状态 + 名称 + 折叠 */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <StatusIcon status={node.status} />
        <span className={cn("flex-1 truncate text-sm", node.status === "running" && "font-medium text-primary")}>
          {node.name}
        </span>
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px]",
            node.status === "running" && "bg-primary/10 text-primary",
            node.status === "done" && "bg-success/10 text-success",
            node.status === "error" && "bg-destructive/10 text-destructive",
            node.status === "waiting" && "bg-muted text-muted-foreground"
          )}
        >
          {node.status === "running" ? "运行中" : node.status === "done" ? "已完成" : node.status === "error" ? "错误" : "等待中"}
        </span>
        <span className="text-muted-foreground">{open ? "▾" : "▸"}</span>
      </button>
      {/* 展开内容：摘要（end 时） */}
      {open && node.summary && (
        <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">{node.summary}</p>
      )}
    </div>
  );
}

export default function SubagentPanel() {
  const agentTree = useChatStore((s) => s.agentTree);
  if (agentTree.length === 0) return null;

  const done = agentTree.filter((n) => n.status === "done" || n.status === "error").length;
  const total = agentTree.length;
  const pct = Math.round((done / total) * 100);

  return (
    <div className="mx-auto w-full max-w-2xl space-y-1.5 px-4 py-1">
      {/* 整体进度（v5.0 §2.2.4：已完成/总数 + 进度条） */}
      {total > 1 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>子代理进度：{done}/{total} 完成</span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-success transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="w-8 text-right">{pct}%</span>
        </div>
      )}
      {agentTree.map((node) => (
        <SubagentCard key={node.key} node={node} defaultOpen={node.status === "running"} />
      ))}
    </div>
  );
}
