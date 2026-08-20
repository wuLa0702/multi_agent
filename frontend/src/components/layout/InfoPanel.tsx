/**
 * 右侧信息栏（P1a 交互优化，2026-08-12）— 收纳任务进度/成本告警，可伸缩/折叠。
 * - 宽 280px ↔ 折叠窄条 40px（localStorage 记忆）
 * - 区块各自可折叠（localStorage 记忆）
 * 主界面清爽：顶部只留 ChatHeader + 消息 + 输入，过程信息收此栏。
 */
import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ClipboardList } from "lucide-react";
import { useChatStore } from "@/lib/stores/chatStore";
import TodoPanel from "@/components/todo/TodoPanel";
import { CostPanel } from "@/components/chat/CostPanel";

const WIDE_KEY = "multi-agent.infoPanel.open";
const SECTION_KEY = "multi-agent.infoPanel.sections";

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** T7：任务进度区块（有任务显示 TodoPanel，无任务友好提示） */
function TaskSection() {
  const todos = useChatStore((s) => s.todos);
  if (todos.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 py-4 text-xs text-muted-foreground">
        <ClipboardList className="size-5 opacity-40" />
        <span>该项目暂无任务</span>
        <span className="text-[10px] opacity-60">历史任务已完成</span>
      </div>
    );
  }
  return <TodoPanel />;
}

export default function InfoPanel({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState<boolean>(() => load(WIDE_KEY, true));
  const [sections, setSections] = useState<Record<string, boolean>>(() => load(SECTION_KEY, {}));

  const isOpen = (k: string) => sections[k] ?? true;
  const toggleSection = (k: string) => {
    const next = { ...sections, [k]: !isOpen(k) };
    setSections(next);
    localStorage.setItem(SECTION_KEY, JSON.stringify(next));
  };
  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    localStorage.setItem(WIDE_KEY, String(next));
  };

  const Section = ({ k, title, children }: { k: string; title: string; children: React.ReactNode }) => (
    <div className="border-b border-border">
      <button
        type="button"
        onClick={() => toggleSection(k)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-accent/50"
      >
        <ChevronDown className={`size-3.5 transition-transform ${isOpen(k) ? "" : "-rotate-90"}`} />
        {title}
      </button>
      {isOpen(k) && <div className="px-3 pb-3">{children}</div>}
    </div>
  );

  // 折叠态：窄条（40px）
  if (!open) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-l border-border bg-card py-2" data-testid="info-panel">
        <button
          type="button"
          onClick={toggleOpen}
          className="press rounded-lg p-1.5 hover:bg-accent"
          aria-label="展开信息栏"
          title="展开信息栏"
        >
          <ChevronLeft className="size-4" />
        </button>
      </aside>
    );
  }

  return (
    <aside className="flex w-[280px] shrink-0 flex-col border-l border-border bg-card" data-testid="info-panel">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-semibold">运行信息</span>
        <button
          type="button"
          onClick={toggleOpen}
          className="press rounded-lg p-1 hover:bg-accent"
          aria-label="收起信息栏"
          title="收起信息栏"
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Section k="task" title="任务进度">
          <TaskSection />
        </Section>
        <Section k="cost" title="成本 / 告警">
          <CostPanel sessionId={sessionId} />
        </Section>
      </div>
    </aside>
  );
}
