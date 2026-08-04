/**
 * ChatInput — 对话输入框（两行式独立组件，v2 §3.2 ⭐核心）。
 * 第一行工具栏：附件（mock）/ 代理模式 / 模型 / 上下文用量（mock）/ 更多（mock）。
 * 第二行：输入区（1-6 行自适应，150ms 高度过渡）+ 发送/停止。
 * Props 驱动：showAttach/showAgentMode/showModel/showContextUsage/onSend/onCancel。
 * 内部状态自包含，外部只传配置和回调。
 */

import { useRef, useState } from "react";
import { Paperclip, Send, Square, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useChatStore } from "@/lib/stores/chatStore";
import AgentModeSelector, { type AgentMode } from "./AgentModeSelector";
import ModelSelector from "./ModelSelector";
import ContextUsage from "./ContextUsage";
import { showToast } from "@/components/shared/Toast";

interface Props {
  showAttach?: boolean;
  showAgentMode?: boolean;
  showModel?: boolean;
  showContextUsage?: boolean;
  onSend: (content: string) => void;
  onCancel?: () => void;
  disabled?: boolean;
}

export default function ChatInput({
  showAttach = true,
  showAgentMode = true,
  showModel = true,
  showContextUsage = true,
  onSend,
  onCancel,
  disabled = false,
}: Props) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AgentMode>("default");
  const [attachments, setAttachments] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const streamStatus = useChatStore((s) => s.streamStatus);
  const providers = useChatStore((s) => s.providers);
  const selectedModelId = useChatStore((s) => s.selectedModelId);
  const setSelectedModelId = useChatStore((s) => s.setSelectedModelId);

  const isStreaming = streamStatus === "connecting" || streamStatus === "streaming";
  const isAwaiting = streamStatus === "awaiting_approval";
  const busy = isStreaming || isAwaiting || disabled;

  const handleSend = () => {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
    if (attachments.length > 0) setAttachments([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-border bg-card/70 p-3 backdrop-blur-sm">
      {isAwaiting && (
        <div className="mb-2 text-center text-xs text-warning">
          等待审批决策…（请在弹出的对话框中操作）
        </div>
      )}

      {/* 第一行：工具栏（v2 §3.2） */}
      {(showAttach || showAgentMode || showModel || showContextUsage) && (
        <div className="mb-2 flex items-center gap-2">
          {showAttach && (
            <>
              <input
                ref={fileRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  const names = Array.from(e.target.files ?? []).map((f) => f.name);
                  if (names.length > 0) {
                    setAttachments((prev) => [...prev, ...names].slice(-5));
                    showToast(`已附加 ${names.length} 个文件（mock）`, "info");
                  }
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
                className="press flex h-8 items-center gap-1 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
                title="附加文件（mock）"
                aria-label="附加文件"
              >
                <Paperclip className="size-3.5" />
                {attachments.length > 0 && (
                  <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">
                    {attachments.length}
                  </span>
                )}
              </button>
            </>
          )}
          {showAgentMode && <AgentModeSelector mode={mode} onChange={setMode} disabled={busy} />}
          {showModel && (
            <ModelSelector
              providers={providers}
              selectedModelId={selectedModelId}
              onSelect={setSelectedModelId}
              disabled={busy}
            />
          )}
          {showContextUsage && <ContextUsage />}

          {/* 更多（mock：清空上下文 / 导出） */}
          <div className="ml-auto">
            <button
              type="button"
              disabled={busy}
              onClick={() => showToast("更多选项：清空上下文 / 导出对话（mock）", "info")}
              className="press flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground hover:text-foreground disabled:opacity-50"
              title="更多选项"
              aria-label="更多选项"
            >
              <MoreHorizontal className="size-4" />
            </button>
          </div>
        </div>
      )}

      {/* 第二行：输入区 + 发送 */}
      <div className="flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isAwaiting ? "审批中，暂不可输入" : "输入消息...（Enter 发送，Shift+Enter 换行）"}
          disabled={isAwaiting}
          rows={1}
          className="min-h-[36px] max-h-[144px] flex-1 resize-none transition-[height] duration-150"
          style={{ height: Math.min(36 + Math.floor(text.length / 60) * 18, 144) }}
        />
        {isStreaming ? (
          <Button variant="outline" size="icon" onClick={onCancel} title="停止生成" aria-label="停止生成">
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={handleSend}
            disabled={!text.trim() || isAwaiting}
            title="发送"
            aria-label="发送"
            className="btn-lift press shrink-0"
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
