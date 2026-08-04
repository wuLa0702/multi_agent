/**
 * 会话侧栏（二级栏）— 今天/昨天/更早 分组 + 新建/改名/删除。
 * 方案 §4.1.3：顶部搜索框 + 新建按钮；列表项 hover 上浮、选中态主题色竖条。
 * 数据源：sessionStore（列表）+ chatStore（当前会话高亮）。
 */

import { useMemo, useState } from "react";
import { MessageSquare, Plus, Pencil, Trash2, Check, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSessionStore } from "@/lib/stores/sessionStore";
import { useChatStore } from "@/lib/stores/chatStore";
import { showConfirm } from "@/components/ui/confirm-dialog";
import { showToast } from "@/components/shared/Toast";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import type { Session } from "@/lib/api/types";

/** 会话分组：今天 / 昨天 / 7 天内 / 更早（v2 §3.5-3，按 updated_at 本地时区） */
function groupLabel(updatedAt: string): string {
  const d = new Date(updatedAt);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dayMs = 24 * 3600 * 1000;
  const t = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  if (t === startOfToday) return "今天";
  if (t === startOfToday - dayMs) return "昨天";
  if (t >= startOfToday - 6 * dayMs) return "7 天内";
  return "更早";
}

const GROUP_ORDER = ["今天", "昨天", "7 天内", "更早"] as const;

function groupSessions(sessions: Session[]): Record<string, Session[]> {
  const groups: Record<string, Session[]> = { 今天: [], 昨天: [], "7 天内": [], 更早: [] };
  for (const s of sessions) {
    const label = groupLabel(s.updated_at);
    groups[label]?.push(s) ?? (groups[label] = [s]);
  }
  return groups;
}

/** 会话时间显示（v2 §3.5-4）：今天 HH:mm / 昨天 / 7 天内 MM-DD / 更早 YYYY-MM-DD */
function formatSessionTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const label = groupLabel(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (label === "今天") return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (label === "昨天") return "昨天";
  if (label === "7 天内") return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function SessionList() {
  const sessions = useSessionStore((s) => s.sessions);
  const loadList = useSessionStore((s) => s.loadList);
  const createSession = useSessionStore((s) => s.createSession);
  const rename = useSessionStore((s) => s.rename);
  const remove = useSessionStore((s) => s.remove);

  const sessionId = useChatStore((s) => s.sessionId);
  const loadHistory = useChatStore((s) => s.loadHistory);
  const clearChat = useChatStore((s) => s.clearChat);
  const streamStatus = useChatStore((s) => s.streamStatus);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const handleNew = async () => {
    try {
      const session = await createSession();
      clearChat();
      useChatStore.setState({ sessionId: session.id });
      showToast("已创建新会话", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "创建失败", "error");
    }
  };

  const handleSelect = (id: string) => {
    if (streamStatus === "connecting" || streamStatus === "streaming") {
      showToast("生成中，请先停止", "info");
      return;
    }
    void loadHistory(id).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : "加载失败", "error");
    });
  };

  const handleRename = async (id: string) => {
    const title = draftTitle.trim();
    setEditingId(null);
    if (!title) return;
    try {
      await rename(id, title);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "改名失败", "error");
    }
  };

  const handleDelete = async (id: string) => {
    const ok = await showConfirm(`确定删除该会话？其全部消息将一并删除。`, {
      title: "删除会话",
      confirmLabel: "删除",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await remove(id);
      if (useChatStore.getState().sessionId === id) clearChat();
      showToast("已删除", "success");
    } catch (err) {
      if (err instanceof ApiError && err.code === "SESSION_NOT_FOUND") {
        showToast("会话已不存在", "info");
        void loadList();
        return;
      }
      showToast(err instanceof Error ? err.message : "删除失败", "error");
    }
  };

  // 搜索过滤（方案 §4.1.3 顶部搜索框）
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => (query ? sessions.filter((s) => s.title.toLowerCase().includes(query.toLowerCase())) : sessions),
    [sessions, query],
  );
  const groups = useMemo(() => groupSessions(filtered), [filtered]);

  return (
    <div className="flex h-full flex-col">
      {/* 顶部：搜索框 + 新建按钮（方案 §4.1.3） */}
      <div className="space-y-2 border-b border-border p-3">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索会话…"
              className="h-8 pl-7 text-xs"
            />
          </div>
          <button
            type="button"
            onClick={() => void handleNew()}
            className="btn-lift press flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground hover:bg-primary/90"
            title="新建会话"
            aria-label="新建会话"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>

      {/* 列表：今天/昨天/更早 分组，独立滚动 */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {filtered.length === 0 && (
          <div className="mt-8 text-center text-xs text-muted-foreground">
            {query ? "无匹配会话" : "暂无会话，点击 + 新建"}
          </div>
        )}
        {GROUP_ORDER.map((label) => {
          const items = groups[label] ?? [];
          if (items.length === 0) return null;
          return (
            <div key={label} className="mb-3">
              <div className="sidebar-group-title">{label}</div>
              <div className="space-y-0.5">
                {items.map((s) => (
                  <SessionRow
                    key={s.id}
                    session={s}
                    active={s.id === sessionId}
                    editing={editingId === s.id}
                    draftTitle={draftTitle}
                    onDraftChange={setDraftTitle}
                    onSelect={() => handleSelect(s.id)}
                    onStartEdit={() => {
                      setEditingId(s.id);
                      setDraftTitle(s.title);
                    }}
                    onCancelEdit={() => setEditingId(null)}
                    onConfirmEdit={() => handleRename(s.id)}
                    onDelete={() => handleDelete(s.id)}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 单个会话行（两行式：标题 + 时间/hover 操作，v2 §3.5-4） */
function SessionRow({
  session: s,
  active,
  editing,
  draftTitle,
  onDraftChange,
  onSelect,
  onStartEdit,
  onCancelEdit,
  onConfirmEdit,
  onDelete,
}: {
  session: Session;
  active: boolean;
  editing: boolean;
  draftTitle: string;
  onDraftChange: (v: string) => void;
  onSelect: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onConfirmEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={cn(
        "nav-item group relative flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5",
        active ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
      )}
      onClick={onSelect}
    >
      {active && <span className="absolute left-0 top-1 bottom-1 w-0.5 rounded-full bg-primary" />}
      <MessageSquare className={cn("mt-0.5 size-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
      {editing ? (
        <>
          <Input
            value={draftTitle}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onConfirmEdit();
              if (e.key === "Escape") onCancelEdit();
            }}
            onClick={(e) => e.stopPropagation()}
            className="h-6 text-xs"
            autoFocus
          />
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onConfirmEdit();
            }}
            className="text-success"
            aria-label="确认改名"
          >
            <Check className="size-3.5" />
          </button>
        </>
      ) : (
        <div className="min-w-0 flex-1">
          {/* 第一行：标题（截断） */}
          <div className="truncate text-sm">{s.title}</div>
          {/* 第二行：时间（右）+ hover 操作 */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground/70">{formatSessionTime(s.updated_at)}</span>
            <span className="hidden items-center gap-0.5 group-hover:flex">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onStartEdit();
                }}
                className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                aria-label="改名"
              >
                <Pencil className="size-3" />
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
                className="rounded p-0.5 text-muted-foreground hover:text-destructive"
                aria-label="删除"
              >
                <Trash2 className="size-3" />
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
