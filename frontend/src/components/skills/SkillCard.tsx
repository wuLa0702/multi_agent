/**
 * SkillCard — 市场条目卡片（SkillMarketPanel 列表项）。
 * 展示名称/描述/来源与类型 badge/使用量；安装按钮（安装中 spinner）。
 */

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Plug, FileText } from "lucide-react";
import type { SkillMarketItem } from "@/lib/api/types";

interface Props {
  item: SkillMarketItem;
  installing: boolean;
  installed: boolean;
  onInstall: (item: SkillMarketItem, force?: boolean) => Promise<void>;
}

export default function SkillCard({ item, installing, installed, onInstall }: Props) {
  const [error, setError] = useState<string | null>(null);

  const handleInstall = async (force = false) => {
    setError(null);
    try {
      await onInstall(item, force);
    } catch (e) {
      setError(e instanceof Error ? e.message : "安装失败");
    }
  };

  return (
    <div className="card-hover flex flex-col rounded-xl border border-border bg-card p-3.5 shadow-xs space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2.5">
          {/* 图标区（方案 §5.2.2-2） */}
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
            {item.skill_type === "mcp_server" ? (
              <Plug className="size-4.5" />
            ) : (
              <FileText className="size-4.5" />
            )}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium">{item.name}</span>
              {item.verified && (
                <Badge variant="secondary" className="shrink-0 text-[10px] px-1.5 py-0">
                  已验证
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                {item.skill_type === "mcp_server" ? "MCP Server" : "SKILL.md"}
              </Badge>
              <span className="text-[10px] text-muted-foreground">
                {item.source} · {item.use_count > 0 ? `${item.use_count} 次使用` : "新条目"}
              </span>
            </div>
          </div>
        </div>
        {installed ? (
          <div className="flex items-center gap-1.5 shrink-0">
            <Badge variant="secondary">已安装</Badge>
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2.5 text-xs"
              onClick={() => handleInstall(true)}
              disabled={installing}
              title="重新拉取最新版本（升级）"
            >
              {installing && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              升级
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="shrink-0 h-7 px-2.5 text-xs"
            onClick={() => handleInstall(false)}
            disabled={installing}
          >
            {installing && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
            安装
          </Button>
        )}
      </div>

      {item.description && (
        <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
