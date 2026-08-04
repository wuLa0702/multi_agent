/**
 * EmptyChat — 对话空状态（v2 §3.4 / v3 §3.1.3）。
 * 渐变图标（呼吸动画）+「开始新对话」+ 副标题 + 快捷问题胶囊。
 */

import { Sparkles } from "lucide-react";
import { useChatStore } from "@/lib/stores/chatStore";

const QUICK_QUESTIONS = [
  "帮我写一个 Python 爬虫",
  "解释一下 LangGraph 工作原理",
  "安装一个搜索 Skill",
];

export default function EmptyChat() {
  const send = useChatStore((s) => s.send);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 py-16">
      <div className="breathe mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-violet-500/20 shadow-sm">
        <Sparkles className="size-8 text-primary" strokeWidth={1.5} />
      </div>
      <h2 className="text-lg font-semibold">开始新对话</h2>
      <p className="mb-6 text-xs text-muted-foreground">
        基于你的 Agent 能力，回答问题、执行任务、编写代码
      </p>
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
  );
}
