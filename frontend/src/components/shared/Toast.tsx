/**
 * Toast — 右下角全局提示（v3 §7.1 重构）。
 * 单例容器 + 多 toast 纵向堆叠（最新在底部，间距 12px，距边 24px）。
 * 四类型（success/warning/error/info）+ 毛玻璃卡片 + 滑入 250ms / 滑出 200ms。
 * 默认 3s 自动消失，hover 暂停计时，点击关闭立即消失。
 */

import { useEffect, useRef, useState } from "react";
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
  // 通过自定义事件通知容器
  window.dispatchEvent(new CustomEvent("toast-push", { detail: item }));
}

// ── 容器组件 ──

function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const itemsRef = useRef<ToastItem[]>([]);
  itemsRef.current = items;

  useEffect(() => {
    const onPush = (e: Event) => {
      const item = (e as CustomEvent).detail as ToastItem;
      setItems((prev) => [...prev, item]);
      // 3s 自动消失；hover 暂停由 ToastCard 内管理计时
      const timer = setTimeout(() => removeItem(item.id), 3000);
      pendingTimers.current.set(item.id, timer);
    };
    window.addEventListener("toast-push", onPush);
    return () => window.removeEventListener("toast-push", onPush);
  }, []);

  const pendingTimers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const removeItem = (id: number) => {
    // 先滑出动画（200ms）再移除
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, leaving: true } : i)));
    const timer = setTimeout(() => {
      setItems((prev) => prev.filter((i) => i.id !== id));
    }, 200);
    pendingTimers.current.delete(id);
    void timer;
  };

  const pauseTimer = (id: number) => {
    const t = pendingTimers.current.get(id);
    if (t) clearTimeout(t);
  };
  const resumeTimer = (id: number) => {
    if (pendingTimers.current.has(id)) return;
    pendingTimers.current.set(id, setTimeout(() => removeItem(id), 3000));
  };

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
        item.leaving
          ? "translate-x-4 opacity-0"
          : "translate-x-0 opacity-100",
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
