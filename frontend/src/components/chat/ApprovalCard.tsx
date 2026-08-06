/**
 * ApprovalCard — 高风险审批卡片（前端功能规划 §4.2 / v4.0 §2.1）。
 * 触发：SSE approve 事件 → store.pendingApproval 就绪 → 本卡片渲染（对话流挂起）。
 * 风险分级：高危（run_code_in_sandbox）红徽标三决策；中危（文件/技能）橙徽标两决策。
 * 交互：批准 / 拒绝（附理由）/ 编辑后批准（高危，JSON 编辑参数）；提交中 loading。
 * 历史：已处理审批折叠为单行（approvalHistory）。
 */

import { useState } from "react";
import { AlertTriangle, ShieldAlert, ShieldAlert as ShieldMid, Check, X, PencilLine } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";

/** 工具名 → 风险等级（对齐后端 hitl.py interrupt_on 风险分级） */
const HIGH_RISK_TOOLS = new Set(["run_code_in_sandbox"]);

function riskOf(toolName: string): "high" | "medium" {
  return HIGH_RISK_TOOLS.has(toolName) ? "high" : "medium";
}

export default function ApprovalCard() {
  const pending = useChatStore((s) => s.pendingApproval);
  const streamStatus = useChatStore((s) => s.streamStatus);
  const history = useChatStore((s) => s.approvalHistory);
  const approve = useChatStore((s) => s.approve);
  const reject = useChatStore((s) => s.reject);
  const approveWithEdit = useChatStore((s) => s.approveWithEdit);

  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [editedArgs, setEditedArgs] = useState("");

  if (!pending) {
    // 无待审批：仅渲染审批历史（折叠单行）
    if (history.length === 0) return null;
    return (
      <div className="mx-auto w-full max-w-2xl space-y-1 px-4 py-1">
        {history.map((h, i) => (
          <div key={i} className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
            {h.action === "reject" ? <X className="size-3.5 text-destructive" /> : <Check className="size-3.5 text-success" />}
            <span>
              {h.action === "approve" ? "已批准" : h.action === "edit" ? "已编辑后批准" : "已拒绝"} · {h.tool_name} ·{" "}
              {new Date(h.ts).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>
    );
  }

  const risk = riskOf(pending.tool_name);
  const isHigh = risk === "high";
  const isSubmitting = submitting || streamStatus === "connecting";

  const handleApprove = async () => {
    setSubmitting(true);
    await approve();
    setSubmitting(false);
    setEditing(false);
  };

  const handleReject = async () => {
    setSubmitting(true);
    await reject(note || undefined);
    setSubmitting(false);
    setNote("");
  };

  const handleEditApprove = async () => {
    setSubmitting(true);
    try {
      await approveWithEdit(JSON.parse(editedArgs || "{}") as Record<string, unknown>);
    } catch {
      // JSON 非法：不提交，提示
      setSubmitting(false);
      return;
    }
    setSubmitting(false);
    setEditing(false);
  };

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-2">
      <div
        className={cn(
          "rounded-xl border p-4 shadow-md transition-colors",
          isHigh ? "border-destructive/40 bg-destructive/5" : "border-warning/40 bg-warning/5",
          isSubmitting && "opacity-70"
        )}
      >
        {/* 头部：警示 + 风险徽标 */}
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium">
            <AlertTriangle className={cn("size-4", isHigh ? "text-destructive" : "text-warning")} />
            需要您的批准
          </div>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[11px] font-medium text-white",
              isHigh ? "bg-destructive" : "bg-warning"
            )}
          >
            {isHigh ? <span className="flex items-center gap-1"><ShieldAlert className="size-3" />高危</span> : <span className="flex items-center gap-1"><ShieldMid className="size-3" />中危</span>}
          </span>
        </div>

        {/* 工具名 */}
        <div className="mb-2 font-mono text-sm">{pending.tool_name}</div>

        {/* 参数预览 / 编辑区 */}
        {editing ? (
          <textarea
            value={editedArgs}
            onChange={(e) => setEditedArgs(e.target.value)}
            rows={6}
            className="mb-2 w-full resize-y rounded-lg border border-border bg-background p-2 font-mono text-xs"
            aria-label="编辑参数 JSON"
          />
        ) : (
          <pre className="mb-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border bg-background/60 p-2 font-mono text-xs text-muted-foreground">
            {JSON.stringify(pending.arguments, null, 2)}
          </pre>
        )}

        {/* 审批原因 */}
        <p className="mb-3 text-xs text-muted-foreground">💡 {pending.message}</p>

        {/* 拒绝理由（仅拒绝时填写） */}
        {!editing && (
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="拒绝理由（可选）"
            className="mb-3 w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs"
          />
        )}

        {/* 决策按钮（v4.0 §2.1.5：主操作在右） */}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={handleReject}
            disabled={isSubmitting}
            className="rounded-lg border border-destructive/40 px-3 py-1.5 text-sm text-destructive transition hover:bg-destructive/10 disabled:opacity-50"
          >
            拒绝
          </button>
          {isHigh && !editing && (
            <button
              type="button"
              onClick={() => {
                setEditedArgs(JSON.stringify(pending.arguments, null, 2));
                setEditing(true);
              }}
              disabled={isSubmitting}
              className="flex items-center gap-1 rounded-lg bg-warning px-3 py-1.5 text-sm text-white transition hover:bg-warning/90 disabled:opacity-50"
            >
              <PencilLine className="size-3.5" /> 编辑后批准
            </button>
          )}
          {editing && (
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={isSubmitting}
              className="rounded-lg border border-border px-3 py-1.5 text-sm transition hover:bg-muted disabled:opacity-50"
            >
              取消编辑
            </button>
          )}
          {isSubmitting ? (
            <span className="flex items-center gap-2 rounded-lg bg-primary/60 px-4 py-1.5 text-sm text-primary-foreground">
              <span className="size-3 animate-spin rounded-full border-2 border-white/40 border-t-white" /> 提交中…
            </span>
          ) : editing ? (
            <button
              type="button"
              onClick={handleEditApprove}
              className="rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground transition hover:bg-primary/90"
            >
              确认并批准
            </button>
          ) : (
            <button
              type="button"
              onClick={handleApprove}
              className="flex items-center gap-1 rounded-lg bg-primary px-4 py-1.5 text-sm text-primary-foreground transition hover:bg-primary/90"
            >
              <Check className="size-4" /> 批准
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
