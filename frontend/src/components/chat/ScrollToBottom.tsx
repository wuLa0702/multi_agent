/**
 * ScrollToBottom — 一键回到最新按钮（前端功能规划 §4.1 补充功能 1）。
 * 触发：滚动容器脱离底部 500px 时显示（scrollHeight - (scrollTop + clientHeight) > 500）。
 * 行为：脱离期间新消息计数（未读角标）；点击平滑滚动回底并清零。
 * 交互：显示滑入 200ms / 隐藏滑出 150ms / 点击 scale 按压 / 平滑滚动 300ms（v4.0 §2.2.5）。
 */

import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";

/** 脱离底部阈值（px）：v4.0 §2.2.2 */
const DETACH_THRESHOLD = 500;

interface Props {
  scrollRef: RefObject<HTMLDivElement | null>;
  /** 消息总数（用于未读计数：脱离期间新增消息数） */
  totalCount: number;
}

export default function ScrollToBottom({ scrollRef, totalCount }: Props) {
  const [visible, setVisible] = useState(false);
  const [unread, setUnread] = useState(0);
  const baselineRef = useRef(totalCount);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const isDetached = () =>
      el.scrollHeight - (el.scrollTop + el.clientHeight) > DETACH_THRESHOLD;

    const onScroll = () => {
      const detached = isDetached();
      setVisible(detached);
      if (detached) {
        // 进入脱离态：记录当前消息数作为未读基线
        baselineRef.current = totalCount;
        setUnread(0);
      } else {
        setUnread(0);
      }
    };

    // 内容变化（消息增长）→ 若仍脱离底部则累计未读
    const onContentChange = () => {
      if (isDetached()) {
        const gained = totalCount - baselineRef.current;
        if (gained > 0) setUnread((u) => u + gained);
        baselineRef.current = totalCount;
      }
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll(); // 初始化
    return () => el.removeEventListener("scroll", onScroll);
  }, [scrollRef, totalCount]);

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setVisible(false);
    setUnread(0);
  };

  if (!visible) return null;

  return (
    <button
      type="button"
      onClick={scrollToBottom}
      className={cn(
        "absolute bottom-4 right-4 z-20 flex items-center gap-1.5 rounded-full",
        "border border-border bg-card px-4 py-1.5 text-sm text-foreground shadow-md",
        "transition-all duration-200 ease-out hover:bg-accent active:scale-95"
      )}
      aria-label="回到最新消息"
    >
      <ArrowDown className="size-4 text-primary" />
      <span>回到最新</span>
      {unread > 0 && (
        <span className="ml-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
          {unread}
        </span>
      )}
    </button>
  );
}
