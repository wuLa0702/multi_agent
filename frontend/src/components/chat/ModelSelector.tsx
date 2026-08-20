/**
 * ModelSelector — 模型选择器（v2 §3.2 工具栏，厂商→模型两级下拉）。
 * 显示当前模型名；点击展开厂商→模型选择；切厂商自动选默认模型。
 *
 * v6 评审 P1-4 重构（修 #11：模型标"默认"泛滥）：
 * - 去每行"默认"标签 → 仅系统推荐模型标「推荐」徽标
 * - 厂商分组 + 顶部搜索框过滤模型名
 */

import { useState } from "react";
import { ChevronDown, Cpu, Search, Star } from "lucide-react";
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
  const [query, setQuery] = useState("");

  const selectedProvider = providers.find((p) => p.models.some((m) => m.id === selectedModelId));
  const selectedModel = selectedProvider?.models.find((m) => m.id === selectedModelId);
  const displayName = selectedModel?.name ?? "选择模型";

  const selectProvider = (provider: ProviderInfo) => {
    const def = provider.models.find((m) => m.is_default) ?? provider.models[0];
    onSelect(def?.id ?? null);
  };

  const q = query.trim().toLowerCase();
  const filteredProviders = q
    ? providers
        .map((p) => ({ ...p, models: p.models.filter((m) => m.name.toLowerCase().includes(q)) }))
        .filter((p) => p.models.length > 0)
    : providers;

  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled || providers.length === 0}
        onClick={() => {
          setQuery("");
          setOpen((v) => !v);
        }}
        className="press flex h-7 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground disabled:opacity-50"
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
          <div className="expand-down absolute bottom-full left-0 z-40 mb-1.5 w-64 rounded-xl border border-border bg-popover p-1 shadow-lg">
            {/* 搜索框（P1-4） */}
            <div className="relative mb-1 px-1 pt-0.5">
              <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索模型…"
                className="h-7 w-full rounded-md border border-border bg-background pl-7 pr-2 text-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring"
                aria-label="搜索模型"
              />
            </div>

            {filteredProviders.length === 0 ? (
              <div className="py-6 text-center text-xs text-muted-foreground">未找到匹配模型</div>
            ) : (
              filteredProviders.map((p) => (
                <div key={p.slug} className="mb-0.5">
                  <div className="flex items-center justify-between px-2.5 py-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {p.name}
                    </span>
                    {/* 选该厂商默认模型（P1-4：改叫「推荐」） */}
                    <button
                      type="button"
                      className="flex items-center gap-0.5 text-[10px] text-primary hover:underline"
                      onClick={() => selectProvider(p)}
                    >
                      <Star className="size-2.5" /> 推荐
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
                        "flex w-full items-center justify-between gap-1 rounded-lg px-2.5 py-1.5 text-xs transition-colors",
                        m.id === selectedModelId ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                      )}
                    >
                      <span className="truncate">{m.name}</span>
                      {m.is_default && (
                        <span className="flex shrink-0 items-center gap-0.5 rounded bg-primary/10 px-1 py-0.5 text-[10px] text-primary">
                          <Star className="size-2.5" /> 推荐
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
