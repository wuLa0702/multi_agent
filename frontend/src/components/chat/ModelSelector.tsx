/**
 * ModelSelector — 模型选择器（v2 §3.2 工具栏，厂商→模型两级下拉）。
 * 显示当前模型名；点击展开厂商→模型选择；切厂商自动选默认模型。
 */

import { useState } from "react";
import { ChevronDown, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProviderInfo } from "@/lib/api/types";

interface Props {
  providers: ProviderInfo[];
  selectedModelId: number | null;
  onSelect: (modelId: number | null) => void;
  disabled?: boolean;
}

export default function ModelSelector({ providers, selectedModelId, onSelect, disabled }: Props) {
  const [open, setOpen] = useState(false);

  const selectedProvider = providers.find((p) => p.models.some((m) => m.id === selectedModelId));
  const selectedModel = selectedProvider?.models.find((m) => m.id === selectedModelId);
  const displayName = selectedModel?.name ?? "选择模型";

  const selectProvider = (provider: ProviderInfo) => {
    const def = provider.models.find((m) => m.is_default) ?? provider.models[0];
    onSelect(def?.id ?? null);
  };

  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled || providers.length === 0}
        onClick={() => setOpen((v) => !v)}
        className="press flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground disabled:opacity-50"
        aria-label="选择模型"
      >
        <Cpu className="size-3.5 text-primary" />
        <span className="max-w-36 truncate font-medium">{displayName}</span>
        <ChevronDown className="size-3 text-muted-foreground" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          {/* 向上展开（v3 §3.2.2：输入框内下拉默认向上） */}
          <div className="expand-down absolute bottom-full left-0 z-40 mb-1.5 w-56 rounded-xl border border-border bg-popover p-1 shadow-lg">
            {providers.map((p) => (
              <div key={p.slug} className="mb-0.5">
                <div className="flex items-center justify-between px-2.5 py-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {p.name}
                  </span>
                  <button
                    type="button"
                    className="text-[10px] text-primary hover:underline"
                    onClick={() => selectProvider(p)}
                  >
                    默认
                  </button>
                </div>
                {p.models.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => {
                      onSelect(m.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition-colors",
                      m.id === selectedModelId ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                    )}
                  >
                    <span className="truncate">{m.name}</span>
                    {m.is_default && <span className="text-[10px] text-muted-foreground">默认</span>}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
