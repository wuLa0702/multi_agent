/**
 * SSE 流式客户端 — 对齐契约 §5（POST /v1/chat/stream）。
 *
 * 设计决策（方案-前端设计-v1 §3.1）：
 * - 用 fetch + ReadableStream 而非原生 EventSource（EventSource 仅支持 GET，
 *   无法携带契约要求的 POST body：session_id / message / resume_run_id）
 * - SSE 帧解析手写（<30 行核心），学习项目讲得清，边界单测见 test/sse.test.ts
 * - 取消用 AbortController（用户取消 / 切会话）
 *
 * 错误分层（契约 §3.3 + §5.5）：
 * - HTTP 非 2xx（请求阶段错误）→ onHttpError（ErrorResponse JSON）
 * - 流内 error 事件（业务错误）→ onEvent（type: "error"）
 * - 网络中断（fetch reject，非 abort）→ onNetworkError
 */

import type {
  ChatStreamRequest,
  ErrorResponse,
  SSEEvent,
} from "./types";

export interface StreamCallbacks {
  /** 每条 SSE 事件（含流内 error 事件） */
  onEvent(event: SSEEvent): void;
  /** HTTP 非 2xx：请求阶段错误，body 为 ErrorResponse JSON */
  onHttpError(status: number, body: ErrorResponse): void;
  /** fetch 层网络异常（用户 abort 不算错误，不回调） */
  onNetworkError(err: Error): void;
  /** 正常流结束（读到流尾，done/error 事件之后） */
  onEnd(): void;
}

const DATA_PREFIX = "data:";

/** 单帧解析结果：null = 帧内无 data 行（注释/空帧，忽略） */
export function parseSseFrame(frame: string): string | null {
  // 归一化 \r\n → \n，按行取 data: 前缀（SSE 规范允许多 data 行 = 拼接）
  const lines = frame.replace(/\r\n/g, "\n").split("\n");
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith(DATA_PREFIX)) {
      dataLines.push(line.slice(DATA_PREFIX.length).replace(/^ /, ""));
    }
  }
  if (dataLines.length === 0) return null;
  return dataLines.join("\n");
}

/**
 * 流式帧解析器：吞入 chunk 文本，产出完整帧。
 * 边界处理：半帧（分片到达）、粘包（一 chunk 多帧）、空行容错。
 *
 * 帧分隔兼容 \n\n（LF）与 \r\n\r\n（CRLF）——SSE 规范允许两种行尾，
 * FastAPI StreamingResponse 实际输出 CRLF（2026-08-03 实测字节级确认）。
 */
export function createSseParser(
  onFrame: (data: string) => void,
): (chunk: string) => void {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk;
    let idx: number;
    // 一 chunk 可能含多帧（粘包），循环切完
    while ((idx = findFrameDelimiter(buffer)) >= 0) {
      const isCrlf = buffer.startsWith("\r\n\r\n", idx);
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + (isCrlf ? 4 : 2));
      const data = parseSseFrame(frame);
      if (data !== null) onFrame(data);
    }
  };
}

/**
 * 找帧分隔符位置（\n\n 或 \r\n\r\n，取最早出现）；无完整分隔符返回 -1。
 * CRLF 序列 \r\n\r\n 中不含连续 \n\n，两种搜索互不干扰。
 */
function findFrameDelimiter(buf: string): number {
  const lf = buf.indexOf("\n\n");
  const crlf = buf.indexOf("\r\n\r\n");
  if (lf < 0) return crlf;
  if (crlf < 0) return lf;
  return Math.min(lf, crlf);
}

/** 解析事件 JSON，非法帧返回 null（健壮性：不崩流，跳过坏帧） */
function parseEvent(raw: string): SSEEvent | null {
  try {
    const obj = JSON.parse(raw) as SSEEvent;
    if (typeof obj !== "object" || obj === null || typeof obj.type !== "string") {
      return null;
    }
    return obj;
  } catch {
    return null;
  }
}

/**
 * 发起一次流式对话（新消息或审批后 resume）。
 *
 * @param req 契约 ChatStreamRequest（message 与 resume_run_id 互斥）
 * @param cb 事件回调
 * @param signal 取消句柄（abort → 静默停止，不触发 onNetworkError）
 */
export async function streamChat(
  req: ChatStreamRequest,
  cb: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      signal,
    });
  } catch (err) {
    if (!signal.aborted) cb.onNetworkError(err instanceof Error ? err : new Error(String(err)));
    return;
  }

  // 契约 §3.3：请求阶段错误走 HTTP 状态码 + ErrorResponse JSON（不走 SSE）
  if (!res.ok) {
    let body: ErrorResponse = { error: "", detail: "请求失败", code: "HTTP_ERROR" };
    try {
      body = (await res.json()) as ErrorResponse;
    } catch {
      // body 非 JSON 时用默认占位
    }
    cb.onHttpError(res.status, body);
    return;
  }
  if (!res.body) {
    cb.onNetworkError(new Error("响应无 body（SSE 流不可用）"));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const pushFrame = (data: string) => {
    const event = parseEvent(data);
    if (event !== null) cb.onEvent(event);
  };
  const parser = createSseParser(pushFrame);

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser(decoder.decode(value, { stream: true }));
    }
    parser(decoder.decode()); // 冲刷解码器残留
    cb.onEnd();
  } catch (err) {
    if (!signal.aborted) cb.onNetworkError(err instanceof Error ? err : new Error(String(err)));
  }
}
