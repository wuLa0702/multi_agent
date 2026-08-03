/**
 * Mock 后端 — 前端自测用（对齐 docs/方案/方案-后端接口定义-v1.md 契约）。
 *
 * 用途：后端实现前，前端可独立联调（vite proxy /v1 → localhost:8000）。
 * 覆盖：健康检查 / 会话 CRUD / 消息分页 / SSE 流式对话（8 类事件）/ 审批。
 *
 * 启动：node scripts/mock-backend.mjs   （端口 8000）
 */

import http from "node:http";

const PORT = 8010;  // mock 专用端口（8000 可能被真实后端占用）
let sessionSeq = 0;
const sessions = new Map();

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

function now() {
  return new Date().toISOString();
}

function newSession() {
  const id = `mock-session-${++sessionSeq}`;
  const s = { id, title: "新会话", created_at: now(), updated_at: now() };
  sessions.set(id, s);
  return s;
}

/** SSE 事件帧（契约 §5.1 统一信封） */
function frame(event) {
  return `data: ${JSON.stringify(event)}\n\n`;
}

/** 模拟一次 Agent 执行：start → 工具 → 子 Agent → token → done */
function* agentFlow() {
  const runId = `mock-run-${Date.now()}`;
  const sessionId = "mock-session-1";
  yield frame({ type: "start", run_id: runId, session_id: sessionId, resumed: false });
  yield frame({ type: "tool_call", call_id: "c1", name: "search", arguments: { query: "多agent" }, status: "running" });
  yield frame({ type: "subagent", name: "analyst", status: "start" });
  yield frame({ type: "token", text: "正在分析" });
  yield frame({ type: "subagent", name: "analyst", status: "end", summary: "分析完成：方案可行" });
  yield frame({ type: "tool_call", call_id: "c1", name: "search", arguments: { query: "多agent" }, status: "success", result: "搜索结果摘要（mock）" });
  yield frame({ type: "token", text: "，结论：多 Agent 系统采用 deepagents 主线。" });
  yield frame({ type: "done", run_id: runId, session_id: sessionId, duration_ms: 1234 });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  // ── SSE 流式对话（核心） ────────────────────────────────────────────────
  if (path === "/v1/chat/stream" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const reqBody = JSON.parse(body || "{}");
      if (reqBody.message && reqBody.resume_run_id) {
        json(res, 400, { error: "互斥参数", detail: "message 与 resume_run_id 二选一", code: "BAD_REQUEST" });
        return;
      }
      res.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });
      const flow = agentFlow();
      const timer = setInterval(() => {
        const { value, done } = flow.next();
        if (done) {
          clearInterval(timer);
          res.end();
          return;
        }
        res.write(value);
      }, 150);
      res.on("close", () => clearInterval(timer)); // 客户端断开/响应结束时清理
    });
    return;
  }

  // ── 审批 ───────────────────────────────────────────────────────────────
  if (path === "/v1/chat/approve" && req.method === "POST") {
    res.writeHead(202, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", accepted: true }));
    return;
  }

  // ── 健康检查 ───────────────────────────────────────────────────────────
  if (path === "/v1/health") {
    json(res, 200, { status: "ok", redis: "connected", sqlite: "connected", env: "dev" });
    return;
  }

  // ── 会话 CRUD ──────────────────────────────────────────────────────────
  if (path === "/v1/sessions" && req.method === "GET") {
    json(res, 200, { status: "ok", items: [...sessions.values()], total: sessions.size });
    return;
  }
  if (path === "/v1/sessions" && req.method === "POST") {
    const s = newSession();
    json(res, 200, s);
    return;
  }
  const m = path.match(/^\/v1\/sessions\/([^/]+)$/);
  if (m) {
    const id = m[1];
    if (req.method === "PATCH") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const s = sessions.get(id);
        if (!s) {
          json(res, 404, { error: "会话不存在", detail: "SESSION_NOT_FOUND", code: "SESSION_NOT_FOUND" });
          return;
        }
        const { title } = JSON.parse(body || "{}");
        s.title = title;
        s.updated_at = now();
        json(res, 200, s);
      });
      return;
    }
    if (req.method === "DELETE") {
      sessions.delete(id);
      json(res, 200, { status: "ok" });
      return;
    }
    if (req.method === "GET") {
      json(res, 200, { status: "ok", items: [], next_before_id: null, has_more: false });
      return;
    }
  }

  json(res, 404, { error: "Not Found", detail: `mock 未实现：${req.method} ${path}`, code: "NOT_FOUND" });
});

server.listen(PORT, () => {
  console.log(`[mock-backend] listening on http://127.0.0.1:${PORT}`);
});
