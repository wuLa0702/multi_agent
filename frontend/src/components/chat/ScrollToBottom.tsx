/**
 * ScrollToBottom — 动态滚动导航（前端功能规划 §4.1 + 2026-08-20 T5）。
 * - 向下滚动且脱离底部 500px → 显示"回到最新"（ArrowDown）
 * - 向上滚动且脱离顶部 500px → 显示"回到最上"（ArrowUp）
 * - 两者不同时显示（优先底部导航）
 * - 脱离期间新消息计数（未读角标）
 */

import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";

const DETACH_THRESHOLD = 500;

interface Props {
  scrollRef: RefObject<HTMLDivElement | null>;
  totalCount: number;
}

export default function ScrollToBottom({ scrollRef, totalCount }: Props) {
  const [mode, setMode] = useState<"none" | "bottom" | "top">("none");
  const [unread, setUnread] = useState(0);
  const baselineRef = useRef(totalCount);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      const fromBottom = el.scrollHeight - (el.scrollTop + el.clientHeight);
      const fromTop = el.scrollTop;

      if (fromBottom > DETACH_THRESHOLD) {
        setMode("bottom");
      } else if (fromTop > DETACH_THRESHOLD) {
        setMode("top");
      } else {
        setMode("none");
        setUnread(0);
      }
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, [scrollRef]);

  // 内容变化 → 累计未读（仅脱离底部时）
  useEffect(() => {
    if (mode !== "bottom") return;
    const gained = totalCount - baselineRef.current;
    if (gained > 0) setUnread((u) => u + gained);
    baselineRef.current = totalCount;
  }, [totalCount, mode]);

  const scrollTo = (where: "bottom" | "top") => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: where === "bottom" ? el.scrollHeight : 0,
      behavior: "smooth",
    });
    setMode("none");
    setUnread(0);
  };

  if (mode === "none") return null;

  return (
    <button
      type="button"
      onClick={() => scrollTo(mode === "bottom" ? "bottom" : "top")}
      className={cn(
        "absolute right-4 z-20 flex items-center gap-1.5 rounded-full",
        "border border-border bg-card px-4 py-1.5 text-sm text-foreground shadow-md",
        "transition-all duration-200 ease-out hover:bg-accent active:scale-95",
        mode === "bottom" ? "bottom-4" : "top-4",
      )}
      aria-label={mode === "bottom" ? "回到最新消息" : "回到最上部"}
    >
      {mode === "bottom" ? (
        <>
          <ArrowDown className="size-4 text-primary" />
          <span>回到最新</span>
          {unread > 0 && (
            <span className="ml-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
              {unread}
            </span>
          )}
        </>
      ) : (
        <>
          <ArrowUp className="size-4 text-primary" />
          <span>回到最上</span>
        </>
      )}
    </button>
  );
}
