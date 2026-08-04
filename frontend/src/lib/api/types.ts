/**
 * 前后端共享类型 — 对齐 docs/方案/方案-后端接口定义-v1.md（契约真相源）。
 *
 * 维护约定：字段名 snake_case、与后端 Pydantic 逐字段对齐，不设转换层。
 * 契约变更时：先改后端文档 → 再同步本文件（禁手改后端契约迁就前端）。
 */

// ── REST 实体 ────────────────────────────────────────────────────────────────

export interface Session {
  id: string;
  title: string;
  last_message: string | null; // 最后消息摘要（≤50 字，2026-08-04 P0）
  is_pinned: boolean; // 置顶（2026-08-04 P0）
  created_at: string; // ISO 8601 UTC
  updated_at: string;
}

export interface Message {
  id: number | null; // 未落库（流式中）为 null
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
}

export interface MessagePage {
  status: string;
  items: Message[];
  next_before_id: number | null;
  has_more: boolean;
}

export interface SessionListResponse {
  status: string;
  items: Session[];
  total: number;
}

export interface DeleteResponse {
  status: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  redis: "connected" | "disconnected";
  sqlite: "connected" | "disconnected";
  env: string;
}

// ── 模型配置（GET /v1/providers，二级选择数据源）─────────────────────────────

export interface ModelInfo {
  id: number; // DB 模型 ID，请求体 model_id 用
  provider_id: number;
  name: string; // 模型名（API 透传标识，如 deepseek-v4-flash）
  is_default: boolean; // 该厂商的默认模型
  is_active: boolean;
}

export interface ProviderInfo {
  id: number;
  slug: string; // 厂商标识（deepseek / ark / zhipu）
  name: string; // 厂商显示名（DeepSeek / 豆包 / 智谱）
  is_active: boolean;
  models: ModelInfo[];
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
}

// ── Skill Market（GET/POST /v1/skills/*，市场 + 已安装）───────────────────────

/** 市场条目（Smithery 归一化；mcp_server 带连接配置，skill_md 带 git_url） */
export interface SkillMarketItem {
  name: string;
  description: string;
  source: "smithery" | string;
  source_url: string;
  version: string;
  skill_type: "mcp_server" | "skill_md";
  use_count: number;
  verified: boolean;
  transport: string;
  url: string;
  command: string;
  args: string[];
  git_url: string;
}

/** 已安装 Skill 记录 */
export interface InstalledSkill {
  id: number;
  name: string;
  skill_type: "mcp_server" | "skill_md";
  source: string;
  source_url: string;
  version: string;
  install_path: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MarketplaceListResponse {
  source: string;
  items: SkillMarketItem[];
  total: number;
  page: number;
  has_more: boolean;
}

export interface InstalledSkillListResponse {
  items: InstalledSkill[];
  total: number;
}

// ── MCP 管理 + 系统配置（2026-08-04 P1，设置页去 mock）────────────────────────

/** MCP 连接配置（GET /v1/mcp-servers，不含鉴权 headers） */
export interface McpServerInfo {
  id: number;
  name: string;
  transport: string;
  url: string;
  is_active: boolean;
  source: string;
  version: string;
}

export interface McpServerListResponse {
  status: string;
  items: McpServerInfo[];
  total: number;
}

export interface SettingsResponse {
  status: string;
  settings: Record<string, string>;
}

/** 前端日志条目（POST /v1/frontend/logs） */
export interface FrontendLogEntry {
  level: string;
  source: string;
  message: string;
  stack?: string | null;
  url?: string | null;
  ts?: number | null;
}

/** POST /v1/skills/install 请求体（force=true 已安装也重新拉取覆盖 = 升级） */
export interface InstallRequest {
  source: string;
  source_url: string;
  name: string;
  skill_type: "mcp_server" | "skill_md";
  transport: string;
  url: string;
  command: string;
  args: string[];
  git_url: string;
  force?: boolean;
}

// ── 请求体 ───────────────────────────────────────────────────────────────────

/** POST /v1/chat/stream 请求体（message 与 resume_run_id 互斥） */
export interface ChatStreamRequest {
  session_id?: string | null;
  message?: string | null;
  resume_run_id?: string | null;
  model_id?: number | null; // DB 模型 ID（GET /v1/providers 查询）；null/缺省 = 默认模型
  mode?: string; // 代理模式（default/plan/agent/auto，2026-08-04 P1）
}

export interface ApproveRequest {
  run_id: string;
  action: "approve" | "reject";
  note?: string | null;
}

export interface SessionUpdateRequest {
  title: string;
}

// ── 错误 ─────────────────────────────────────────────────────────────────────

/** 统一错误响应（契约 §3.3） */
export interface ErrorResponse {
  error: string;
  detail: string;
  code: string;
}

// ── SSE 事件（契约 §5，8 类） ─────────────────────────────────────────────────

export type SSEEvent =
  | StartEvent
  | TokenEvent
  | ToolCallEvent
  | SubagentEvent
  | ApproveEvent
  | SummarizeEvent
  | DoneEvent
  | ErrorEvent;

export interface StartEvent {
  type: "start";
  run_id: string;
  session_id: string;
  resumed: boolean;
}

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface ToolCallEvent {
  type: "tool_call";
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "success" | "error";
  result?: string | null;
}

export interface SubagentEvent {
  type: "subagent";
  name: string;
  status: "start" | "end";
  summary?: string | null;
}

export interface ApproveEvent {
  type: "approve";
  run_id: string;
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  message: string;
}

export interface SummarizeEvent {
  type: "summarize";
  summary: string;
  removed_count: number;
  keep_from_message_id: number | null;
}

export interface DoneEvent {
  type: "done";
  run_id: string;
  session_id: string;
  duration_ms: number;
  context_used?: number | null; // 上下文累计用量（2026-08-04 P2）
  context_total?: number; // 上下文上限
}

export interface ErrorEvent {
  type: "error";
  code: string;
  detail: string;
  retryable: boolean;
}
