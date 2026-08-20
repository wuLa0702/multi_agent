/**
 * ModeSwitcher — 视图模式切换（v5.0 §3.3 手动入口 + 2026-08-20 T3 图标化）。
 * 四种模式：对话 / 子代理 / 任务规划 / 沙箱（预留）；当前模式图标显示 + hover tooltip 说明。
 * 手动切换优先级最高（autoUpgrade 不覆盖 manualOverride）。
 */

import { useState } from "react";
import { MessageSquare, Users, ClipboardList, Code2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUiModeStore, type UiMode } from "@/lib/stores/uiModeStore";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

const MODES: { key: UiMode; label: string; tooltip: string; icon: typeof MessageSquare }[] = [
  { key: "chat", label: "对话", tooltip: "对话模式：标准聊天，子代理自动委派", icon: MessageSquare },
  { key: "subagent", label: "子代理", tooltip: "子代理模式：显示子代理调用链，工具可视化", icon: Users },
  { key: "todo", label: "任务规划", tooltip: "任务规划模式：先拆解任务为步骤清单，再逐步执行", icon: ClipboardList },
  { key: "sandbox", label: "沙箱", tooltip: "沙箱模式：代码执行隔离环境（预留）", icon: Code2 },
];

export default function ModeSwitcher() {
  const mode = useUiModeStore((s) => s.mode);
  const setMode = useUiModeStore((s) => s.setMode);
  const [open, setOpen] = useState(false);

  const current = MODES.find((m) => m.key === mode) ?? MODES[0];
  const CurrentIcon = current.icon;

  return (
    <div className="relative">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition hover:bg-accent hover:text-foreground"
            aria-label={current.tooltip}
          >
            <CurrentIcon className="size-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs">
          {current.tooltip}
        </TooltipContent>
      </Tooltip>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-40 mt-1 w-48 rounded-xl border border-border bg-popover p-1 shadow-lg">
            {MODES.map((m) => {
              const Icon = m.icon;
              return (
                <Tooltip key={m.key}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={() => {
                        setMode(m.key, true); // 手动切换 → 优先级最高
                        setOpen(false);
                      }}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition hover:bg-accent",
                        m.key === mode && "font-medium text-primary",
                      )}
                    >
                      <Icon className="size-3.5" />
                      {m.label}
                      {m.key === mode && <span className="ml-auto">✓</span>}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="left" className="text-xs">
                    {m.tooltip}
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
