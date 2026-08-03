/**
 * REST 客户端 — 对齐契约 §4（会话/消息/健康检查/审批）。
 *
 * 统一约定：
 * - 非 2xx → 解析 ErrorResponse JSON → 抛 ApiError（携带 code/status）
 * - 业务调用方 catch ApiError 按 code 分支处理（见错误码表契约 §7）
 */

import type {
  ApproveRequest,
  DeleteResponse,
  ErrorResponse,
  HealthResponse,
  InstallRequest,
  InstalledSkill,
  InstalledSkillListResponse,
  MarketplaceListResponse,
  MessagePage,
  ProvidersResponse,
  Session,
  SessionListResponse,
  SessionUpdateRequest,
} from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail: string;

  constructor(status: number, body: ErrorResponse) {
    super(body.error || body.detail || "请求失败");
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.detail = body.detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let body: ErrorResponse = { error: "", detail: "请求失败", code: "HTTP_ERROR" };
    try {
      body = (await res.json()) as ErrorResponse;
    } catch {
      // 非 JSON body 用默认占位
    }
    throw new ApiError(res.status, body);
  }
  return (await res.json()) as T;
}

export const api = {
  /** GET /v1/health */
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/v1/health");
  },

  /** GET /v1/providers — 厂商 + 模型列表（模型下拉数据源） */
  listProviders(): Promise<ProvidersResponse> {
    return request<ProvidersResponse>("/v1/providers");
  },

  /** POST /v1/sessions — 创建会话（无 body） */
  createSession(): Promise<Session> {
    return request<Session>("/v1/sessions", { method: "POST" });
  },

  /** GET /v1/sessions — 会话列表（updated_at 倒序） */
  listSessions(): Promise<SessionListResponse> {
    return request<SessionListResponse>("/v1/sessions");
  },

  /** PATCH /v1/sessions/{id} — 修改标题 */
  updateSessionTitle(id: string, title: string): Promise<Session> {
    const body: SessionUpdateRequest = { title };
    return request<Session>(`/v1/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  /** DELETE /v1/sessions/{id} */
  deleteSession(id: string): Promise<DeleteResponse> {
    return request<DeleteResponse>(`/v1/sessions/${id}`, { method: "DELETE" });
  },

  /** GET /v1/sessions/{id}/messages — cursor 分页 */
  listMessages(
    sessionId: string,
    opts?: { limit?: number; before_id?: number },
  ): Promise<MessagePage> {
    const params = new URLSearchParams();
    if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts?.before_id !== undefined) params.set("before_id", String(opts.before_id));
    const qs = params.toString();
    return request<MessagePage>(
      `/v1/sessions/${sessionId}/messages${qs ? `?${qs}` : ""}`,
    );
  },

  /** POST /v1/chat/approve — 审批决策（202 即返，恢复走新 SSE 流） */
  approve(req: ApproveRequest): Promise<{ status: string; accepted: boolean }> {
    return request<{ status: string; accepted: boolean }>("/v1/chat/approve", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  /** GET /v1/skills/marketplace/list — 市场浏览 */
  listMarketSkills(params: {
    source?: string;
    query?: string;
    page?: number;
    page_size?: number;
    skill_type?: "mcp_server" | "skill_md";
  }): Promise<MarketplaceListResponse> {
    const p = new URLSearchParams();
    if (params.source) p.set("source", params.source);
    if (params.query) p.set("query", params.query);
    if (params.page) p.set("page", String(params.page));
    if (params.page_size) p.set("page_size", String(params.page_size));
    if (params.skill_type) p.set("skill_type", params.skill_type);
    return request<MarketplaceListResponse>(`/v1/skills/marketplace/list?${p}`);
  },

  /** POST /v1/skills/install — 一键安装 */
  installSkill(req: InstallRequest): Promise<InstalledSkill> {
    return request<InstalledSkill>("/v1/skills/install", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  /** GET /v1/skills/installed — 已安装列表 */
  listInstalledSkills(): Promise<InstalledSkillListResponse> {
    return request<InstalledSkillListResponse>("/v1/skills/installed");
  },

  /** PATCH /v1/skills/{id} — 启用/停用 */
  updateSkill(
    id: number,
    body: { is_active: boolean },
  ): Promise<InstalledSkill> {
    return request<InstalledSkill>(`/v1/skills/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  /** DELETE /v1/skills/{id} — 卸载 */
  deleteSkill(id: number): Promise<DeleteResponse> {
    return request<DeleteResponse>(`/v1/skills/${id}`, { method: "DELETE" });
  },
};
