/**
 * TodoPanel — 任务规划模式顶部面板（v5.0 §2.3，主内容区顶部固定不随滚动）。
 * 数据源：chatStore.todos（TodoListMiddleware 推送，全量替换；空 → 不渲染）。
 * 结构：头部（📋 任务进度 + 已完成/总数 + 百分比 + 折叠）+ 任务列表。
 * 状态样式：待执行 ○灰 / 进行中 ◉主题色脉冲 / 已完成 ✓绿删除线。
 */

import { useState } from "react";
import { Check, Circle, ClipboardList } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import type { TodoItem } from "@/lib/api/types";

function TodoRow({ item }: { item: TodoItem }) {
  if (item.status === "completed") {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Check className="size-3.5 text-success" />
        <span className="line-through">{item.title}</span>
      </div>
    );
  }
  if (item.status === "in_progress") {
    return (
      <div className="flex items-center gap-2 text-xs font-medium text-primary">
        <Circle className="size-3.5 animate-pulse fill-primary/20" />
        <span>{item.title}</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground/70">
      <Circle className="size-3.5" />
      <span>{item.title}</span>
    </div>
  );
}

export default function TodoPanel() {
  const todos = useChatStore((s) => s.todos);
  const [collapsed, setCollapsed] = useState(false);

  if (todos.length === 0) return null;

  const done = todos.filter((t) => t.status === "completed").length;
  const total = todos.length;
  const pct = Math.round((done / total) * 100);

  return (
    <div className="shrink-0 border-b border-border bg-card/80 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-4xl px-4 py-2">
        {/* 头部：标题 + 进度 + 折叠 */}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex w-full items-center gap-2 text-sm"
        >
          <ClipboardList className="size-4 text-primary" />
          <span className="font-medium">任务进度</span>
          <span className="text-xs text-muted-foreground">{done}/{total} 完成</span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-success transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="w-8 text-right text-xs text-muted-foreground">{pct}%</span>
          <span className="text-muted-foreground">{collapsed ? "▾" : "▴"}</span>
        </button>
        {/* 任务列表（可折叠，默认展开） */}
        {!collapsed && (
          <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {todos.map((t) => (
              <TodoRow key={t.id} item={t} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
