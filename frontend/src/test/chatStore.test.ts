/**
 * chatStore 单测 — 流状态机流转（方案-前端设计-v1 §5.1/§5.2）。
 * mock sse/client，通过回调序列驱动状态机，断言状态迁移与数据累积。
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { useChatStore } from "@/lib/stores/chatStore";
import { ApiError } from "@/lib/api/client";
import type { SSEEvent } from "@/lib/api/types";

// mock 外部依赖：streamChat 捕获回调；api 全 mock
// 注意：mock 工厂被 hoist 到 import 之前执行，工厂内引用的变量必须 vi.hoisted
const { streamChatMock, apiMock } = vi.hoisted(() => ({
  streamChatMock: vi.fn(),
  apiMock: {
  createSession: vi.fn(),
  listSessions: vi.fn(),
  listMessages: vi.fn(),
  approve: vi.fn(),
  updateSessionTitle: vi.fn(),
  deleteSession: vi.fn(),
  health: vi.fn(),
  },
}));

vi.mock("@/lib/api/sse", () => ({
  streamChat: (...args: unknown[]) => streamChatMock(...args),
}));

// 测试环境关闭 mock 流（chatStore 走 streamChat，由上方 vi.fn 捕获）
vi.mock("@/lib/api/mock", () => ({
  MOCK_ENABLED: false,
  streamChatMock: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  api: apiMock,
  ApiError: class ApiError extends Error {
    code: string;
    status: number;
    detail: string;
    constructor(status: number, body: { code: string; detail: string; error: string }) {
      super(body.error);
      this.code = body.code;
      this.status = status;
      this.detail = body.detail;
    }
  },
}));

/** 捕获最近一次 streamChat 调用的回调（send/resume 后自动更新为最新流） */
interface StreamCb {
  onEvent: (e: SSEEvent) => void;
  onHttpError: (status: number, body: unknown) => void;
  onNetworkError: (err: Error) => void;
  onEnd: () => void;
}
let capturedCallbacks: StreamCb | null = null;

/**
 * 建立真实流（等价于用户已发送消息）：send 内部同步调用 streamChat，
 * mockImplementation 捕获到 store 的真实回调，之后 fireEvent 即驱动状态机。
 */
async function setupStream() {
  useChatStore.setState({ sessionId: "s1" });
  await useChatStore.getState().send("setup");
  // 清理 setup 副作用（user 消息/提示），保持用例预置状态纯净
  useChatStore.setState({ messages: [], notices: [] });
}

/** 惰性流标记：首个 fireEvent 前自动建立（幂等） */
let streamReady = false;

/** 触发最近一次捕获到的回调（首次自动建立真实流） */
async function fireEvent(event: SSEEvent) {
  if (!streamReady) {
    streamReady = true;
    await setupStream();
  }
  capturedCallbacks?.onEvent(event);
}

beforeEach(async () => {
  vi.clearAllMocks();
  localStorage.clear();
  // 重置 store 到初始态
  useChatStore.setState({
    sessionId: null,
    messages: [],
    notices: [],
    toolCalls: {},
    agentTree: [],
    streamStatus: "idle",
    pendingApprovals: [],
    pendingRunId: null,
    approvalHistory: [],
  });
  streamChatMock.mockImplementation((_req, cb) => {
    capturedCallbacks = cb;
    return Promise.resolve();
  });
  streamReady = false;
});

describe("发送消息（send）", () => {
  it("无 sessionId 时先创建会话再发起流", async () => {
    apiMock.createSession.mockResolvedValue({ id: "s1", title: "新会话", created_at: "", updated_at: "" });
    const store = useChatStore.getState();
    await store.send("你好");

    expect(apiMock.createSession).toHaveBeenCalledTimes(1);
    expect(useChatStore.getState().sessionId).toBe("s1");
    // 用户消息已入流，streamChat 带 session_id + message
    const req = streamChatMock.mock.calls.at(-1)![0];
    expect(req).toMatchObject({ session_id: "s1", message: "你好" });
  });

  it("已有 sessionId 时不重复创建", async () => {
    useChatStore.setState({ sessionId: "s1" });
    await useChatStore.getState().send("hi");
    expect(apiMock.createSession).not.toHaveBeenCalled();
    expect(streamChatMock).toHaveBeenCalledTimes(1);
  });

  it("空文本 / 流式中不发送", async () => {
    await useChatStore.getState().send("   ");
    expect(streamChatMock).not.toHaveBeenCalled();
  });
});

describe("token 事件", () => {
  it("追加到现有 assistant 消息（流式累积）", async () => {
    // 纯事件驱动：首 token 新建 assistant 消息，次 token 追加（真实流语义）
    await fireEvent({ type: "token", text: "你好" });
    await fireEvent({ type: "token", text: "，世界" });
    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0]).toMatchObject({ role: "assistant", content: "你好，世界" });
  });

  it("无 assistant 消息时新建", async () => {
    useChatStore.setState({ sessionId: "s1" });
    await fireEvent({ type: "token", text: "hi" });
    const msgs = useChatStore.getState().messages;
    expect(msgs.at(-1)).toMatchObject({ role: "assistant", content: "hi" });
  });
});

describe("tool_call 事件（幂等 upsert）", () => {
  it("running → success 状态流转", async () => {
    await fireEvent({ type: "tool_call", call_id: "c1", name: "search", arguments: { q: "x" }, status: "running" });
    await fireEvent({ type: "tool_call", call_id: "c1", name: "search", arguments: { q: "x" }, status: "success", result: "结果" });
    const call = useChatStore.getState().toolCalls["c1"];
    expect(call.status).toBe("success");
    expect(call.result).toBe("结果");
  });

  it("已完成后再来陈旧 running 不覆盖（resume 重放保护）", async () => {
    await fireEvent({ type: "tool_call", call_id: "c1", name: "search", arguments: {}, status: "success", result: "R" });
    await fireEvent({ type: "tool_call", call_id: "c1", name: "search", arguments: {}, status: "running" });
    expect(useChatStore.getState().toolCalls["c1"].status).toBe("success");
  });
});

describe("subagent 事件", () => {
  it("start 追加节点，end 匹配同名节点置 done", async () => {
    await fireEvent({ type: "subagent", name: "analyst", status: "start" });
    await fireEvent({ type: "subagent", name: "analyst", status: "end", summary: "结论" });
    const tree = useChatStore.getState().agentTree;
    expect(tree).toHaveLength(1);
    expect(tree[0]).toMatchObject({ name: "analyst", status: "done", summary: "结论" });
  });
});

describe("审批流程", () => {
  // 审批测试事件统一带 checkpoint_id（P0 HITL v1.1：resume 恢复键）
  const approvalFire = (msg: string) =>
    fireEvent({ type: "approve", run_id: "r1", checkpoint_id: "cp-1", call_id: "c1", tool_name: "rm", arguments: {}, message: msg });

  it("approve 事件 → awaiting_approval + localStorage 持久化", async () => {
    await approvalFire("删除文件");
    const s = useChatStore.getState();
    expect(s.streamStatus).toBe("awaiting_approval");
    expect(s.pendingApprovals[0]?.run_id).toBe("r1");
    expect(localStorage.getItem("multi-agent.pendingRunId")).toBe("cp-1");
  });

  it("approve() → 提交接口 + resume 恢复执行", async () => {
    apiMock.approve.mockResolvedValue({ status: "ok", accepted: true });
    await approvalFire("x");

    await useChatStore.getState().approve();

    expect(apiMock.approve).toHaveBeenCalledWith({ run_id: "r1", checkpoint_id: "cp-1", call_id: "c1", action: "approve", note: null, edited_arguments: null });
    const resumeReq = streamChatMock.mock.calls.at(-1)![0];
    expect(resumeReq).toMatchObject({ resume_run_id: "cp-1" });
  });

  it("reject() → action 为 reject 且带 note", async () => {
    apiMock.approve.mockResolvedValue({ status: "ok", accepted: true });
    await approvalFire("x");

    await useChatStore.getState().reject("理由");

    expect(apiMock.approve).toHaveBeenCalledWith({ run_id: "r1", checkpoint_id: "cp-1", call_id: "c1", action: "reject", note: "理由", edited_arguments: null });
  });

  it("审批失效（RUN_NOT_FOUND）→ 清理状态 + 提示", async () => {
    const { ApiError } = await import("@/lib/api/client");
    apiMock.approve.mockRejectedValue(new ApiError(404, { code: "RUN_NOT_FOUND", detail: "run 不存在", error: "" }));
    await approvalFire("x");

    await useChatStore.getState().approve();

    const s = useChatStore.getState();
    expect(s.streamStatus).toBe("idle");
    expect(s.pendingApprovals).toHaveLength(0);
    expect(localStorage.getItem("multi-agent.pendingRunId")).toBeNull();
    expect(s.notices.some((n) => n.kind === "info" && n.text.includes("已失效"))).toBe(true);
  });
});

describe("start 事件（resume 语义）", () => {
  it("resumed=false 清空面板；resumed=true 保留", async () => {
    useChatStore.setState({
      toolCalls: { c1: { call_id: "c1", name: "t", arguments: {}, status: "success", result: "r" } },
      agentTree: [{ key: "a-1", name: "analyst", status: "done", summary: "s" }],
    });
    await fireEvent({ type: "start", run_id: "r2", session_id: "s1", resumed: true });
    expect(useChatStore.getState().toolCalls).not.toEqual({});
    expect(useChatStore.getState().streamStatus).toBe("streaming");

    await fireEvent({ type: "start", run_id: "r3", session_id: "s1", resumed: false });
    expect(useChatStore.getState().toolCalls).toEqual({});
    expect(useChatStore.getState().agentTree).toEqual([]);
  });
});

describe("结束与错误", () => {
  it("done → idle + 清审批态", async () => {
    useChatStore.setState({ pendingApprovals: [{ run_id: "r1", checkpoint_id: "cp-1", call_id: "c", tool_name: "t", arguments: {}, message: "m" }], streamStatus: "awaiting_approval", pendingRunId: "cp-1" });
    localStorage.setItem("multi-agent.pendingRunId", "r1");

    await fireEvent({ type: "done", run_id: "r1", session_id: "s1", duration_ms: 5 });

    const s = useChatStore.getState();
    expect(s.streamStatus).toBe("idle");
    expect(s.pendingApprovals).toHaveLength(0);
    expect(localStorage.getItem("multi-agent.pendingRunId")).toBeNull();
  });

  it("error 事件 → idle + 错误提示（retryable 标注）", async () => {
    await fireEvent({ type: "error", code: "LLM_TIMEOUT", detail: "LLM 超时", retryable: true });
    const s = useChatStore.getState();
    expect(s.streamStatus).toBe("idle");
    expect(s.notices.some((n) => n.kind === "error" && n.text.includes("可重试"))).toBe(true);
  });

  it("summarize → 系统提示气泡", async () => {
    await fireEvent({ type: "summarize", summary: "历史摘要", removed_count: 5, keep_from_message_id: 10 });
    expect(useChatStore.getState().notices.some((n) => n.text.includes("移除 5 条"))).toBe(true);
  });
});

describe("loadHistory", () => {
  it("拉取消息并重置面板", async () => {
    apiMock.listMessages.mockResolvedValue({
      status: "ok",
      items: [{ id: 1, session_id: "s1", role: "user", content: "hi", created_at: "" }],
      next_before_id: null,
      has_more: false,
    });
    useChatStore.setState({ toolCalls: { c1: { call_id: "c1", name: "t", arguments: {}, status: "running" } } });

    await useChatStore.getState().loadHistory("s1");

    const s = useChatStore.getState();
    expect(s.sessionId).toBe("s1");
    expect(s.messages).toHaveLength(1);
    expect(s.toolCalls).toEqual({});
    expect(s.streamStatus).toBe("idle");
  });
});

describe("done 后静默重拉（设计 §8.1 发现 4 / §8.4 未决项 3：以库为准）", () => {
  const tick = () => new Promise<void>((r) => setTimeout(r, 0));

  it("done → 以库为准替换本地流（id=null），面板保留", async () => {
    apiMock.listMessages.mockResolvedValue({
      status: "ok",
      items: [
        { id: 1, session_id: "s1", role: "user", content: "你好", created_at: "" },
        { id: 2, session_id: "s1", role: "assistant", content: "落库版回复", created_at: "" },
      ],
      next_before_id: null,
      has_more: false,
    });
    useChatStore.setState({
      toolCalls: { c1: { call_id: "c1", name: "t", arguments: {}, status: "success", result: "r" } },
      agentTree: [{ key: "a-1", name: "analyst", status: "done", summary: "s" }],
    });
    await fireEvent({ type: "token", text: "本地流" });

    await fireEvent({ type: "done", run_id: "r1", session_id: "s1", duration_ms: 5 });

    await vi.waitFor(() => {
      const s = useChatStore.getState();
      expect(s.messages).toHaveLength(2);
      expect(s.messages[0].id).toBe(1);
      expect(s.messages[1].content).toContain("落库版");
    });
    const s = useChatStore.getState();
    expect(s.streamStatus).toBe("idle");
    expect(s.toolCalls["c1"]).toBeDefined(); // 面板保留，不随重拉清空
    expect(s.agentTree).toHaveLength(1);
  });

  it("重拉失败 → 静默保留本地流（不打扰用户）", async () => {
    apiMock.listMessages.mockRejectedValue(new Error("net down"));
    await fireEvent({ type: "token", text: "流式内容" });

    await fireEvent({ type: "done", run_id: "r1", session_id: "s1", duration_ms: 5 });
    await tick();

    const s = useChatStore.getState();
    expect(s.messages.at(-1)?.content).toBe("流式内容");
    expect(s.streamStatus).toBe("idle");
    expect(s.notices).toEqual([]);
  });

  it("竞态：done 重拉不覆盖用户已切换的会话", async () => {
    let resolveS1!: (v: unknown) => void;
    apiMock.listMessages.mockImplementation((sid: string) => {
      if (sid === "s1") return new Promise((res) => { resolveS1 = res; });
      return Promise.resolve({
        status: "ok",
        items: [{ id: 9, session_id: "s2", role: "user", content: "另一会话", created_at: "" }],
        next_before_id: null,
        has_more: false,
      });
    });

    // done 触发 s1 重拉（挂起中）
    await fireEvent({ type: "done", run_id: "r1", session_id: "s1", duration_ms: 5 });
    // 用户随即切到 s2
    await useChatStore.getState().loadHistory("s2");
    // 迟到的 s1 重拉结果返回
    resolveS1!({
      status: "ok",
      items: [{ id: 1, session_id: "s1", role: "user", content: "s1 数据", created_at: "" }],
      next_before_id: null,
      has_more: false,
    });
    await tick();

    const s = useChatStore.getState();
    expect(s.sessionId).toBe("s2");
    expect(s.messages[0].id).toBe(9); // 仍是 s2，未被 s1 覆盖
  });
});


describe("审批流程（HITL，v4.0 §2.1）", () => {
  const approveEvent: SSEEvent = {
    type: "approve",
    run_id: "run-1",
    checkpoint_id: "cp-1", // P0 HITL v1.1：resume 恢复键
    call_id: "call-1",
    tool_name: "run_code_in_sandbox",
    arguments: { code: "print(1)" },
    message: "沙箱执行任意代码",
  };

  it("approve 事件 → pendingApprovals 队列 + awaiting_approval", async () => {
    await fireEvent(approveEvent);
    const st = useChatStore.getState();
    expect(st.pendingApprovals).toHaveLength(1);
    expect(st.pendingApprovals[0]).toMatchObject({ run_id: "run-1", tool_name: "run_code_in_sandbox" });
    expect(st.streamStatus).toBe("awaiting_approval");
  });

  it("approve() → 调 API + 历史 + resume 新流", async () => {
    apiMock.approve.mockResolvedValue({ status: "ok", accepted: true });
    await fireEvent(approveEvent);
    await useChatStore.getState().approve();

    expect(apiMock.approve).toHaveBeenCalledWith({ run_id: "run-1", checkpoint_id: "cp-1", call_id: "call-1", action: "approve", note: null, edited_arguments: null });
    expect(useChatStore.getState().approvalHistory).toEqual([{ tool_name: "run_code_in_sandbox", action: "approve", ts: expect.any(String) }]);
    const req = streamChatMock.mock.calls.at(-1)![0];
    expect(req).toMatchObject({ resume_run_id: "cp-1" });
    expect(useChatStore.getState().pendingApprovals).toHaveLength(0);
  });

  it("reject(note) → 携带拒绝理由", async () => {
    apiMock.approve.mockResolvedValue({ status: "ok", accepted: true });
    await fireEvent(approveEvent);
    await useChatStore.getState().reject("参数有风险");
    expect(apiMock.approve).toHaveBeenCalledWith({ run_id: "run-1", checkpoint_id: "cp-1", call_id: "call-1", action: "reject", note: "参数有风险", edited_arguments: null });
    expect(useChatStore.getState().approvalHistory.at(-1)?.action).toBe("reject");
  });

  it("approveWithEdit → action=edit + edited_arguments", async () => {
    apiMock.approve.mockResolvedValue({ status: "ok", accepted: true });
    await fireEvent(approveEvent);
    await useChatStore.getState().approveWithEdit({ code: "print(2)" });
    expect(apiMock.approve).toHaveBeenCalledWith({ run_id: "run-1", checkpoint_id: "cp-1", call_id: "call-1", action: "edit", note: null, edited_arguments: { code: "print(2)" } });
  });

  it("RUN_NOT_FOUND → 审批失效清理", async () => {
    apiMock.approve.mockRejectedValue(new ApiError(404, { code: "RUN_NOT_FOUND", detail: "x", error: "x" }));
    await fireEvent(approveEvent);
    await useChatStore.getState().approve();
    const st = useChatStore.getState();
    expect(st.pendingApprovals).toHaveLength(0);
    expect(st.streamStatus).toBe("idle");
    expect(st.notices.some((n) => n.text.includes("已失效"))).toBe(true);
  });

  it("多 action：首卡 accepted=false 不 resume，次卡 accepted=true 才恢复", async () => {
    const evtA: SSEEvent = { type: "approve", run_id: "run-1", checkpoint_id: "cp-1", call_id: "call-a", tool_name: "run_code_in_sandbox", arguments: {}, message: "A" };
    const evtB: SSEEvent = { type: "approve", run_id: "run-1", checkpoint_id: "cp-1", call_id: "call-b", tool_name: "run_skill_script", arguments: {}, message: "B" };
    await fireEvent(evtA);
    await fireEvent(evtB);
    expect(useChatStore.getState().pendingApprovals).toHaveLength(2);
    expect(useChatStore.getState().pendingApprovals[0].call_id).toBe("call-a");

    // 首卡提交：后端 accepted=false（还有 1 张待审）→ 不 resume，队列移除首卡
    const callsBefore = streamChatMock.mock.calls.length;
    apiMock.approve.mockResolvedValueOnce({ status: "ok", accepted: false });
    await useChatStore.getState().approve();
    expect(streamChatMock.mock.calls.length).toBe(callsBefore); // 未 resume
    expect(useChatStore.getState().pendingApprovals).toHaveLength(1);
    expect(useChatStore.getState().pendingApprovals[0].call_id).toBe("call-b");

    // 次卡提交：accepted=true（决策齐）→ resume
    apiMock.approve.mockResolvedValueOnce({ status: "ok", accepted: true });
    await useChatStore.getState().approve();
    expect(streamChatMock.mock.calls.length).toBe(callsBefore + 1); // resume 触发新流
    expect(useChatStore.getState().pendingApprovals).toHaveLength(0);
  });
});

describe("任务规划（todos，v5.0 §2.3）", () => {
  it("todos 事件 → 全量替换 + 空态隐藏", async () => {
    useChatStore.setState({ todos: [] });
    await fireEvent({
      type: "todos",
      items: [
        { id: "1", title: "需求分析", status: "completed" },
        { id: "2", title: "方案设计", status: "in_progress" },
        { id: "3", title: "代码实现", status: "pending" },
      ],
    } as SSEEvent);
    const todos = useChatStore.getState().todos;
    expect(todos).toHaveLength(3);
    expect(todos[1]).toMatchObject({ title: "方案设计", status: "in_progress" });
    // 后续全量替换（进度推进）
    await fireEvent({
      type: "todos",
      items: [
        { id: "1", title: "需求分析", status: "completed" },
        { id: "2", title: "方案设计", status: "completed" },
        { id: "3", title: "代码实现", status: "in_progress" },
      ],
    } as SSEEvent);
    expect(useChatStore.getState().todos.filter((t) => t.status === "completed")).toHaveLength(2);
  });
});
