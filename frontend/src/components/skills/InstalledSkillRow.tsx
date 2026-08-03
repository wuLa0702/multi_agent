/**
 * InstalledSkillRow — 已安装 Skill 行（列表项）。
 * 名称/类型/版本 + 启用开关 + 卸载按钮（confirm 确认）。
 */

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Trash2, Loader2 } from "lucide-react";
import { showConfirm } from "@/components/ui/confirm-dialog";
import type { InstalledSkill } from "@/lib/api/types";

interface Props {
  skill: InstalledSkill;
  onToggle: (id: number, active: boolean) => Promise<void>;
  onUninstall: (id: number) => Promise<void>;
}

export default function InstalledSkillRow({ skill, onToggle, onUninstall }: Props) {
  const [busy, setBusy] = useState(false);

  const handleToggle = async () => {
    setBusy(true);
    try {
      await onToggle(skill.id, !skill.is_active);
    } finally {
      setBusy(false);
    }
  };

  const handleUninstall = async () => {
    const ok = await showConfirm(`卸载「${skill.name}」？`, {
      title: "卸载 Skill",
      confirmLabel: "卸载",
      cancelLabel: "取消",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await onUninstall(skill.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium">{skill.name}</span>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              {skill.skill_type === "mcp_server" ? "MCP Server" : "SKILL.md"}
            </Badge>
          </div>
          <div className="text-[10px] text-neutral-500 mt-0.5">
            {skill.version}
            {skill.source !== "manual" ? ` · ${skill.source}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleToggle}
            disabled={busy}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              skill.is_active ? "bg-primary" : "bg-neutral-300 dark:bg-neutral-700"
            }`}
            title={skill.is_active ? "点击停用" : "点击启用"}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                skill.is_active ? "translate-x-[18px]" : "translate-x-[3px]"
              }`}
            />
          </button>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 text-neutral-400 hover:text-red-500"
            onClick={handleUninstall}
            disabled={busy}
            title="卸载"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>
      {!skill.is_active && (
        <p className="text-[10px] text-amber-600 dark:text-amber-400">已停用（工具不再注入 Agent）</p>
      )}
    </div>
  );
}
