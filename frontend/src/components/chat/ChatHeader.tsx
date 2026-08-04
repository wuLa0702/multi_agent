/**
 * ChatHeader — 对话顶部标题栏组件（v3 §3.1.3，56px）。
 * 标题（可点击重命名）+ 右侧操作：搜索 / 导出 / Agent（第四栏开关）/ 更多。
 * 按钮顺序固定，间距 8px（v3 §3.5.3）。
 */

import { useState } from "react";
import { Search, Download, MoreHorizontal, Check, X, Bot } from "lucide-react";
import { Input } from "@/components/ui/input";
import PageHeader from "@/components/common/PageHeader";
import { showConfirm } from "@/components/ui/confirm-dialog";

interface Props {
  title: string;
  agentPanelOpen: boolean;
  onRename: (title: string) => void;
  onSearch: () => void;
  onExport: () => void;
  onToggleAgentPanel: () => void;
  onClearChat: () => void;
}

export default function ChatHeader({
  title,
  agentPanelOpen,
  onRename,
  onSearch,
  onExport,
  onToggleAgentPanel,
  onClearChat,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const confirmRename = () => {
    const t = draft.trim();
    setEditing(false);
    if (t) onRename(t);
  };

  return (
    <PageHeader
      title={title}
      onTitleClick={() => {
        setDraft(title);
        setEditing(true);
      }}
      right={
        <>
          <HeaderBtn label="搜索对话内容" onClick={onSearch}>
            <Search className="size-4" />
          </HeaderBtn>
          <HeaderBtn label="导出对话" onClick={onExport}>
            <Download className="size-4" />
          </HeaderBtn>
          {/* Agent 第四栏开关（v3 §3.5.3） */}
          <button
            type="button"
            onClick={onToggleAgentPanel}
            className={`press flex h-8 items-center gap-1 rounded-md px-2 text-xs transition-colors ${
              agentPanelOpen ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted"
            }`}
            aria-label="Agent 详情面板"
          >
            <Bot className="size-4" />
            Agent
          </button>
          <HeaderBtn
            label="更多操作"
            onClick={() =>
              void showConfirm("清空当前对话上下文？", {
                title: "清空对话",
                confirmLabel: "清空",
                variant: "destructive",
              }).then((ok) => ok && onClearChat())
            }
          >
            <MoreHorizontal className="size-4" />
          </HeaderBtn>
        </>
      }
    >
      {/* 标题行内重命名 */}
      {editing && (
        <div className="flex items-center gap-1.5 px-4 pb-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") confirmRename();
              if (e.key === "Escape") setEditing(false);
            }}
            className="h-7 text-xs"
            autoFocus
          />
          <button type="button" onClick={confirmRename} className="text-success" aria-label="确认">
            <Check className="size-4" />
          </button>
          <button type="button" onClick={() => setEditing(false)} className="text-muted-foreground" aria-label="取消">
            <X className="size-4" />
          </button>
        </div>
      )}
    </PageHeader>
  );
}

function HeaderBtn({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="press rounded-md p-1.5 text-muted-foreground hover:bg-muted"
      title={label}
      aria-label={label}
    >
      {children}
    </button>
  );
}

// 导出工具提示（ChatPage 用）
export function exportChatAsMd(title: string, lines: { role: string; content: string }[]): void {
  const blob = new Blob([lines.map((m) => `${m.role}: ${m.content}`).join("\n\n")], {
    type: "text/plain;charset=utf-8",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${title}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}
