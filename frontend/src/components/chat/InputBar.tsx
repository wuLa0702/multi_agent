/**
 * 输入栏 — 发送 / 取消（流式中）/ 审批中禁用。
 * Enter 发送、Shift+Enter 换行。
 * 模型二级选择（厂商 → 模型）：数据源 GET /v1/providers（后端 DB 配置），
 * 切厂商时自动选中该厂商默认模型；流式中禁用切换。
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
  const providers = useChatStore((s) => s.providers);
  const selectedModelId = useChatStore((s) => s.selectedModelId);
  const setSelectedModelId = useChatStore((s) => s.setSelectedModelId);

  const isStreaming = streamStatus === "connecting" || streamStatus === "streaming";
  const isAwaiting = streamStatus === "awaiting_approval";
  const disabled = isStreaming || isAwaiting;

  // 当前选中模型 → 所属厂商 / 该厂商模型列表（二级联动）
  const selectedProvider =
    providers.find((p) => p.models.some((m) => m.id === selectedModelId)) ?? null;
  const modelOptions = selectedProvider?.models ?? [];

  const handleProviderChange = (slug: string) => {
    const provider = providers.find((p) => p.slug === slug);
    const def = provider?.models.find((m) => m.is_default) ?? provider?.models[0];
    setSelectedModelId(def?.id ?? null);
  };

  const handleSend = () => {
    if (!text.trim() || disabled) return;
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

      {/* 模型二级选择（厂商 → 模型）；providers 拉取失败时不渲染 */}
      {providers.length > 0 && (
        <div className="mb-2 flex items-center gap-2 text-xs">
          <select
            value={selectedProvider?.slug ?? ""}
            onChange={(e) => handleProviderChange(e.target.value)}
            disabled={disabled}
            aria-label="选择模型厂商"
            className="h-7 rounded-md border border-neutral-300 bg-transparent px-2 text-neutral-700 dark:border-neutral-700 dark:text-neutral-300 disabled:opacity-50"
          >
            {providers.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={selectedModelId ?? ""}
            onChange={(e) => setSelectedModelId(e.target.value ? Number(e.target.value) : null)}
            disabled={disabled || modelOptions.length === 0}
            aria-label="选择模型"
            className="h-7 rounded-md border border-neutral-300 bg-transparent px-2 text-neutral-700 dark:border-neutral-700 dark:text-neutral-300 disabled:opacity-50"
          >
            {modelOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
                {m.is_default ? "（默认）" : ""}
              </option>
            ))}
          </select>
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
