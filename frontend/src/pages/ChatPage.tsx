/**
 * 主聊天页 — 三区布局（会话/技能侧栏 + 对话流 + Agent 直播台）。
 * 左侧栏双 Tab：Sessions（历史会话）/ Skills（Skill 市场，见 components/skills）。
 * 编排：挂载加载会话列表 + 审批断点恢复提示（设计 §7.4）。
 */

import { useEffect, useState } from "react";
import { useSessionStore } from "@/lib/stores/sessionStore";
import { useChatStore } from "@/lib/stores/chatStore";
import SessionList from "@/components/history/SessionList";
import SkillMarketPanel from "@/components/skills/SkillMarketPanel";
import MessageList from "@/components/chat/MessageList";
import InputBar from "@/components/chat/InputBar";
import ToolCallPanel from "@/components/agent/ToolCallPanel";
import AgentTree from "@/components/agent/AgentTree";
import ApproveDialog from "@/components/agent/ApproveDialog";
import { showConfirm } from "@/components/ui/confirm-dialog";

export default function ChatPage() {
  const loadList = useSessionStore((s) => s.loadList);
  const resume = useChatStore((s) => s.resume);
  const loadProviders = useChatStore((s) => s.loadProviders);
  const [leftTab, setLeftTab] = useState<"sessions" | "skills">("sessions");

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

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 左：会话 / 技能 侧栏（双 Tab） */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950">
        <div className="flex shrink-0 border-b border-neutral-200 dark:border-neutral-800">
          {(["sessions", "skills"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setLeftTab(tab)}
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                leftTab === tab
                  ? "text-neutral-900 dark:text-neutral-100 border-b-2 border-primary"
                  : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
              }`}
            >
              {tab === "sessions" ? "会话" : "Skills"}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          {leftTab === "sessions" ? <SessionList /> : <SkillMarketPanel />}
        </div>
      </aside>

      {/* 中：对话流 */}
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-hidden">
          <MessageList />
        </div>
        <InputBar />
      </main>

      {/* 右：Agent 直播台（工具调用 + 调用链） */}
      <aside className="flex w-72 shrink-0 flex-col border-l border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950">
        <div className="h-1/2 border-b border-neutral-200 dark:border-neutral-800 overflow-hidden">
          <ToolCallPanel />
        </div>
        <div className="h-1/2 overflow-hidden">
          <AgentTree />
        </div>
      </aside>

      <ApproveDialog />
    </div>
  );
}
