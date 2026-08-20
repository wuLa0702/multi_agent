/**
 * ChatHeader — 对话顶部标题栏组件（v3 §3.1.3，56px）。
 * 标题（可点击重命名）+ 右侧操作：搜索（本地 SearchPanel）/ 导出 / Agent（第四栏开关）/ 更多。
 *
 * v6 评审：
 * - P0-3 修 #4：删除按钮 tooltip 由"更多操作"改"删除会话"
 * - P1-5 修 #2：搜索接入前端本地 SearchPanel（替代 mock toast）
 * - P2-7 按钮统一 28px（h-7）、间距 8px
 */

import { useState } from "react";
import { Search, Download, Trash2, Check, X, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import PageHeader from "@/components/common/PageHeader";
import ModeSwitcher from "@/components/common/ModeSwitcher";
import { showConfirm } from "@/components/ui/confirm-dialog";
import SearchPanel from "./SearchPanel";

interface Props {
  title: string;
  agentPanelOpen: boolean;
  onRename: (title: string) => void;
  onExport: () => void;
  onToggleAgentPanel: () => void;
  onClearChat: () => void;
}

export default function ChatHeader({
  title,
  agentPanelOpen,
  onRename,
  onExport,
  onToggleAgentPanel,
  onClearChat,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);

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
          {/* 视图模式切换（v5.0 §3.3：手动入口，优先级最高） */}
          <ModeSwitcher />
          {/* 搜索：本地 SearchPanel（P1-5，替代 mock） */}
          <div className="relative">
            <HeaderBtn
              label="搜索对话内容"
              active={searchOpen}
              onClick={() => setSearchOpen((v) => !v)}
            >
              <Search className="size-4" />
            </HeaderBtn>
            {searchOpen && <SearchPanel onClose={() => setSearchOpen(false)} />}
          </div>
          <HeaderBtn label="导出对话" onClick={onExport}>
            <Download className="size-4" />
          </HeaderBtn>
          {/* Agent 第四栏开关（v3 §3.5.3） */}
          <button
            type="button"
            onClick={onToggleAgentPanel}
            className={`press flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors ${
              agentPanelOpen ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted"
            }`}
            aria-label="Agent 详情面板"
          >
            <Bot className="size-4" />
            Agent
          </button>
          <HeaderBtn
            label="删除会话"
            onClick={() =>
              void showConfirm("清空当前对话上下文？", {
                title: "清空对话",
                confirmLabel: "清空",
                variant: "destructive",
              }).then((ok) => ok && onClearChat())
            }
          >
            <Trash2 className="size-4" />
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
  active = false,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "press flex h-7 w-7 items-center justify-center rounded-md transition-colors",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted",
      )}
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
