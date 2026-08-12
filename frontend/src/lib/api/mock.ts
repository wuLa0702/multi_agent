/**
 * mock 数据源（开发/测试用，前端功能开发计划 §1）。
 * 与真实 streamChat 同接口（StreamCallbacks），按契约字段生成 SSE 序列：
 * - 新消息：start → token×N → tool_call → approve（挂起）→（resume 后）start(resumed) → token → done
 * - 审批决策由用户在 ApprovalCard 操作，resume 触发新 mock 流
 * 接真实后端：MOCK_ENABLED = false 即切换（契约不变）。
 */

import type { ChatStreamRequest, SSEEvent } from "./types";

// ── REST mock 数据（F1/F2/F4/F5，2026-08-12）──────────────────────────────

/** mock 模型列表（含单价，F1 数据源） */
export function mockProviders() {
  return {
    providers: [
      { id: 1, slug: "deepseek", name: "DeepSeek", is_active: true, models: [{ provider_id: 1, name: "deepseek-v4-flash", is_default: true, is_active: true, input_price: 0.001, output_price: 0.002 }] },
      { id: 2, slug: "ark", name: "豆包", is_active: true, models: [{ provider_id: 2, name: "doubao-seed", is_default: true, is_active: true, input_price: 0.006, output_price: 0.03 }] },
    ],
  };
}

/** mock 成本汇总（F2） */
export function mockCostSummary(sessionId: string) {
  return { session_id: sessionId, total_cost: 1.2345, input_tokens: 12000, output_tokens: 3000, alert_count: 1 };
}

/** mock 成本告警列表（F2） */
export function mockCostAlerts() {
  return { status: "ok", items: [{ threshold: 1, total_cost: 1.23, created_at: "2026-08-12T12:00:00" }], total: 1 };
}

/** mock MCP 连接列表（F4） */
export function mockMcpServers() {
  return { status: "ok", items: [{ id: 1, name: "demo-server", transport: "stdio", url: "http://demo", is_active: true, source: "smithery", version: "1.0" }], total: 1 };
}

/** mock 系统配置（F5） */
export function mockSettings() {
  return { status: "ok", settings: { hitl_enabled: "true", log_report: "false" } };
}

/** 开发/测试开关：true = 走 mock 流；联调真后端时改 false */
export const MOCK_ENABLED = true;

/** 与 streamChat 对齐的回调集合（复用 sse.ts 的 StreamCallbacks 类型） */
import type { StreamCallbacks } from "./sse";

/** mock HITL 开关（localStorage 持久化；SettingsPage 开关联动，默认开便于测试） */
const HITL_MOCK_KEY = "multi-agent.mock.hitlEnabled";
export function isHitlEnabledMock(): boolean {
  return localStorage.getItem(HITL_MOCK_KEY) !== "false";
}
export function setHitlEnabledMock(enabled: boolean): void {
  localStorage.setItem(HITL_MOCK_KEY, String(enabled));
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** mock 审批事件（高危：任意代码执行，三决策） */
function mockApproveEvent(): SSEEvent {
  return {
    type: "approve",
    run_id: `mock-run-${Date.now()}`,
    checkpoint_id: `mock-cp-${Date.now()}`, // P0 HITL v1.1：resume 恢复键
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
    cb.onEvent({ type: "cost_alert", session_id: req.session_id ?? "mock", total_cost: 12.5, threshold: 10 } as SSEEvent);
    cb.onEvent({ type: "done", run_id: req.resume_run_id, session_id: req.session_id ?? "mock", duration_ms: 1200, context_used: 8600, context_total: 128_000 } as SSEEvent);
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
  // 任务规划（v5.0 §2.3 mock）：5 步计划逐步完成 → 顶部 Todo 面板
  const todoBase = Date.now();
  const todoTitles = ["需求分析", "方案设计", "代码实现", "测试验证", "部署上线"];
  const mkTodos = (doneCount: number, activeIdx: number): SSEEvent => ({
    type: "todos",
    items: todoTitles.map((title, i) => ({
      id: `${todoBase}-${i}`,
      title,
      status: i < doneCount ? "completed" : i === activeIdx ? "in_progress" : "pending",
    })),
  } as unknown as SSEEvent);
  cb.onEvent(mkTodos(0, 0));
  for (let d = 1; d <= 3; d++) {
    if (signal.aborted) return;
    await sleep(400);
    cb.onEvent(mkTodos(d, d));
  }
  if (signal.aborted) return;
  await sleep(300);
  if (isHitlEnabledMock()) {
    // 高危操作 → 触发审批（挂起，等待用户决策；resume 走上方恢复流）
    cb.onEvent(mockApproveEvent());
  } else {
    // HITL 关闭：直接完成（带上下文用量，v4.0 §3.2）
    cb.onEvent({ type: "token", text: "（HITL 已关闭，高风险操作自动执行）" } as SSEEvent);
    cb.onEvent({ type: "cost_alert", session_id: req.session_id ?? "mock", total_cost: 12.5, threshold: 10 } as SSEEvent);
    cb.onEvent({ type: "done", run_id: "mock-run-new", session_id: req.session_id ?? "mock", duration_ms: 900, context_used: 5200, context_total: 128_000 } as SSEEvent);
    cb.onEnd();
  }
}
