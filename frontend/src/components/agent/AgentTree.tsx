/**
 * Agent 调用链（主→子委派直播）。
 *
 * MVP 用轻量 DOM 树（自测版务实取舍：vis-network 在 jsdom 下不可测、
 * 依赖重；设计文档中的 vis-network 增强版标注为后置项）。
 * 数据源：chatStore.agentTree（契约 subagent 事件）。
 */

import { Network, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";

export default function AgentTree() {
  const tree = useChatStore((s) => s.agentTree);

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-neutral-500">
        <Network className="size-3.5" /> Agent 调用链
        {tree.length > 0 && (
          <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-1.5 text-[10px] text-neutral-500">
            {tree.length}
          </span>
        )}
      </div>
      {tree.length === 0 ? (
        <div className="mt-6 text-center text-xs text-neutral-400">暂无子 Agent 委派</div>
      ) : (
        <div className="space-y-1">
          {/* 根：主 Agent */}
          <div className="flex items-center gap-1.5 rounded-md bg-neutral-100 dark:bg-neutral-800 px-2 py-1 text-xs font-medium">
            <Circle className="size-2 fill-blue-500 text-blue-500" />
            主 Agent
          </div>
          {tree.map((node) => (
            <div key={node.key} className="relative pl-5">
              {/* 连线 */}
              <span className="absolute left-1.5 top-0 h-full w-px bg-neutral-300 dark:bg-neutral-700" />
              <span className="absolute left-1.5 top-3.5 h-px w-3 bg-neutral-300 dark:bg-neutral-700" />
              <div
                className={cn(
                  "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                  node.status === "running"
                    ? "border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-950"
                    : "border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950",
                )}
              >
                <Circle
                  className={cn(
                    "size-2",
                    node.status === "running" ? "fill-blue-500 text-blue-500 animate-pulse" : "fill-green-500 text-green-500",
                  )}
                />
                <span className="font-mono">{node.name}</span>
                <span className="ml-auto text-[10px] text-neutral-400">{node.status}</span>
              </div>
              {node.summary && (
                <div className="ml-1 mt-0.5 text-[10px] text-neutral-500 line-clamp-2">{node.summary}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
