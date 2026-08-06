/**
 * 对话页（v3 §3）— 弹性四栏布局：一级导航 / 会话列表 / 主内容区 / Agent 详情面板（可开关）。
 * 主内容区组件化：ChatHeader（标题栏）+ ChatMessages（消息流 + 概览标尺）+ ChatInput（悬浮输入）。
 * Agent 面板替代抽屉：主区挤压不覆盖，可拖动宽度（v3 §3.5）。
 */

import { useEffect, useRef, useState } from "react";
import { MessageSquare, Plus } from "lucide-react";
import { useSessionStore } from "@/lib/stores/sessionStore";
import { useChatStore } from "@/lib/stores/chatStore";
import SessionList from "@/components/history/SessionList";
import ChatHeader, { exportChatAsMd } from "@/components/chat/ChatHeader";
import ChatMessages from "@/components/chat/ChatMessages";
import TodoPanel from "@/components/todo/TodoPanel";
import ChatInput from "@/components/chat/ChatInput";
import AgentPanel from "@/components/agent/AgentPanel";
import PageHeader from "@/components/common/PageHeader";
import { showToast } from "@/components/shared/Toast";
import { showConfirm } from "@/components/ui/confirm-dialog";

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

  const [agentPanelOpen, setAgentPanelOpen] = useState(false);
  const resumePromptShownRef = useRef(false);

  useEffect(() => {
    void loadList().catch(() => undefined);
    void loadProviders();

    // 审批断点恢复（StrictMode 双渲染 guard：只弹一次确认）
    if (resumePromptShownRef.current) return;
    resumePromptShownRef.current = true;
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

  return (
    <div className="flex min-w-0 flex-1">
      {/* 二级栏：会话列表 */}
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-border bg-card">
        <PageHeader
          title="会话"
          icon={<MessageSquare className="size-4" />}
          right={
            <button
              type="button"
              onClick={() => void useChatStore.getState().clearChat()}
              className="press flex h-7 items-center gap-1 rounded-lg bg-primary px-2 text-xs text-primary-foreground hover:bg-primary/90"
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

      {/* 主内容区（组件化：ChatHeader + ChatMessages + ChatInput，v3 §3.1） */}
      <main className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          title={currentTitle}
          agentPanelOpen={agentPanelOpen}
          onRename={async (t) => {
            if (!sessionId) return;
            try {
              await renameSession(sessionId, t);
              showToast("已重命名", "success");
            } catch {
              showToast("重命名失败", "error");
            }
          }}
          onSearch={() => showToast("对话内搜索（后端未实现，mock）", "info")}
          onExport={() => {
            if (messages.length === 0) {
              showToast("暂无内容可导出", "info");
              return;
            }
            exportChatAsMd(currentTitle, messages.map((m) => ({ role: m.role, content: m.content })));
            showToast("已导出对话", "success");
          }}
          onToggleAgentPanel={() => setAgentPanelOpen((v) => !v)}
          onClearChat={() => clearChat()}
        />

        {/* 任务规划模式顶部面板（v5.0 §2.3：todos 非空时固定顶部） */}
        <TodoPanel />
        <ChatMessages />

        {/* 悬浮输入框（v3 §3.2：圆角卡片 + 阴影 + 底部留白 + 宽度对齐消息区） */}
        <div
          className="mx-auto w-full pb-4"
          style={{ maxWidth: "var(--chat-max-width)", paddingLeft: "var(--chat-padding-x)", paddingRight: "var(--chat-padding-x)" }}
        >
          <ChatInput onSend={(content) => void send(content)} onCancel={cancel} />
        </div>
      </main>

      {/* 第四栏：Agent 详情面板（v3 §3.5，可开关可拖动） */}
      <AgentPanel open={agentPanelOpen} onClose={() => setAgentPanelOpen(false)} />

    </div>
  );
}
