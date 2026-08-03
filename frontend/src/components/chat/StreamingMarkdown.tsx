/**
 * 流式 markdown 渲染 — 复用 shared/MarkdownRenderer（marked）。
 * MVP 直接渲染（store 实时内容）；200ms 节流优化为后置项（设计 §8.2 风险 2）。
 */

import MarkdownRenderer from "@/components/shared/MarkdownRenderer";

interface Props {
  content: string;
}

export default function StreamingMarkdown({ content }: Props) {
  if (!content) {
    return <span className="text-muted-foreground animate-pulse">▍</span>;
  }
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none break-words">
      <MarkdownRenderer content={content} />
    </div>
  );
}
