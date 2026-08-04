/**
 * ChatMessages — 对话消息区组件（v3 §3.1.3，flex:1 独立滚动）。
 * 宽度由 CSS 变量 --chat-max-width / --chat-padding-x 控制（v3 §2.2 分级响应式）。
 * 右侧可挂载 OverviewRuler 概览标尺（消息 > 10 条显示）。
 */

import { useRef } from "react";
import { useChatStore } from "@/lib/stores/chatStore";
import MessageList from "./MessageList";
import OverviewRuler from "./OverviewRuler";
import EmptyChat from "./EmptyChat";

export default function ChatMessages() {
  const messages = useChatStore((s) => s.messages);
  const streamStatus = useChatStore((s) => s.streamStatus);
  const scrollRef = useRef<HTMLDivElement>(null);

  const isEmpty = messages.length === 0 && streamStatus === "idle";

  return (
    <div ref={scrollRef} className="chat-scroll min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex min-h-full w-full" style={{ maxWidth: "var(--chat-max-width)", padding: "0 var(--chat-padding-x)" }}>
        <div className="flex min-w-0 flex-1 flex-col">
          {isEmpty ? <EmptyChat /> : <MessageList />}
        </div>
        {/* 右侧概览标尺（v3 §3.4：消息 ≥ 10 条显示） */}
        {!isEmpty && messages.length >= 10 && (
          <OverviewRuler scrollRef={scrollRef} />
        )}
      </div>
    </div>
  );
}
