/**
 * HelpTooltip — 通用问号悬浮提示（T12 通用规范，2026-08-20）。
 * 全项目统一：需要解释的功能/字段旁加 `?` 图标，hover 弹出说明。
 * 用法：<HelpTooltip content="输入 token = 本轮累计 LLM 接收的 token 数" />
 */

import { HelpCircle } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface HelpTooltipProps {
  content: string;
  className?: string;
  side?: "top" | "bottom" | "left" | "right";
}

export function HelpTooltip({ content, className, side = "top" }: HelpTooltipProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex shrink-0 items-center justify-center text-muted-foreground/60 hover:text-foreground transition-colors",
            className
          )}
          aria-label="说明"
        >
          <HelpCircle className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side={side} className="max-w-xs text-xs leading-relaxed">
        {content}
      </TooltipContent>
    </Tooltip>
  );
}
