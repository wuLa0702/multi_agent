/**
 * 输入栏 — 发送 / 取消（流式中）/ 审批中禁用。
 * Enter 发送、Shift+Enter 换行。
 */

import { useState } from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useChatStore } from "@/lib/stores/chatStore";

export default function InputBar() {
  const [text, setText] = useState("");
  const streamStatus = useChatStore((s) => s.streamStatus);
  const send = useChatStore((s) => s.send);
  const cancel = useChatStore((s) => s.cancel);

  const isStreaming = streamStatus === "connecting" || streamStatus === "streaming";
  const isAwaiting = streamStatus === "awaiting_approval";

  const handleSend = () => {
    if (!text.trim() || isStreaming || isAwaiting) return;
    void send(text);
    setText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-neutral-200 dark:border-neutral-800 p-3">
      {isAwaiting && (
        <div className="mb-2 text-center text-xs text-amber-600 dark:text-amber-400">
          等待审批决策…（请在弹出的对话框中操作）
        </div>
      )}
      <div className="flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isAwaiting ? "审批中，暂不可输入" : "发送消息…（Enter 发送，Shift+Enter 换行）"}
          disabled={isAwaiting}
          rows={2}
          className="min-h-[44px] resize-none"
        />
        {isStreaming ? (
          <Button variant="outline" size="icon" onClick={cancel} title="停止生成" aria-label="停止生成">
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={handleSend}
            disabled={!text.trim() || isAwaiting}
            title="发送"
            aria-label="发送"
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
