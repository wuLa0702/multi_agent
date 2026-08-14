/**
 * ChatInput — 对话输入框（两行式独立组件，v2 §3.2 ⭐核心）。
 * 第一行工具栏：附件（mock）/ 代理模式 / 模型 / 上下文用量（mock）/ 更多（mock）。
 * 第二行：输入区（1-6 行自适应，150ms 高度过渡）+ 发送/停止。
 * Props 驱动：showAttach/showAgentMode/showModel/showContextUsage/onSend/onCancel。
 * 内部状态自包含，外部只传配置和回调。
 */

import { useRef, useState } from "react";
import { Paperclip, Send, Square, MoreHorizontal, Loader2, BookUp, BookDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
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
  const [attachments, setAttachments] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 代理模式（2026-08-04 P1）：存 chatStore，随请求透传后端
  const agentMode = useChatStore((s) => s.agentMode);
  const setAgentMode = useChatStore((s) => s.setAgentMode);

  /** 高度自伸缩（v3 §3.3）：scrollHeight 实时测量，44~320px，150ms 过渡 */
  const autosize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto"; // 先重置再测，否则只增不减
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 44), 320)}px`;
  };

  const streamStatus = useChatStore((s) => s.streamStatus);
  const providers = useChatStore((s) => s.providers);
  const selectedModelId = useChatStore((s) => s.selectedModelId);
  const setSelectedModelId = useChatStore((s) => s.setSelectedModelId);
  const sessionId = useChatStore((s) => s.sessionId);
  const messages = useChatStore((s) => s.messages);

  const isStreaming = streamStatus === "connecting" || streamStatus === "streaming";
  const isAwaiting = streamStatus === "awaiting_approval";
  const busy = isStreaming || isAwaiting || disabled;

  /** 保存到 wiki：取最后一条 assistant 消息 → POST /v1/export/wiki（2026-08-13 双向链路） */
  const [wikiSaving, setWikiSaving] = useState(false);
  const handleSaveToWiki = async () => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (!lastAssistant || !sessionId) {
      showToast("没有可保存的助手回复", "info");
      return;
    }
    setWikiSaving(true);
    try {
      const path = `对话-${sessionId}-${Date.now()}`;
      const r = await api.exportToWiki({
        path,
        content: lastAssistant.content,
        title: `对话-${sessionId}`,
      });
      showToast(`已保存到 wiki：${r.path}`, "success");
    } catch (e) {
      showToast(`保存失败：${e instanceof Error ? e.message : String(e)}（检查 wiki 是否启动 8766）`, "error");
    } finally {
      setWikiSaving(false);
    }
  };

  /** 从 wiki 拉取：path → GET /v1/export/wiki/pages/{path} → 注入对话（2026-08-13） */
  const [wikiPath, setWikiPath] = useState("");
  const [wikiLoading, setWikiLoading] = useState(false);
  const handleReadFromWiki = async () => {
    const path = wikiPath.trim();
    if (!path) {
      showToast("输入 wiki 页面路径", "info");
      return;
    }
    setWikiLoading(true);
    try {
      const r = await api.readFromWiki(path);
      showToast(`已从 wiki 读取：${r.page.title}`, "success");
      onSend(`【从 wiki 读取 ${r.page.path}】\n\n${r.page.content}`);
    } catch (e) {
      showToast(`拉取失败：${e instanceof Error ? e.message : String(e)}`, "error");
    } finally {
      setWikiLoading(false);
      setWikiPath("");
    }
  };

  const handleSend = () => {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
    if (attachments.length > 0) setAttachments([]);
    // 发送后高度复位到最小（onChange 不触发，手动重置）
    if (textareaRef.current) textareaRef.current.style.height = "44px";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    // 悬浮卡片（v3 §3.2.1）：圆角 16px + shadow-lg + 毛玻璃 + 不贴底
    <div className="rounded-2xl border border-border bg-card/85 p-3 shadow-lg backdrop-blur-md">
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
                  const files = Array.from(e.target.files ?? []);
                  e.target.value = "";
                  if (files.length === 0) return;
                  // 2026-08-04 P2：真实上传 POST /v1/uploads
                  for (const f of files) {
                    void api
                      .uploadFile(f)
                      .then((res) => {
                        setAttachments((prev) => [...prev, res.name].slice(-5));
                        showToast(`已上传 ${res.name}`, "success");
                      })
                      .catch(() => showToast(`上传失败：${f.name}`, "error"));
                  }
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
          {showAgentMode && (
            <AgentModeSelector
              mode={agentMode as AgentMode}
              onChange={(m) => setAgentMode(m)}
              disabled={busy}
            />
          )}
          {showModel && (
            <ModelSelector
              providers={providers}
              selectedModelId={selectedModelId}
              onSelect={setSelectedModelId}
              disabled={busy}
            />
          )}
          {showContextUsage && <ContextUsage />}

          {/* wiki 双向链路（2026-08-13）：保存到 wiki + 从 wiki 拉取 */}
          <button
            type="button"
            disabled={busy || wikiSaving}
            onClick={handleSaveToWiki}
            className="press flex h-8 items-center gap-1 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            title="保存最后一条回复到 wiki 知识库"
            aria-label="保存到 wiki"
          >
            <BookUp className="size-3.5" />
            {wikiSaving ? "保存中…" : "存 wiki"}
          </button>
          <div className="flex items-center gap-1">
            <input
              value={wikiPath}
              onChange={(e) => setWikiPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void handleReadFromWiki()}
              placeholder="wiki路径"
              disabled={busy}
              className="h-8 w-24 rounded-lg border border-border bg-background px-2 text-xs text-muted-foreground outline-none focus-visible:border-ring disabled:opacity-50"
              aria-label="wiki 页面路径"
            />
            <button
              type="button"
              disabled={busy || wikiLoading}
              onClick={handleReadFromWiki}
              className="press flex h-8 items-center gap-1 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
              title="从 wiki 读取页面并注入对话"
              aria-label="从 wiki 拉取"
            >
              <BookDown className="size-3.5" />
              {wikiLoading ? "拉取中…" : "拉wiki"}
            </button>
          </div>

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

      {/* 第二行：输入区 + 发送（v3 §3.3：scrollHeight 实时自伸缩 44~320px，150ms 过渡）
          原生 textarea：shadcn Textarea 带 field-sizing-content，手动 height 被忽略（已踩坑） */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            autosize(e.target);
          }}
          onKeyDown={handleKeyDown}
          placeholder={isAwaiting ? "审批中，暂不可输入" : "输入消息...（Enter 发送，Shift+Enter 换行）"}
          disabled={isAwaiting}
          rows={1}
          className="max-h-[320px] min-h-[44px] w-full flex-1 resize-none rounded-xl border border-border bg-transparent px-4 py-3 text-sm leading-[1.6] outline-none transition-[height] duration-150 ease-out placeholder:text-muted-foreground focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
        {isStreaming ? (
          <Button variant="outline" size="icon" onClick={onCancel} title="停止生成" aria-label="停止生成">
            <Loader2 className="size-4 animate-spin" />
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
