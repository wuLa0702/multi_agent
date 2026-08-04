/**
 * OverviewRuler — 右侧概览标尺（v3 §3.4，24px 宽）。
 * 标记点：用户消息每 5 条（靛蓝）/ tool 消息（绿）/ 代码块（橙，content 含 ```）/ 错误（红）。
 * 交互：hover tooltip（前 30 字 + 时间，200ms 延迟）、点击平滑滚动 300ms + 目标高亮、
 * 滚动时当前位置实时更新（放大圆点）。
 * 显示规则：消息 < 10 条自动隐藏（由 ChatMessages 控制）。
 */

import { useMemo, useState, useEffect, useCallback } from "react";
import type { RefObject } from "react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";

interface Props {
  scrollRef: RefObject<HTMLDivElement | null>;
}

interface Marker {
  index: number;
  type: "user" | "tool" | "code" | "error";
  preview: string;
}

const MARKER_COLOR: Record<Marker["type"], string> = {
  user: "bg-primary",
  tool: "bg-success",
  code: "bg-warning",
  error: "bg-destructive",
};

export default function OverviewRuler({ scrollRef }: Props) {
  const messages = useChatStore((s) => s.messages);
  const [activeIndex, setActiveIndex] = useState(0);
  const [hovered, setHovered] = useState<Marker | null>(null);
  const [hoverTimer, setHoverTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  const [flashIndex, setFlashIndex] = useState<number | null>(null);

  // 标记点计算（v3 §3.4.3）：用户每 5 条 / tool / 代码块 / 错误
  const markers = useMemo<Marker[]>(() => {
    const result: Marker[] = [];
    let userCount = 0;
    messages.forEach((m, i) => {
      if (m.role === "user") {
        userCount += 1;
        if (userCount % 5 === 0) {
          result.push({ index: i, type: "user", preview: m.content.slice(0, 30) });
        }
      } else if (m.role === "tool") {
        result.push({ index: i, type: "tool", preview: m.content.slice(0, 30) });
      } else if (m.role === "assistant") {
        if (m.content.includes("```")) {
          result.push({ index: i, type: "code", preview: m.content.slice(0, 30) });
        }
        if (m.content.includes("Error") || m.content.includes("错误") || m.content.includes("失败")) {
          result.push({ index: i, type: "error", preview: m.content.slice(0, 30) });
        }
      }
    });
    return result;
  }, [messages]);

  // 滚动时更新当前位置（视口中心对应消息）
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const center = el.scrollTop + el.clientHeight / 2;
    const items = el.querySelectorAll<HTMLElement>("[data-msg-index]");
    let current = 0;
    items.forEach((item) => {
      const idx = Number(item.dataset.msgIndex ?? 0);
      if (item.offsetTop <= center) current = idx;
    });
    setActiveIndex(current);
  }, [scrollRef]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [scrollRef, onScroll]);

  // 点击跳转：平滑滚动 300ms + 目标高亮闪烁
  const jumpTo = (marker: Marker) => {
    const el = scrollRef.current;
    if (!el) return;
    const item = el.querySelector<HTMLElement>(`[data-msg-index="${marker.index}"]`);
    if (!item) return;
    el.scrollTo({ top: item.offsetTop - 24, behavior: "smooth" });
    setFlashIndex(marker.index);
    setTimeout(() => setFlashIndex(null), 800);
  };

  const showTooltip = (marker: Marker) => {
    if (hoverTimer) clearTimeout(hoverTimer);
    setHoverTimer(setTimeout(() => setHovered(marker), 200));
  };
  const hideTooltip = () => {
    if (hoverTimer) clearTimeout(hoverTimer);
    setHovered(null);
  };

  return (
    <div className="relative ml-2 w-6 shrink-0 select-none" onMouseLeave={hideTooltip}>
      {/* 标尺轨道 */}
      <div className="absolute inset-y-2 left-1/2 w-px -translate-x-1/2 bg-border/60" />

      {/* 标记点 */}
      {markers.map((marker) => {
        const pct = (marker.index / Math.max(1, messages.length - 1)) * 100;
        const isActive = Math.abs(marker.index - activeIndex) <= 2;
        return (
          <button
            key={`${marker.type}-${marker.index}`}
            type="button"
            onClick={() => jumpTo(marker)}
            onMouseEnter={() => showTooltip(marker)}
            className="absolute left-1/2 -translate-x-1/2 -translate-y-1/2"
            style={{ top: `${pct}%` }}
            aria-label={`跳转到消息 ${marker.index + 1}`}
          >
            <span
              className={cn(
                "block rounded-full transition-all duration-150",
                MARKER_COLOR[marker.type],
                isActive ? "h-3 w-3 scale-110 ring-2 ring-primary/30" : "h-1.5 w-1.5 hover:scale-125",
              )}
              style={isActive ? { animation: "pop-in 250ms ease-out both" } : undefined}
            />
          </button>
        );
      })}

      {/* tooltip（v3 §3.4.3：前 30 字 + 时间，200ms 延迟 150ms 淡入） */}
      {hovered && (
        <div className="pointer-events-none absolute right-6 top-0 z-30 w-48 rounded-lg border border-border bg-popover p-2 text-[10px] shadow-lg transition-opacity duration-150">
          <div className="line-clamp-2 text-muted-foreground">{hovered.preview}…</div>
          <div className="mt-0.5 text-muted-foreground/60">
            消息 {hovered.index + 1} · {new Date(messages[hovered.index].created_at).toLocaleTimeString()}
          </div>
        </div>
      )}

      {/* 目标高亮闪烁 */}
      {flashIndex !== null && (
        <style>{`
          [data-msg-index="${flashIndex}"] { animation: msg-enter 400ms ease-out 2; }
        `}</style>
      )}
    </div>
  );
}
