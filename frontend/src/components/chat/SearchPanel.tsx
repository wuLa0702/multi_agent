/**
 * SearchPanel — 对话内本地搜索（v6 评审 P1-5，修 #2：搜索 mock → 前端本地搜索）。
 * 在已加载的当前会话消息里做关键词匹配：高亮 + 点击跳转消息。
 * TODO: 后端全文检索 API 就绪后切换真实接口（本组件渲染形态可复用）。
 */

import { useEffect, useMemo, useState } from "react";
import { Search, User, Bot, CornerDownRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import { messageScrollRef } from "@/lib/messageScroll";
import SearchInput from "@/components/common/SearchInput";

interface Props {
  onClose: () => void;
}

/** 截取命中片段（匹配前 40 字 + 匹配串 + 后 80 字，超长省略号） */
function snippet(text: string, q: string): { head: string; match: string; tail: string } {
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return { head: text.slice(0, 60), match: "", tail: "" };
  const start = Math.max(0, idx - 40);
  const end = Math.min(text.length, idx + q.length + 80);
  return {
    head: (start > 0 ? "…" : "") + text.slice(start, idx),
    match: text.slice(idx, idx + q.length),
    tail: text.slice(idx + q.length, end) + (end < text.length ? "…" : ""),
  };
}

export default function SearchPanel({ onClose }: Props) {
  const messages = useChatStore((s) => s.messages);
  const [query, setQuery] = useState("");
  const [flashIndex, setFlashIndex] = useState<number | null>(null);

  // Escape 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return messages
      .map((m, i) => ({ index: i, message: m }))
      .filter(({ message }) => message.content.toLowerCase().includes(q));
  }, [messages, query]);

  const jumpTo = (index: number) => {
    const el = messageScrollRef.current;
    if (el) {
      const item = el.querySelector<HTMLElement>(`[data-msg-index="${index}"]`);
      if (item) el.scrollTo({ top: item.offsetTop - 24, behavior: "smooth" });
    }
    setFlashIndex(index);
    setTimeout(() => setFlashIndex(null), 800);
  };

  return (
    <>
      {/* 点击外部关闭 */}
      <div className="fixed inset-0 z-30" onClick={onClose} aria-hidden />
      <div
        className="absolute right-0 top-full z-40 mt-1 w-80 rounded-xl border border-border bg-popover p-2 shadow-lg"
        data-testid="search-panel"
      >
        <SearchInput value={query} onChange={setQuery} placeholder="搜索当前对话内容…" />

      {query.trim() === "" ? (
        <div className="flex items-center justify-center gap-1.5 py-6 text-xs text-muted-foreground">
          <Search className="size-3.5" /> 输入关键词，搜索当前会话已加载的消息
        </div>
      ) : results.length === 0 ? (
        <div className="py-6 text-center text-xs text-muted-foreground">未找到匹配消息</div>
      ) : (
        <div className="mt-2">
          <div className="px-2 pb-1 text-[10px] text-muted-foreground">找到 {results.length} 条</div>
          <div className="max-h-72 space-y-0.5 overflow-y-auto">
            {results.map(({ index, message }) => {
              const s = snippet(message.content, query.trim());
              return (
                <button
                  key={index}
                  type="button"
                  onClick={() => jumpTo(index)}
                  className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent"
                  data-testid={`search-result-${index}`}
                >
                  <span className={cn("mt-0.5 shrink-0", message.role === "user" ? "text-primary" : "text-violet-500")}>
                    {message.role === "user" ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
                  </span>
                  <span className="line-clamp-2 min-w-0 flex-1 break-all text-muted-foreground">
                    {s.head}
                    {s.match && <mark className="rounded bg-warning/30 px-0.5 text-foreground">{s.match}</mark>}
                    {s.tail}
                  </span>
                  <span className="flex shrink-0 items-center gap-0.5 text-[10px] text-muted-foreground/60">
                    <CornerDownRight className="size-2.5" /> {index + 1}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

        {/* 跳转目标闪烁高亮（复用 OverviewRuler 手法） */}
        {flashIndex !== null && (
          <style>{`[data-msg-index="${flashIndex}"] { animation: msg-enter 400ms ease-out 2; }`}</style>
        )}
      </div>
    </>
  );
}
