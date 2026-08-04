/**
 * 对话页（方案 §5.1）— 二级栏（会话列表）+ 主区（消息流居中 768px + 输入控制区）。
 * 空状态：图标 + 欢迎语 + 3 个快捷问题（点击直接发送）。
 * Agent 直播台改为右侧抽屉（AgentStatusDrawer），默认收起。
 */

import { useEffect } from "react";
import { Sparkles } from "lucide-react";
import { useSessionStore } from "@/lib/stores/sessionStore";
import { useChatStore } from "@/lib/stores/chatStore";
import SessionList from "@/components/history/SessionList";
import MessageList from "@/components/chat/MessageList";
import InputBar from "@/components/chat/InputBar";
import AgentStatusDrawer from "@/components/agent/AgentStatusDrawer";
import ApproveDialog from "@/components/agent/ApproveDialog";
import EmptyState from "@/components/shared/EmptyState";
import { showConfirm } from "@/components/ui/confirm-dialog";

const QUICK_QUESTIONS = [
  "帮我调研一下 MCP 协议的最新进展",
  "写一个 Python 脚本统计当前目录文件数量",
  "总结一下多 Agent 系统的架构设计要点",
];

export default function ChatPage() {
  const loadList = useSessionStore((s) => s.loadList);
  const sessions = useSessionStore((s) => s.sessions);
  const resume = useChatStore((s) => s.resume);
  const loadProviders = useChatStore((s) => s.loadProviders);
  const send = useChatStore((s) => s.send);
  const sessionId = useChatStore((s) => s.sessionId);
  const messages = useChatStore((s) => s.messages);
  const streamStatus = useChatStore((s) => s.streamStatus);

  useEffect(() => {
    void loadList().catch(() => undefined);
    void loadProviders();

    // 审批断点恢复（刷新后 localStorage 里残留 run_id）
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

  return (
    <div className="flex min-w-0 flex-1">
      {/* 二级栏：会话列表（280px，独立滚动） */}
      <aside className="w-[280px] shrink-0 border-r border-border bg-card">
        <SessionList />
      </aside>

      {/* 主内容区：标题 + 消息流（居中 768px）+ 输入控制区 */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center justify-center border-b border-border bg-card/60 px-4 backdrop-blur-sm">
          <h1 className="truncate text-sm font-medium text-foreground">{currentTitle}</h1>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-[768px] flex-col px-4">
            {isEmpty ? (
              <div className="relative flex flex-1 items-center justify-center">
                <EmptyState
                  icon={Sparkles}
                  title="多 Agent 工作台"
                  desc="选择下方问题开始，或直接输入你的需求"
                />
                {/* 快捷问题（方案 §5.1.2-6） */}
                <div className="absolute bottom-20 left-1/2 flex w-full max-w-[640px] -translate-x-1/2 flex-col gap-2 px-4">
                  {QUICK_QUESTIONS.map((q, i) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => void send(q)}
                      className="btn-lift press msg-enter msg-enter-d rounded-lg border border-border bg-card px-4 py-2.5 text-left text-xs text-foreground/80 hover:border-primary/40 hover:bg-accent/40"
                      style={{ animationDelay: `${i * 50}ms` }}
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

        <InputBar />
      </main>

      <AgentStatusDrawer />
      <ApproveDialog />
    </div>
  );
}
