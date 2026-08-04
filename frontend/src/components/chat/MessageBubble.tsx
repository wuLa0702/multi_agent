/**
 * MessageBubble — 单条消息气泡（v2 §3.3）。
 * 助手消息：左侧 AI 头像（28px 圆标）+ 气泡卡片 + 下方时间 + hover 操作按钮（复制/重新生成/反馈）。
 * 用户消息：右对齐主题色气泡 + 下方时间（单用户无头像）。
 * 圆角 16px、shadow-sm、内边距 12px 16px；流式输出光标闪烁。
 */

import { useState } from "react";
import { Bot, Copy, RefreshCw, ThumbsUp, ThumbsDown, Check, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { showToast } from "@/components/shared/Toast";
import StreamingMarkdown from "./StreamingMarkdown";
import type { Message } from "@/lib/api/types";

interface Props {
  message: Message;
  streaming?: boolean; // 流式进行中（显示光标 + 不显示时间）
  onRegenerate?: () => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 助手消息（左对齐 + AI 头像 + hover 操作） */
function AssistantBubble({ message, streaming, onRegenerate }: Props) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      showToast("复制失败", "error");
    }
  };

  return (
    <div className="msg-enter group flex items-start gap-2.5">
      {/* AI 头像 28px 圆标（渐变底） */}
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-violet-500 text-primary-foreground shadow-sm">
        <Bot className="size-4" />
      </div>

      <div className="min-w-0 max-w-[85%]">
        <div className="rounded-2xl rounded-tl-md border border-border bg-card px-4 py-3 shadow-sm">
          <StreamingMarkdown content={message.content} />
          {streaming && <span className="cursor-blink ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-primary" />}
        </div>

        {/* 下方：时间 + hover 操作 */}
        <div className="mt-1 flex items-center gap-2 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
          {!streaming && <span className="text-[10px] text-muted-foreground">{formatTime(message.created_at)}</span>}
          <button
            type="button"
            onClick={copy}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary"
            aria-label="复制"
          >
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
            {copied ? "已复制" : "复制"}
          </button>
          {onRegenerate && (
            <button
              type="button"
              onClick={onRegenerate}
              className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary"
              aria-label="重新生成"
            >
              <RefreshCw className="size-3" /> 重新生成
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setFeedback("up");
              showToast("感谢反馈", "success");
            }}
            className={cn("text-[10px] text-muted-foreground hover:text-success", feedback === "up" && "text-success")}
            aria-label="好评"
          >
            <ThumbsUp className="size-3" />
          </button>
          <button
            type="button"
            onClick={() => {
              setFeedback("down");
              showToast("已记录反馈", "info");
            }}
            className={cn("text-[10px] text-muted-foreground hover:text-warning", feedback === "down" && "text-warning")}
            aria-label="差评"
          >
            <ThumbsDown className="size-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

/** 用户消息（右对齐主题色） */
function UserBubble({ message }: Props) {
  return (
    <div className="msg-enter flex flex-col items-end gap-1">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-tr-md bg-primary px-4 py-3 text-sm text-primary-foreground shadow-sm">
        {message.content}
      </div>
      <span className="text-[10px] text-muted-foreground">{formatTime(message.created_at)}</span>
    </div>
  );
}

/** 带附件的用户消息（引用文件提示，v2 §3.2 左下角） */
export function AttachedUserBubble({ message, attachments }: Props & { attachments: string[] }) {
  return (
    <div className="msg-enter flex flex-col items-end gap-1">
      <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-primary px-4 py-3 text-sm text-primary-foreground shadow-sm">
        {attachments.length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1">
            {attachments.map((a) => (
              <span
                key={a}
                className="flex items-center gap-1 rounded bg-white/15 px-1.5 py-0.5 text-[10px]"
              >
                <Paperclip className="size-2.5" /> {a}
              </span>
            ))}
          </div>
        )}
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
      </div>
      <span className="text-[10px] text-muted-foreground">{formatTime(message.created_at)}</span>
    </div>
  );
}

export default function MessageBubble(props: Props) {
  if (props.message.role === "user") return <UserBubble {...props} />;
  if (props.message.role === "tool") return null; // tool 消息由 MessageList 折叠块处理
  return <AssistantBubble {...props} />;
}
