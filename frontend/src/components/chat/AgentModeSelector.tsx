/**
 * AgentModeSelector — 代理模式选择器（v2 §3.2 工具栏，四档下拉）。
 * 默认/规划/代理/自动；自动模式二次确认；显示当前模式 + 说明。
 */

import { useState } from "react";
import { ChevronDown, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { showConfirm } from "@/components/ui/confirm-dialog";

export const AGENT_MODES = [
  { key: "default", label: "默认", desc: "标准对话，按需调用工具" },
  { key: "plan", label: "规划", desc: "先拆解任务再执行" },
  { key: "agent", label: "代理", desc: "自主完成多步骤任务" },
  { key: "auto", label: "自动", desc: "自动选择最优模式" },
] as const;

export type AgentMode = (typeof AGENT_MODES)[number]["key"];

interface Props {
  mode: AgentMode;
  onChange: (mode: AgentMode) => void;
  disabled?: boolean;
}

export default function AgentModeSelector({ mode, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const current = AGENT_MODES.find((m) => m.key === mode)!;

  const select = async (key: AgentMode) => {
    if (key === "auto" && key !== mode) {
      const ok = await showConfirm("自动模式将由系统根据任务复杂程度选择执行策略，是否继续？", {
        title: "切换自动模式",
        confirmLabel: "确认",
        cancelLabel: "取消",
      });
      if (!ok) return;
    }
    onChange(key);
    setOpen(false);
  };

  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        title={current.desc}
        className="press flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground disabled:opacity-50"
        aria-label="代理模式"
      >
        <Bot className="size-3.5 text-primary" />
        <span className="font-medium">{current.label}</span>
        <ChevronDown className="size-3 text-muted-foreground" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          {/* 向上展开（v3 §3.2.2：输入框内下拉默认向上） */}
          <div className="expand-down absolute bottom-full left-0 z-40 mb-1.5 w-44 rounded-xl border border-border bg-popover p-1 shadow-lg">
            {AGENT_MODES.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => void select(m.key)}
                className={cn(
                  "w-full rounded-lg px-2.5 py-2 text-left text-xs transition-colors",
                  m.key === mode ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                )}
              >
                <div className="flex items-center gap-1.5 font-medium">
                  <Bot className="size-3" /> {m.label}
                </div>
                <div className="mt-0.5 pl-4.5 text-[10px] text-muted-foreground">{m.desc}</div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
