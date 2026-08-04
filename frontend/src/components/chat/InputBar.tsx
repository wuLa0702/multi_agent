/**
 * 输入栏（底部控制区，方案 §5.1.2）— 从左到右：
 * 代理模式四档（默认/规划/代理/自动）→ 模型二级选择 → 输入框 → 发送/停止。
 * Enter 发送、Shift+Enter 换行；中文输入法 isComposing 防误触。
 * 代理模式为前端概念（mock 状态，暂不传后端）；自动模式二次确认。
 */

import { useState } from "react";
import { Send, Square, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useChatStore } from "@/lib/stores/chatStore";
import { showConfirm } from "@/components/ui/confirm-dialog";

/** 代理模式四档（方案 §5.1.2-3） */
export const AGENT_MODES = [
  { key: "default", label: "默认", desc: "标准对话，按需调用工具" },
  { key: "plan", label: "规划", desc: "先拆解任务再执行" },
  { key: "agent", label: "代理", desc: "自主完成多步骤任务" },
  { key: "auto", label: "自动", desc: "自动选择最优模式" },
] as const;

export type AgentMode = (typeof AGENT_MODES)[number]["key"];

export default function InputBar() {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AgentMode>("default");
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

  const handleModeChange = async (key: AgentMode) => {
    // 自动模式二次确认（方案 §5.1.2-3）
    if (key === "auto" && key !== mode) {
      const ok = await showConfirm("自动模式将由系统根据任务复杂程度选择执行策略，是否继续？", {
        title: "切换自动模式",
        confirmLabel: "确认",
        cancelLabel: "取消",
      });
      if (!ok) return;
    }
    setMode(key);
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

  const currentMode = AGENT_MODES.find((m) => m.key === mode)!;

  return (
    <div className="border-t border-border bg-card/60 p-3 backdrop-blur-sm">
      {isAwaiting && (
        <div className="mb-2 text-center text-xs text-warning">
          等待审批决策…（请在弹出的对话框中操作）
        </div>
      )}

      <div className="flex items-center gap-2">
        {/* 代理模式四档（方案 §5.1.2-3） */}
        <div className="group relative shrink-0">
          <button
            type="button"
            disabled={disabled}
            onClick={() => {
              const idx = AGENT_MODES.findIndex((m) => m.key === mode);
              void handleModeChange(AGENT_MODES[(idx + 1) % AGENT_MODES.length].key);
            }}
            title={currentMode.desc}
            className="press flex h-9 items-center gap-1 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground disabled:opacity-50"
            aria-label="代理模式"
          >
            <span className="font-medium">{currentMode.label}</span>
            <ChevronDown className="size-3 text-muted-foreground" />
          </button>
          {/* hover 显示全部四档 */}
          <div className="invisible absolute bottom-full left-0 z-20 mb-1 w-40 rounded-lg border border-border bg-popover p-1 opacity-0 shadow-lg transition-all duration-150 group-hover:visible group-hover:opacity-100">
            {AGENT_MODES.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => void handleModeChange(m.key)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors ${
                  m.key === mode ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                }`}
              >
                <div className="font-medium">{m.label}</div>
                <div className="text-[10px] text-muted-foreground">{m.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 模型二级选择（厂商 → 模型）；providers 拉取失败时不渲染 */}
        {providers.length > 0 && (
          <>
            <select
              value={selectedProvider?.slug ?? ""}
              onChange={(e) => handleProviderChange(e.target.value)}
              disabled={disabled}
              aria-label="选择模型厂商"
              className="h-9 shrink-0 rounded-lg border border-border bg-background px-2 text-xs text-foreground disabled:opacity-50"
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
              className="h-9 shrink-0 rounded-lg border border-border bg-background px-2 text-xs text-foreground disabled:opacity-50"
            >
              {modelOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                  {m.is_default ? "（默认）" : ""}
                </option>
              ))}
            </select>
          </>
        )}

        {/* 输入框（弹性） */}
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isAwaiting ? "审批中，暂不可输入" : "发送消息…（Enter 发送，Shift+Enter 换行）"}
          disabled={isAwaiting}
          rows={2}
          className="min-h-[36px] flex-1 resize-none"
        />

        {/* 发送 / 停止 */}
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
            className="btn-lift press shrink-0"
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
