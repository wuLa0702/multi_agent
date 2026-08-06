/**
 * mock 数据源（开发/测试用，前端功能开发计划 §1）。
 * 与真实 streamChat 同接口（StreamCallbacks），按契约字段生成 SSE 序列：
 * - 新消息：start → token×N → tool_call → approve（挂起）→（resume 后）start(resumed) → token → done
 * - 审批决策由用户在 ApprovalCard 操作，resume 触发新 mock 流
 * 接真实后端：MOCK_ENABLED = false 即切换（契约不变）。
 */

import type { ChatStreamRequest, SSEEvent } from "./types";

/** 开发/测试开关：true = 走 mock 流；联调真后端时改 false */
export const MOCK_ENABLED = true;

/** 与 streamChat 对齐的回调集合（复用 sse.ts 的 StreamCallbacks 类型） */
import type { StreamCallbacks } from "./sse";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** mock 审批事件（高危：任意代码执行，三决策） */
function mockApproveEvent(): SSEEvent {
  return {
    type: "approve",
    run_id: `mock-run-${Date.now()}`,
    call_id: `mock-call-${Date.now()}`,
    tool_name: "run_code_in_sandbox",
    arguments: {
      code: "print('hello from mock sandbox')",
      timeout: 30,
      language: "python",
    },
    message: "此操作将在沙箱中执行任意代码，可能产生安全风险",
  } as SSEEvent;
}

/** mock 子代理事件序列（B3 用） */
function mockSubagentEvents(): SSEEvent[] {
  const base = Date.now();
  return [
    { type: "subagent", name: "市场研究员", status: "start" } as SSEEvent,
    { type: "tool_call", call_id: `m-${base}`, name: "internet_search", arguments: { query: "AI Agent 市场" }, status: "running" } as SSEEvent,
    { type: "tool_call", call_id: `m-${base}`, name: "internet_search", arguments: {}, status: "success", result: "3 篇行业报告" } as SSEEvent,
    { type: "subagent", name: "市场研究员", status: "end", summary: "市场规模 2026 年预计 500 亿" } as SSEEvent,
    { type: "subagent", name: "商业分析师", status: "start" } as SSEEvent,
    { type: "subagent", name: "商业分析师", status: "end", summary: "建议关注企业级市场" } as SSEEvent,
  ];
}

/**
 * mock 流：模拟后端 SSE 序列。
 * resume_run_id 传入 → 恢复流（start.resumed=true）；否则新流（token→工具→审批挂起）。
 */
export async function streamChatMock(
  req: ChatStreamRequest,
  cb: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const isResume = Boolean(req.resume_run_id);

  if (isResume) {
    // 审批后的恢复流
    cb.onEvent({ type: "start", run_id: req.resume_run_id, session_id: req.session_id ?? "mock", resumed: true } as SSEEvent);
    for (const t of ["审批已通过，继续执行……", "沙箱代码运行成功。", "结论：mock 数据验证通过。"]) {
      if (signal.aborted) return;
      await sleep(300);
      cb.onEvent({ type: "token", text: t } as SSEEvent);
    }
    cb.onEvent({ type: "done", run_id: req.resume_run_id, session_id: req.session_id ?? "mock", duration_ms: 1200 } as SSEEvent);
    cb.onEnd();
    return;
  }

  // 新流：start → token×N → 工具调用 → 子代理 → 审批挂起
  cb.onEvent({ type: "start", run_id: "mock-run-new", session_id: req.session_id ?? "mock", resumed: false } as SSEEvent);
  for (const t of ["好的，我将调研 AI Agent 市场并给出报告。", "首先委派子代理收集最新数据……"]) {
    if (signal.aborted) return;
    await sleep(250);
    cb.onEvent({ type: "token", text: t } as SSEEvent);
  }
  if (signal.aborted) return;
  for (const e of mockSubagentEvents()) {
    await sleep(200);
    cb.onEvent(e);
  }
  if (signal.aborted) return;
  await sleep(300);
  // 高危操作 → 触发审批（挂起，等待用户决策；resume 走上方恢复流）
  cb.onEvent(mockApproveEvent());
}
