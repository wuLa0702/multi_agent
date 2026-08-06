/**
 * ModeSwitcher — 视图模式切换（v5.0 §3.3 手动入口，标题栏右侧）。
 * 四种模式：对话 / 子代理 / 任务规划 / 沙箱（预留）；当前模式勾选；手动切换优先级最高。
 */

import { useState } from "react";
import { LayoutGrid, MessageSquare, Users, ClipboardList, Code2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUiModeStore, type UiMode } from "@/lib/stores/uiModeStore";

const MODES: { key: UiMode; label: string; icon: typeof MessageSquare }[] = [
  { key: "chat", label: "对话模式", icon: MessageSquare },
  { key: "subagent", label: "子代理模式", icon: Users },
  { key: "todo", label: "任务规划模式", icon: ClipboardList },
  { key: "sandbox", label: "沙箱模式", icon: Code2 },
];

export default function ModeSwitcher() {
  const mode = useUiModeStore((s) => s.mode);
  const setMode = useUiModeStore((s) => s.setMode);
  const [open, setOpen] = useState(false);

  const current = MODES.find((m) => m.key === mode) ?? MODES[0];
  const CurrentIcon = current.icon;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-xs text-muted-foreground transition hover:bg-accent"
        aria-label="视图模式"
      >
        <LayoutGrid className="size-3.5" />
        <CurrentIcon className="size-3.5" />
        <span>{current.label}</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-40 mt-1 w-40 rounded-xl border border-border bg-popover p-1 shadow-lg">
            {MODES.map((m) => {
              const Icon = m.icon;
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => {
                    setMode(m.key, true); // 手动切换 → 优先级最高
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition hover:bg-accent",
                    m.key === mode && "font-medium text-primary"
                  )}
                >
                  <Icon className="size-3.5" />
                  {m.label}
                  {m.key === mode && <span className="ml-auto">✓</span>}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
