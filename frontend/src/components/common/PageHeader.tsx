/**
 * PageHeader — 统一页面标题栏（56px 高，v2 §2.1）。
 * 所有栏的顶部标题栏统一：左右内边距 16px、底部 1px 分隔线、背景与栏一致。
 * 左侧标题（可选点击重命名）+ 右侧操作区；children 可放标题栏下方附加行（筛选栏等）。
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props {
  title: string;
  icon?: ReactNode;
  right?: ReactNode;
  onTitleClick?: () => void;
  children?: ReactNode;
  className?: string;
}

export default function PageHeader({ title, icon, right, onTitleClick, children, className }: Props) {
  return (
    <div className={cn("shrink-0 border-b border-border bg-card", className)}>
      <div className="flex h-14 items-center gap-2 px-4">
        {icon && <span className="flex items-center text-primary">{icon}</span>}
        {onTitleClick ? (
          <button
            type="button"
            onClick={onTitleClick}
            className="press truncate text-sm font-semibold hover:text-primary"
            title="点击重命名"
          >
            {title}
          </button>
        ) : (
          <h1 className="truncate text-sm font-semibold">{title}</h1>
        )}
        <div className="ml-auto flex items-center gap-1.5">{right}</div>
      </div>
      {children}
    </div>
  );
}
