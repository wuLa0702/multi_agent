/**
 * Toast — 右下角全局提示（v3 §7.1 重构 + 2026-08-20 T1 修复）。
 * 单例容器 + 多 toast 纵向堆叠（最新在底部，间距 12px，距边 24px）。
 * 四类型（success/warning/error/info）+ 毛玻璃卡片 + 滑入 250ms / 滑出 200ms。
 *
 * 修复（T1，2026-08-20）：
 * - 分级时长：success 1.5s / info 3s / warning 4s / error 5s（co-creator 定案）
 * - 定时器 bug：hover 暂停/恢复用剩余时间管理，避免 timer 泄漏/不消失
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastType = "success" | "warning" | "error" | "info";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
  leaving: boolean;
}

/** 分级时长（co-creator 定案，2026-08-20） */
const DURATION: Record<ToastType, number> = {
  success: 1500,
  info: 3000,
  warning: 4000,
  error: 5000,
};

// ── 单例容器状态（模块级）──
let containerEl: HTMLDivElement | null = null;
let containerRoot: ReturnType<typeof createRoot> | null = null;
let nextId = 1;

function ensureContainer(): void {
  if (containerEl && containerRoot) return;
  containerEl = document.createElement("div");
  document.body.appendChild(containerEl);
  containerRoot = createRoot(containerEl);
  containerRoot.render(<ToastContainer />);
}

export function showToast(message: string, type: ToastType = "info"): void {
  ensureContainer();
  const id = nextId++;
  const item: ToastItem = { id, message, type, leaving: false };
  window.dispatchEvent(new CustomEvent("toast-push", { detail: item }));
}

// ── 容器组件 ──

interface TimerEntry {
  timer: ReturnType<typeof setTimeout>;
  remaining: number;
  startedAt: number;
}

function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timersRef = useRef(new Map<number, TimerEntry>());

  const removeItem = useCallback(
    (id: number) => {
      // 滑出动画（200ms）再移除
      setItems((prev) => prev.map((i) => (i.id === id ? { ...i, leaving: true } : i)));
      setTimeout(() => {
        setItems((prev) => prev.filter((i) => i.id !== id));
      }, 200);
      const entry = timersRef.current.get(id);
      if (entry) clearTimeout(entry.timer);
      timersRef.current.delete(id);
    },
    [],
  );

  const startTimer = useCallback(
    (id: number, duration: number) => {
      const entry = timersRef.current.get(id);
      if (entry) clearTimeout(entry.timer);
      const timer = setTimeout(() => removeItem(id), duration);
      timersRef.current.set(id, { timer, remaining: duration, startedAt: Date.now() });
    },
    [removeItem],
  );

  const pauseTimer = useCallback((id: number) => {
    const entry = timersRef.current.get(id);
    if (!entry) return;
    clearTimeout(entry.timer);
    const elapsed = Date.now() - entry.startedAt;
    entry.remaining = Math.max(0, entry.remaining - elapsed);
  }, []);

  const resumeTimer = useCallback(
    (id: number) => {
      const entry = timersRef.current.get(id);
      if (!entry) return;
      startTimer(id, entry.remaining);
    },
    [startTimer],
  );

  useEffect(() => {
    const onPush = (e: Event) => {
      const item = (e as CustomEvent).detail as ToastItem;
      setItems((prev) => [...prev, item]);
      const duration = DURATION[item.type] ?? 3000;
      startTimer(item.id, duration);
    };
    window.addEventListener("toast-push", onPush);
    return () => {
      window.removeEventListener("toast-push", onPush);
      timersRef.current.forEach(({ timer }) => clearTimeout(timer));
      timersRef.current.clear();
    };
  }, [startTimer]);

  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-[60] flex flex-col items-end gap-3">
      {items.map((item) => (
        <ToastCard
          key={item.id}
          item={item}
          onClose={() => removeItem(item.id)}
          onHoverPause={() => pauseTimer(item.id)}
          onHoverResume={() => resumeTimer(item.id)}
        />
      ))}
    </div>
  );
}

const TYPE_STYLE: Record<ToastType, { icon: typeof Info; color: string }> = {
  success: { icon: CheckCircle2, color: "text-success" },
  warning: { icon: AlertTriangle, color: "text-warning" },
  error: { icon: XCircle, color: "text-destructive" },
  info: { icon: Info, color: "text-primary" },
};

function ToastCard({
  item,
  onClose,
  onHoverPause,
  onHoverResume,
}: {
  item: ToastItem;
  onClose: () => void;
  onHoverPause: () => void;
  onHoverResume: () => void;
}) {
  const { icon: Icon, color } = TYPE_STYLE[item.type] ?? TYPE_STYLE.info;

  return (
    <div
      onMouseEnter={onHoverPause}
      onMouseLeave={onHoverResume}
      className={cn(
        "pointer-events-auto flex w-72 max-w-[360px] min-w-[200px] items-start gap-2.5 rounded-xl border border-border bg-card/90 p-3 shadow-lg backdrop-blur-md transition-all duration-200 ease-out",
        item.leaving ? "translate-x-4 opacity-0" : "translate-x-0 opacity-100",
      )}
      role="status"
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", color)} />
      <span className="flex-1 break-words text-xs leading-relaxed">{item.message}</span>
      <button
        type="button"
        onClick={onClose}
        className="shrink-0 rounded p-0.5 text-muted-foreground/60 hover:text-foreground"
        aria-label="关闭提示"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
