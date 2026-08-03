/**
 * 会话侧栏 — 列表 / 新建 / 改名 / 删除。
 * 数据源：sessionStore（列表）+ chatStore（当前会话高亮）。
 */

import { useState } from "react";
import { MessageSquare, Plus, Pencil, Trash2, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSessionStore } from "@/lib/stores/sessionStore";
import { useChatStore } from "@/lib/stores/chatStore";
import { showConfirm } from "@/components/ui/confirm-dialog";
import { showToast } from "@/components/shared/Toast";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";

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

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-2.5">
        <span className="text-xs font-semibold text-neutral-500">会话</span>
        <button
          type="button"
          onClick={() => void handleNew()}
          className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800"
          title="新建会话"
          aria-label="新建会话"
        >
          <Plus className="size-4" />
        </button>
      </div>

      <div className="flex-1 space-y-1 overflow-y-auto px-2 pb-2">
        {sessions.length === 0 && (
          <div className="mt-8 text-center text-xs text-neutral-400">暂无会话</div>
        )}
        {sessions.map((s) => {
          const active = s.id === sessionId;
          return (
            <div
              key={s.id}
              className={cn(
                "group flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm cursor-pointer",
                active
                  ? "bg-neutral-200/70 dark:bg-neutral-800"
                  : "hover:bg-neutral-100 dark:hover:bg-neutral-900",
              )}
              onClick={() => handleSelect(s.id)}
            >
              <MessageSquare className="size-3.5 shrink-0 text-neutral-400" />
              {editingId === s.id ? (
                <>
                  <Input
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void handleRename(s.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="h-6 text-xs"
                    autoFocus
                  />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleRename(s.id);
                    }}
                    className="text-green-600"
                    aria-label="确认改名"
                  >
                    <Check className="size-3.5" />
                  </button>
                </>
              ) : (
                <>
                  <span className="flex-1 truncate">{s.title}</span>
                  <span className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(s.id);
                        setDraftTitle(s.title);
                      }}
                      className="rounded p-0.5 text-neutral-400 hover:text-neutral-600"
                      aria-label="改名"
                    >
                      <Pencil className="size-3" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(s.id);
                      }}
                      className="rounded p-0.5 text-neutral-400 hover:text-red-500"
                      aria-label="删除"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </span>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
