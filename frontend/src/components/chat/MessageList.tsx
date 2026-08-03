/**
 * 消息流 — 对话气泡 + 工具调用折叠 + 系统提示（notices）。
 * 数据源：chatStore.messages（流式 token 累积）+ chatStore.notices + chatStore.toolCalls。
 */

import { useMemo } from "react";
import { Bot, User, AlertCircle, Info, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import type { Message } from "@/lib/api/types";
import StreamingMarkdown from "./StreamingMarkdown";
import EmptyState from "@/components/shared/EmptyState";

/** 历史里的 tool 角色消息 → 折叠块 */
function ToolMessageBlock({ message }: { message: Message }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 text-neutral-500 font-medium">
        <Wrench className="size-3.5" />
        tool 调用结果
      </div>
      <pre className="mt-1 whitespace-pre-wrap break-all text-neutral-600 dark:text-neutral-400">
        {message.content}
      </pre>
    </div>
  );
}

export default function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const notices = useChatStore((s) => s.notices);
  const toolCalls = useChatStore((s) => s.toolCalls);

  // 流式进行中的 tool_call（当前 run）→ 渲染为消息流里的折叠块
  const liveToolIds = useMemo(() => Object.keys(toolCalls), [toolCalls]);

  if (messages.length === 0 && notices.length === 0) {
    return (
      <EmptyState
        icon={Bot}
        title="多 Agent 工作台"
        desc="发送消息开始对话。Agent 的工具调用、子 Agent 委派与审批请求会实时展示。"
      />
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      {/* 系统提示（错误/压缩/审批失效） */}
      {notices.map((n, i) => (
        <div
          key={`notice-${i}`}
          className={cn(
            "mx-auto w-full max-w-md rounded-lg border px-3 py-2 text-xs",
            n.kind === "error"
              ? "border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300"
              : "border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400",
          )}
        >
          <span className="flex items-center gap-1.5">
            {n.kind === "error" ? <AlertCircle className="size-3.5" /> : <Info className="size-3.5" />}
            {n.text}
          </span>
        </div>
      ))}

      {messages.map((m, i) => {
        if (m.role === "user") {
          return (
            <div key={`m-${m.id ?? i}`} className="flex justify-end">
              <div className="flex max-w-[75%] items-start gap-2">
                <div className="rounded-2xl rounded-tr-sm bg-primary px-3 py-2 text-sm text-primary-foreground whitespace-pre-wrap break-words">
                  {m.content}
                </div>
                <User className="mt-2 size-4 shrink-0 text-neutral-400" />
              </div>
            </div>
          );
        }
        if (m.role === "tool") {
          return (
            <div key={`m-${m.id ?? i}`} className="flex justify-center w-full max-w-[85%] mx-auto">
              <ToolMessageBlock message={m} />
            </div>
          );
        }
        // assistant（含流式）
        return (
          <div key={`m-${m.id ?? i}`} className="flex justify-start">
            <div className="flex max-w-[85%] items-start gap-2">
              <Bot className="mt-2 size-4 shrink-0 text-neutral-400" />
              <div className="rounded-2xl rounded-tl-sm border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 px-3 py-2">
                <StreamingMarkdown content={m.content} />
              </div>
            </div>
          </div>
        );
      })}

      {/* 流式工具调用直播块 */}
      {liveToolIds.length > 0 && (
        <div className="flex justify-center">
          <div className="w-full max-w-[85%] rounded-lg border border-dashed border-neutral-300 dark:border-neutral-700 px-3 py-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-neutral-500">
              <Wrench className="size-3.5" /> 工具调用
            </div>
            {liveToolIds.map((id) => {
              const tc = toolCalls[id];
              return (
                <div key={id} className="mt-1.5 text-xs">
                  <span className="font-mono">{tc.name}</span>
                  <span
                    className={cn(
                      "ml-2 rounded px-1.5 py-0.5 text-[10px]",
                      tc.status === "running" && "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
                      tc.status === "success" && "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300",
                      tc.status === "error" && "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
                    )}
                  >
                    {tc.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
