/**
 * 审批弹窗 — 前端唯一「决策者」入口（契约 approve 事件 → POST /v1/chat/approve）。
 *
 * 流程（设计 §7.2）：approve 事件 → 弹窗 → 通过/拒绝 → 202 → 自动 resume。
 * 失败兜底：RUN_NOT_FOUND / NOT_PENDING → store 已清理状态，弹窗自动消失（本地提示）。
 */

import { useEffect, useState } from "react";
import { ShieldAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useChatStore } from "@/lib/stores/chatStore";

export default function ApproveDialog() {
  const pendingApproval = useChatStore((s) => s.pendingApproval);
  const approve = useChatStore((s) => s.approve);
  const reject = useChatStore((s) => s.reject);
  const streamStatus = useChatStore((s) => s.streamStatus);

  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [showNote, setShowNote] = useState(false);

  // 弹窗关闭（approve/reject 提交后或审批失效）时重置本地态
  useEffect(() => {
    if (!pendingApproval) {
      setNote("");
      setBusy(false);
      setShowNote(false);
    }
  }, [pendingApproval]);

  if (!pendingApproval) return null;

  const handleApprove = async () => {
    setBusy(true);
    await approve();
    setBusy(false);
  };

  const handleReject = async () => {
    setBusy(true);
    await reject(showNote ? note || undefined : undefined);
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 shadow-xl">
        <div className="flex items-start justify-between border-b border-neutral-200 dark:border-neutral-800 p-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="size-5 text-amber-500" />
            <h2 className="text-sm font-semibold">操作需要审批</h2>
          </div>
          <span className="font-mono text-[10px] text-neutral-400">{pendingApproval.run_id.slice(0, 8)}</span>
        </div>

        <div className="p-4 space-y-3 text-sm">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-neutral-400">工具</div>
            <div className="mt-0.5 font-mono">{pendingApproval.tool_name}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-neutral-400">参数</div>
            <pre className="mt-0.5 max-h-32 overflow-y-auto whitespace-pre-wrap break-all rounded bg-neutral-50 dark:bg-neutral-900 p-2 text-xs text-neutral-600 dark:text-neutral-400">
              {JSON.stringify(pendingApproval.arguments, null, 2)}
            </pre>
          </div>
          {pendingApproval.message && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-neutral-400">说明</div>
              <div className="mt-0.5 text-xs text-neutral-600 dark:text-neutral-400">{pendingApproval.message}</div>
            </div>
          )}

          {showNote && (
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="拒绝理由（可选，会注入 Agent 上下文）"
              rows={2}
              className="text-xs"
            />
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-neutral-200 dark:border-neutral-800 p-3">
          {!showNote ? (
            <Button variant="ghost" size="sm" onClick={() => setShowNote(true)}>
              拒绝…
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={() => setShowNote(false)}>
                <X className="size-3.5" /> 取消
              </Button>
              <Button variant="destructive" size="sm" onClick={() => void handleReject()} disabled={busy}>
                拒绝
              </Button>
            </>
          )}
          <Button size="sm" onClick={() => void handleApprove()} disabled={busy}>
            {busy ? "提交中…" : "通过"}
          </Button>
        </div>
        {streamStatus !== "awaiting_approval" && (
          <div className="px-4 pb-3 text-[10px] text-amber-600 dark:text-amber-400">
            审批状态已变化，此弹窗即将关闭
          </div>
        )}
      </div>
    </div>
  );
}
