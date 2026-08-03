/**
 * sse.ts 单测 — 帧解析边界（半帧/粘包/CRLF/注释帧）+ streamChat 集成。
 * 对齐方案-前端设计-v1 §8.2 风险 1：解析器必须覆盖分片读取、多事件一 chunk、空行容错。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createSseParser, parseSseFrame, streamChat } from "@/lib/api/sse";
import type { SSEEvent } from "@/lib/api/types";

describe("parseSseFrame", () => {
  it("提取单 data 行", () => {
    expect(parseSseFrame('data: {"type":"token","text":"hi"}')).toBe(
      '{"type":"token","text":"hi"}',
    );
  });

  it("归一化 CRLF 行尾", () => {
    expect(parseSseFrame('data: {"type":"done"}\r\n\r\n'.slice(0, -2))).toBe(
      '{"type":"done"}',
    );
  });

  it("多 data 行按换行拼接（SSE 规范）", () => {
    expect(parseSseFrame("data: line1\ndata: line2")).toBe("line1\nline2");
  });

  it("data 前缀后的单空格被剥离", () => {
    expect(parseSseFrame("data: {\"type\":\"x\"}")).toBe('{"type":"x"}');
  });

  it("注释帧（冒号开头）与空帧返回 null", () => {
    expect(parseSseFrame(": keepalive")).toBeNull();
    expect(parseSseFrame("")).toBeNull();
  });
});

describe("createSseParser", () => {
  it("整帧一次到达", () => {
    const frames: string[] = [];
    const parser = createSseParser((d) => frames.push(d));
    parser('data: {"type":"a"}\n\n');
    expect(frames).toEqual(['{"type":"a"}']);
  });

  it("半帧分片（逐字符喂入）", () => {
    const frames: string[] = [];
    const parser = createSseParser((d) => frames.push(d));
    const raw = 'data: {"type":"token","text":"你好"}\n\n';
    for (const ch of raw) parser(ch);
    expect(frames).toHaveLength(1);
    expect(JSON.parse(frames[0]).text).toBe("你好");
  });

  it("粘包：一 chunk 多帧", () => {
    const frames: string[] = [];
    const parser = createSseParser((d) => frames.push(d));
    parser('data: {"type":"a"}\n\ndata: {"type":"b"}\n\n');
    expect(frames).toEqual(['{"type":"a"}', '{"type":"b"}']);
  });

  it("帧边界跨 chunk（帧尾 \n\n 被切开）", () => {
    const frames: string[] = [];
    const parser = createSseParser((d) => frames.push(d));
    parser('data: {"type":"a"}');
    parser("\n");
    parser("\ndata: {\"type\":\"b\"}\n");
    parser("\n");
    expect(frames).toEqual(['{"type":"a"}', '{"type":"b"}']);
  });

  it("忽略无 data 行的帧（注释 keepalive 不产出）", () => {
    const frames: string[] = [];
    const parser = createSseParser((d) => frames.push(d));
    parser(": ping\n\n");
    parser('data: {"type":"a"}\n\n');
    expect(frames).toEqual(['{"type":"a"}']);
  });
});

describe("streamChat", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function sseStream(chunks: string[]): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c));
        controller.close();
      },
    });
    return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  }

  it("正常流：事件按序回调 + onEnd", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      sseStream([
        'data: {"type":"start","run_id":"r1","session_id":"s1","resumed":false}\n\n',
        'data: {"type":"token","text":"你好"}\n',
        '\ndata: {"type":"done","run_id":"r1","session_id":"s1","duration_ms":10}\n\n',
      ]),
    ) as unknown as typeof fetch;

    const events: SSEEvent[] = [];
    let ended = false;
    await streamChat(
      { session_id: "s1", message: "hi" },
      {
        onEvent: (e) => events.push(e),
        onHttpError: () => fail("不应有 HTTP 错误"),
        onNetworkError: () => fail("不应有网络错误"),
        onEnd: () => {
          ended = true;
        },
      },
      new AbortController().signal,
    );

    expect(events.map((e) => e.type)).toEqual(["start", "token", "done"]);
    expect(ended).toBe(true);
  });

  it("非法 JSON 帧被跳过，不崩流", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      sseStream(['data: {broken\n\n', 'data: {"type":"token","text":"ok"}\n\n']),
    ) as unknown as typeof fetch;

    const events: SSEEvent[] = [];
    await streamChat(
      { session_id: "s1", message: "hi" },
      {
        onEvent: (e) => events.push(e),
        onHttpError: () => fail("不应有 HTTP 错误"),
        onNetworkError: () => fail("不应有网络错误"),
        onEnd: () => undefined,
      },
      new AbortController().signal,
    );
    expect(events.map((e) => e.type)).toEqual(["token"]);
  });

  it("HTTP 非 2xx → onHttpError 携带 ErrorResponse", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "互斥", detail: "message 与 resume_run_id 二选一", code: "BAD_REQUEST" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    let got: { status: number; code: string } | null = null;
    await streamChat(
      { session_id: "s1", message: "hi", resume_run_id: "r1" },
      {
        onEvent: () => undefined,
        onHttpError: (status, body) => {
          got = { status, code: body.code };
        },
        onNetworkError: () => fail("不应有网络错误"),
        onEnd: () => fail("HTTP 错误后不应 onEnd"),
      },
      new AbortController().signal,
    );
    expect(got).toEqual({ status: 400, code: "BAD_REQUEST" });
  });

  it("用户 abort → 不触发任何错误回调", async () => {
    const controller = new AbortController();
    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      // 立即 abort：模拟网络层被取消
      controller.abort();
      return Promise.reject(new DOMException("aborted", "AbortError"));
    }) as unknown as typeof fetch;

    let networkErrorCalled = false;
    await streamChat(
      { session_id: "s1", message: "hi" },
      {
        onEvent: () => undefined,
        onHttpError: () => undefined,
        onNetworkError: () => {
          networkErrorCalled = true;
        },
        onEnd: () => undefined,
      },
      controller.signal,
    );
    expect(networkErrorCalled).toBe(false);
  });

  it("请求体序列化正确（session_id + message）", async () => {
    let sentBody: string | null = null;
    globalThis.fetch = vi.fn().mockImplementation(async (_url, init) => {
      sentBody = init.body as string;
      return sseStream([]);
    }) as unknown as typeof fetch;

    await streamChat(
      { session_id: "s1", message: "你好", resume_run_id: null },
      {
        onEvent: () => undefined,
        onHttpError: () => undefined,
        onNetworkError: () => undefined,
        onEnd: () => undefined,
      },
      new AbortController().signal,
    );
    const parsed = JSON.parse(sentBody ?? "{}");
    expect(parsed).toEqual({ session_id: "s1", message: "你好", resume_run_id: null });
  });
});
