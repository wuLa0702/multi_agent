/**
 * 对话页（v2 §3）— 二级栏（会话列表）+ 主区（顶部栏 + 消息流 900px + ChatInput 两行式）。
 * 顶部栏：会话标题点击重命名 + 右侧搜索/导出/更多（mock）。
 * 空状态：渐变图标 + 「开始新对话」+ 副标题 + 快捷问题胶囊。
 * Agent 直播台：右侧抽屉（AgentStatusDrawer）。
 */

import { useEffect, useState } from "react";
import { Sparkles, Search, Download, MoreHorizontal, Check, X, MessageSquare, Plus } from "lucide-react";
import { useSessionStore } from "@/lib/stores/sessionStore";
import { useChatStore } from "@/lib/stores/chatStore";
import SessionList from "@/components/history/SessionList";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";
import PageHeader from "@/components/common/PageHeader";
import AgentStatusDrawer from "@/components/agent/AgentStatusDrawer";
import ApproveDialog from "@/components/agent/ApproveDialog";
import { Input } from "@/components/ui/input";
import { showToast } from "@/components/shared/Toast";
import { showConfirm } from "@/components/ui/confirm-dialog";

const QUICK_QUESTIONS = [
  "帮我写一个 Python 爬虫",
  "解释一下 LangGraph 工作原理",
  "安装一个搜索 Skill",
];

export default function ChatPage() {
  const loadList = useSessionStore((s) => s.loadList);
  const sessions = useSessionStore((s) => s.sessions);
  const renameSession = useSessionStore((s) => s.rename);
  const resume = useChatStore((s) => s.resume);
  const loadProviders = useChatStore((s) => s.loadProviders);
  const send = useChatStore((s) => s.send);
  const cancel = useChatStore((s) => s.cancel);
  const clearChat = useChatStore((s) => s.clearChat);
  const sessionId = useChatStore((s) => s.sessionId);
  const messages = useChatStore((s) => s.messages);
  const streamStatus = useChatStore((s) => s.streamStatus);

  // 标题行内重命名（v2 §3.6-1）
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  useEffect(() => {
    void loadList().catch(() => undefined);
    void loadProviders();

    // 审批断点恢复
    const runId = useChatStore.getState().pendingRunId;
    if (runId) {
      void showConfirm("检测到上次有一个待审批操作，是否恢复执行？", {
        title: "恢复审批",
        confirmLabel: "恢复",
        cancelLabel: "稍后",
      }).then((ok) => {
        if (ok) void resume(runId);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentTitle = sessions.find((s) => s.id === sessionId)?.title ?? "新对话";
  const isEmpty = messages.length === 0 && streamStatus === "idle";

  const confirmTitle = async () => {
    const title = titleDraft.trim();
    setEditingTitle(false);
    if (!title || !sessionId) return;
    try {
      await renameSession(sessionId, title);
      showToast("已重命名", "success");
    } catch {
      showToast("重命名失败", "error");
    }
  };

  return (
    <div className="flex min-w-0 flex-1">
      {/* 二级栏：会话列表（280px，标题栏 56px） */}
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-border bg-card">
        <PageHeader
          title="会话"
          icon={<MessageSquare className="size-4" />}
          right={
            <button
              type="button"
              onClick={() => void useChatStore.getState().clearChat()}
              className="press flex h-7 items-center gap-1 rounded-lg bg-primary px-2 text-xs text-primary-foreground hover:bg-primary/90"
              title="新建会话（先清空当前，创建由会话列表处理）"
              aria-label="新建会话"
            >
              <Plus className="size-3.5" /> 新建
            </button>
          }
        />
        <div className="min-h-0 flex-1">
          <SessionList />
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* 顶部标题栏 56px（v2 §3.6）：标题可重命名 + 右侧操作（mock） */}
        <PageHeader
          title={currentTitle}
          onTitleClick={() => {
            setTitleDraft(currentTitle);
            setEditingTitle(true);
          }}
          right={
            <>
              <button
                type="button"
                className="press rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                title="搜索对话内容（mock）"
                aria-label="搜索对话内容"
                onClick={() => showToast("对话内搜索（后端未实现，mock）", "info")}
              >
                <Search className="size-4" />
              </button>
              <button
                type="button"
                className="press rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                title="导出对话（mock）"
                aria-label="导出对话"
                onClick={() => {
                  const blob = new Blob([messages.map((m) => `${m.role}: ${m.content}`).join("\n\n")], {
                    type: "text/plain;charset=utf-8",
                  });
                  const a = document.createElement("a");
                  a.href = URL.createObjectURL(blob);
                  a.download = `${currentTitle}.md`;
                  a.click();
                  URL.revokeObjectURL(a.href);
                }}
              >
                <Download className="size-4" />
              </button>
              <button
                type="button"
                className="press rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                title="更多（清空上下文）"
                aria-label="更多操作"
                onClick={() =>
                  void showConfirm("清空当前对话上下文？", {
                    title: "清空对话",
                    confirmLabel: "清空",
                    variant: "destructive",
                  }).then((ok) => ok && clearChat())
                }
              >
                <MoreHorizontal className="size-4" />
              </button>
            </>
          }
        >
          {/* 标题行内重命名 */}
          {editingTitle && (
            <div className="flex items-center gap-1.5 px-4 pb-2">
              <Input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void confirmTitle();
                  if (e.key === "Escape") setEditingTitle(false);
                }}
                className="h-7 text-xs"
                autoFocus
              />
              <button type="button" onClick={() => void confirmTitle()} className="text-success" aria-label="确认">
                <Check className="size-4" />
              </button>
              <button type="button" onClick={() => setEditingTitle(false)} className="text-muted-foreground" aria-label="取消">
                <X className="size-4" />
              </button>
            </div>
          )}
        </PageHeader>

        {/* 消息流：900px 居中（v2 §3.1） */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-[900px] flex-col px-10">
            {isEmpty ? (
              <div className="relative flex flex-1 flex-col items-center justify-center gap-1 py-16">
                {/* 渐变图标（v2 §3.4-2，非 loading 圈） */}
                <div className="breathe mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-violet-500/20 shadow-sm">
                  <Sparkles className="size-8 text-primary" strokeWidth={1.5} />
                </div>
                <h2 className="text-lg font-semibold">开始新对话</h2>
                <p className="mb-6 text-xs text-muted-foreground">
                  基于你的 Agent 能力，回答问题、执行任务、编写代码
                </p>
                {/* 快捷问题胶囊（v2 §3.4-3） */}
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {QUICK_QUESTIONS.map((q, i) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => void send(q)}
                      className="btn-lift press msg-enter msg-enter-d rounded-full border border-border bg-muted/60 px-4 py-2 text-xs text-foreground/80 hover:border-primary/40 hover:bg-accent/50"
                      style={{ animationDelay: `${i * 60}ms` }}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <MessageList />
            )}
          </div>
        </div>

        {/* 两行式输入（v2 §3.2） */}
        <ChatInput onSend={(content) => void send(content)} onCancel={cancel} />
      </main>

      <AgentStatusDrawer />
      <ApproveDialog />
    </div>
  );
}
