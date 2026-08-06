/**
 * 消息流 — MessageBubble 气泡 + 工具调用折叠 + 系统提示（notices）+ 流式工具直播块。
 * 数据源：chatStore.messages / notices / toolCalls。
 */

import { useMemo } from "react";
import { Wrench, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import type { Message } from "@/lib/api/types";
import MessageBubble from "./MessageBubble";
import ApprovalCard from "./ApprovalCard";

/** 历史里的 tool 角色消息 → 折叠块 */
function ToolMessageBlock({ message }: { message: Message }) {
  return (
    <div className="rounded-xl border border-border bg-muted/50 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-muted-foreground">
        <Wrench className="size-3.5" />
        tool 调用结果
      </div>
      <pre className="mt-1 whitespace-pre-wrap break-all text-muted-foreground">{message.content}</pre>
    </div>
  );
}

export default function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const notices = useChatStore((s) => s.notices);
  const toolCalls = useChatStore((s) => s.toolCalls);

  // 流式进行中的 tool_call（当前 run）→ 渲染为消息流里的折叠块
  const liveToolIds = useMemo(() => Object.keys(toolCalls), [toolCalls]);

  // 最后一条 assistant 消息是否流式中（显示光标）
  const lastIndex = messages.length - 1;
  const lastIsStreaming =
    messages.length > 0 && messages[lastIndex].role === "assistant" && messages[lastIndex].id === null;

  return (
    <div className="flex flex-col gap-3 py-4">
      {/* 系统提示（错误/压缩/审批失效） */}
      {notices.map((n, i) => (
        <div
          key={`notice-${i}`}
          className={cn(
            "mx-auto w-full max-w-md rounded-xl border px-3 py-2 text-xs",
            n.kind === "error"
              ? "border-red-300/60 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
              : "border-border bg-muted/60 text-muted-foreground",
          )}
        >
          <span className="flex items-center gap-1.5">
            {n.kind === "error" ? <AlertCircle className="size-3.5" /> : <Info className="size-3.5" />}
            {n.text}
          </span>
        </div>
      ))}

      {messages.map((m, i) => {
        // data-msg-index：概览标尺定位锚点（v3 §3.4）
        const anchorProps = { "data-msg-index": i };
        if (m.role === "tool") {
          return (
            <div key={`m-${m.id ?? i}`} {...anchorProps} className="mx-auto w-full max-w-[85%]">
              <ToolMessageBlock message={m} />
            </div>
          );
        }
        return (
          <div key={`m-${m.id ?? i}`} {...anchorProps}>
            <MessageBubble
              message={m}
              streaming={i === lastIndex && lastIsStreaming}
            />
          </div>
        );
      })}

      {/* 流式工具调用直播块 */}
      {liveToolIds.length > 0 && (
        <div className="mx-auto w-full max-w-[85%]">
          <div className="expand-down rounded-xl border border-dashed border-border bg-card px-3 py-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
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
      {/* 高风险审批卡片（前端功能规划 §4.2：pending 时插入对话流，含历史折叠行） */}
      <ApprovalCard />
    </div>
  );
}
