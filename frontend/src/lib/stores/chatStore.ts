/**
 * chatStore — 对话流状态机（方案-前端设计-v1 §5/§6）。
 *
 * 流状态机：idle → connecting → streaming ⇄ awaiting_approval → idle
 * 单向数据流：SSE 事件 → store action（唯一写入口）→ 组件订阅。
 *
 * 关键设计：
 * - awaiting_approval 是持久化挂起（后端 interrupt 落库），pendingRunId 存
 *   localStorage，刷新后可恢复（§7.4）
 * - toolCalls 按 call_id 幂等 upsert（resume 后事件续接不重复）
 * - resume 不清空面板（挂起前节点保留），仅重置审批态
 */

import { create, type StoreApi } from "zustand";
import { api, ApiError } from "@/lib/api/client";
import { streamChat } from "@/lib/api/sse";
import type {
  ApproveEvent,
  Message,
  ProviderInfo,
  SSEEvent,
  ToolCallEvent,
} from "@/lib/api/types";

export type StreamStatus =
  | "idle"
  | "connecting"
  | "streaming"
  | "awaiting_approval";

export interface ToolCall {
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "success" | "error";
  result?: string | null;
}

export interface AgentNode {
  key: string; // `${name}-${seq}`（契约 subagent 事件无 id，用 name+序号定位）
  name: string;
  status: "running" | "done";
  summary?: string | null;
}

export interface ChatNotice {
  kind: "info" | "error";
  text: string;
}

const PENDING_RUN_KEY = "multi-agent.pendingRunId";

interface ChatState {
  sessionId: string | null;
  messages: Message[];
  notices: ChatNotice[]; // 系统提示（错误/压缩/审批失效），独立于消息流
  toolCalls: Record<string, ToolCall>;
  agentTree: AgentNode[];
  streamStatus: StreamStatus;
  pendingApproval: ApproveEvent | null;
  pendingRunId: string | null; // localStorage 镜像（刷新恢复用）
  providers: ProviderInfo[]; // 模型下拉数据源（GET /v1/providers）
  selectedModelId: number | null; // 用户选择；null = 默认模型
  agentMode: string; // 代理模式（2026-08-04 P1，随请求透传后端）

  send(text: string): Promise<void>;
  resume(runId: string): Promise<void>;
  approve(): Promise<void>;
  reject(note?: string): Promise<void>;
  cancel(): void;
  loadHistory(sessionId: string): Promise<void>;
  clearChat(): void;
  loadProviders(): Promise<void>;
  setSelectedModelId(modelId: number | null): void;
  setAgentMode(mode: string): void;
}

let abortRef: AbortController | null = null;
let subagentSeq = 0;

export const useChatStore = create<ChatState>((set, get) => {
  /** 追加系统提示（自动过期清除由组件处理） */
  const pushNotice = (notice: ChatNotice) =>
    set((s) => ({ notices: [...s.notices, notice] }));

  /** 开始一个流（send / resume 共用入口） */
  const startStream = (req: {
    session_id?: string | null;
    message?: string | null;
    resume_run_id?: string | null;
    model_id?: number | null;
    mode?: string;
  }) => {
    abortRef?.abort();
    const controller = new AbortController();
    abortRef = controller;

    set({ streamStatus: "connecting" });

    void streamChat(req, {
      onEvent: (event) => handleEvent(set, get, event),
      onHttpError: (status, body) => {
        pushNotice({
          kind: "error",
          text: `请求失败（HTTP ${status}）：${body.detail || body.error} [${body.code}]`,
        });
        set({ streamStatus: "idle" });
      },
      onNetworkError: (err) => {
        pushNotice({ kind: "error", text: `连接中断：${err.message}（可重试）` });
        set({ streamStatus: "idle" });
      },
      onEnd: () => {
        // done / error 事件已置 idle；这里兜底（网络正常读完但无 done）
        set((s) => (s.streamStatus === "idle" ? s : { streamStatus: "idle" }));
      },
    }, controller.signal);
  };

  return {
    sessionId: null,
    messages: [],
    notices: [],
    toolCalls: {},
    agentTree: [],
    streamStatus: "idle",
    pendingApproval: null,
    pendingRunId: localStorage.getItem(PENDING_RUN_KEY),
    providers: [],
    selectedModelId: null,
    agentMode: "default", // 代理模式（2026-08-04 P1，随请求透传后端）

    async send(text: string) {
      const trimmed = text.trim();
      if (!trimmed || get().streamStatus === "connecting" || get().streamStatus === "streaming") {
        return;
      }
      // 追加用户消息（id=null：未落库，done 后以后端为准）
      set((s) => ({
        messages: [
          ...s.messages,
          { id: null, session_id: s.sessionId ?? "", role: "user", content: trimmed, created_at: new Date().toISOString() },
        ],
        notices: s.streamStatus === "awaiting_approval" ? s.notices : s.notices,
        pendingApproval: null, // 发送新消息时清掉旧审批态
        pendingRunId: null,
      }));
      localStorage.removeItem(PENDING_RUN_KEY);

      let sessionId = get().sessionId;
      if (!sessionId) {
        try {
          const session = await api.createSession();
          sessionId = session.id;
          set({ sessionId });
        } catch (err) {
          pushNotice({
            kind: "error",
            text: `创建会话失败：${err instanceof Error ? err.message : String(err)}`,
          });
          return;
        }
      }
      startStream({
        session_id: sessionId,
        message: trimmed,
        model_id: get().selectedModelId, // null → 后端用默认模型
        mode: get().agentMode, // 代理模式（2026-08-04 P1）
      });
    },

    async loadProviders() {
      try {
        const data = await api.listProviders();
        const providers = data.providers;
        let selected = get().selectedModelId;
        if (selected === null) {
          // 初始选中：第一个厂商的默认模型（后端按 sort_order 返回，首厂商 = llm_provider）
          const first = providers[0];
          const def = first?.models.find((m) => m.is_default) ?? first?.models[0];
          selected = def?.id ?? null;
        }
        set({ providers, selectedModelId: selected });
      } catch {
        // 拉取失败静默降级：下拉不渲染，请求不带 model_id（后端用默认）
        set({ providers: [], selectedModelId: null });
      }
    },

    setAgentMode(mode: string) {
      set({ agentMode: mode });
    },

    setSelectedModelId(modelId: number | null) {
      set({ selectedModelId: modelId });
    },

    async resume(runId: string) {
      set({ pendingApproval: null, pendingRunId: null });
      localStorage.removeItem(PENDING_RUN_KEY);
      startStream({ resume_run_id: runId });
    },

    async approve() {
      const { pendingApproval, resume } = get();
      if (!pendingApproval) return;
      await submitApproval(pendingApproval, "approve", resume);
    },

    async reject(note?: string) {
      const { pendingApproval, resume } = get();
      if (!pendingApproval) return;
      await submitApproval(pendingApproval, "reject", resume, note);
    },

    cancel() {
      abortRef?.abort();
      set({ streamStatus: "idle" });
    },

    async loadHistory(sessionId: string) {
      abortRef?.abort();
      const all = await fetchAllMessages(sessionId);
      set({
        sessionId,
        messages: all,
        toolCalls: {},
        agentTree: [],
        streamStatus: "idle",
        pendingApproval: null,
      });
    },

    clearChat() {
      abortRef?.abort();
      set({
        sessionId: null,
        messages: [],
        notices: [],
        toolCalls: {},
        agentTree: [],
        streamStatus: "idle",
        pendingApproval: null,
        pendingRunId: null,
      });
      localStorage.removeItem(PENDING_RUN_KEY);
    },
  };
});

/** 拉全量消息（契约 cursor 分页，200/页循环到底；MVP 接受全量成本） */
async function fetchAllMessages(sessionId: string): Promise<Message[]> {
  const all: Message[] = [];
  let beforeId: number | undefined;
  for (let guard = 0; guard < 50; guard++) {
    const page = await api.listMessages(sessionId, { limit: 200, before_id: beforeId });
    all.unshift(...page.items);
    if (!page.has_more || page.next_before_id === null) break;
    beforeId = page.next_before_id;
  }
  return all;
}

/** done 后静默重拉：以库为准替换本地流；失败不打扰，保留现状 */
async function refreshMessages(
  sessionId: string,
  set: SetState,
  get: () => ChatState,
): Promise<void> {
  try {
    const all = await fetchAllMessages(sessionId);
    // 竞态保护：重拉期间用户可能已切换会话/清空，不覆盖新状态
    if (get().sessionId !== sessionId) return;
    set({ messages: all });
  } catch {
    // 静默降级（id=null 本地流仅刷新重进时冗余，MVP 接受）
  }
}

/** 审批提交（approve / reject 共用）：202 后 resume 恢复执行 */
async function submitApproval(
  approval: ApproveEvent,
  action: "approve" | "reject",
  resume: (runId: string) => Promise<void>,
  note?: string,
): Promise<void> {
  const pushNotice = (n: ChatNotice) =>
    useChatStore.setState((s) => ({ notices: [...s.notices, n] }));

  try {
    await api.approve({ run_id: approval.run_id, action, note: note ?? null });
    await resume(approval.run_id);
  } catch (err) {
    if (err instanceof ApiError) {
      // 契约 §7：RUN_NOT_FOUND / NOT_PENDING → 审批已失效，前端清理状态
      if (err.code === "RUN_NOT_FOUND" || err.code === "NOT_PENDING") {
        pushNotice({ kind: "info", text: "该审批已失效（可能已被处理），请重发消息。" });
        useChatStore.setState({ pendingApproval: null, pendingRunId: null, streamStatus: "idle" });
        localStorage.removeItem(PENDING_RUN_KEY);
        return;
      }
      pushNotice({ kind: "error", text: `审批提交失败：${err.detail} [${err.code}]` });
    } else {
      pushNotice({ kind: "error", text: `审批提交失败：${err instanceof Error ? err.message : String(err)}` });
    }
  }
}

/** SSE 事件 → store 状态（契约 §5.2 精确动作表） */
type SetState = StoreApi<ChatState>["setState"];
function handleEvent(
  set: SetState,
  get: () => ChatState,
  event: SSEEvent,
): void {
  switch (event.type) {
    case "start": {
      if (!event.resumed) {
        // 新 run：清空本轮面板缓冲（resume 保留挂起前节点）
        set({ toolCalls: {}, agentTree: [] });
        subagentSeq = 0;
      }
      set({
        sessionId: event.session_id,
        streamStatus: "streaming",
        pendingApproval: null,
      });
      break;
    }

    case "token": {
      const { messages } = get();
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant" && last.id === null) {
        set({
          messages: [...messages.slice(0, -1), { ...last, content: last.content + event.text }],
        });
      } else {
        set({
          messages: [
            ...messages,
            { id: null, session_id: get().sessionId ?? "", role: "assistant", content: event.text, created_at: new Date().toISOString() },
          ],
        });
      }
      break;
    }

    case "tool_call":
      upsertToolCall(set, get, event);
      break;

    case "subagent": {
      const tree = get().agentTree;
      if (event.status === "start") {
        set({ agentTree: [...tree, { key: `${event.name}-${++subagentSeq}`, name: event.name, status: "running" }] });
      } else {
        // end：匹配最后一个 running 同名节点
        const idx = [...tree].reverse().findIndex((n) => n.name === event.name && n.status === "running");
        if (idx >= 0) {
          const target = tree.length - 1 - idx;
          const updated = tree.map((n, i) =>
            i === target ? { ...n, status: "done" as const, summary: event.summary ?? null } : n,
          );
          set({ agentTree: updated });
        }
      }
      break;
    }

    case "approve": {
      set({ pendingApproval: event, streamStatus: "awaiting_approval", pendingRunId: event.run_id });
      localStorage.setItem(PENDING_RUN_KEY, event.run_id);
      break;
    }

    case "summarize": {
      set({
        notices: [
          ...get().notices,
          { kind: "info", text: `上下文已压缩：移除 ${event.removed_count} 条历史消息。${event.summary}` },
        ],
      });
      break;
    }

    case "done": {
      set({ streamStatus: "idle", pendingApproval: null, pendingRunId: null });
      localStorage.removeItem(PENDING_RUN_KEY);
      // 设计 §8.1 发现 4（P0）：流结束以库为准静默重拉，替换本地 id=null 流，
      // 避免刷新重进会话时重复渲染；失败静默降级保留本地流。
      const sid = get().sessionId;
      if (sid) void refreshMessages(sid, set, get);
      break;
    }

    case "error": {
      set({ streamStatus: "idle" });
      useChatStore.setState((s) => ({
        notices: [...s.notices, { kind: "error", text: `${event.detail} [${event.code}]${event.retryable ? "（可重试）" : ""}` }],
      }));
      break;
    }
  }
}

/** tool_call 幂等 upsert（契约 §5.3：同一 call_id running → success|error） */
function upsertToolCall(
  set: SetState,
  get: () => ChatState,
  event: ToolCallEvent,
): void {
  const calls = { ...get().toolCalls };
  const existing = calls[event.call_id];
  if (existing && existing.status === "success" && event.status === "running") {
    // 陈旧 running（resume 重放）不覆盖已完成状态
    return;
  }
  calls[event.call_id] = {
    call_id: event.call_id,
    name: event.name,
    arguments: event.arguments,
    status: event.status,
    result: event.result ?? null,
  };
  set({ toolCalls: calls });
}
