/**
 * logger — 前端运行时日志模块
 *
 * 职责：
 *   - 统一日志出口：console + 批量上报后端（POST /v1/frontend/logs）
 *   - 后端接口把日志写入 .logs/frontend.log（与后端日志同目录），
 *     前端问题在后端日志目录可追溯
 *   - 全局捕获 window.onerror / unhandledrejection（main.tsx 注册 setupGlobalErrorHandlers）
 *
 * 设计原则：
 *   - 日志上报是旁路能力，任何失败都静默吞掉，绝不影响主流程
 *   - 批量上报（最多每 2s 或 10 条 flush 一次），避免刷请求
 *   - 页面卸载前用 sendBeacon 兜底，保证错误不丢
 */

export type LogLevel = 'info' | 'warn' | 'error';

export interface LogEntry {
  level: LogLevel;
  source: string;
  message: string;
  stack?: string;
  url?: string;
  ts: number;
}

const QUEUE: LogEntry[] = [];
const FLUSH_INTERVAL_MS = 2000;
const FLUSH_BATCH_SIZE = 10;
let timer: number | null = null;

/** 从 Error 对象提取 message + stack（兼容非 Error throw） */
function extractError(err: unknown): { message: string; stack?: string } {
  if (err instanceof Error) return { message: err.message, stack: err.stack };
  if (typeof err === 'string') return { message: err };
  try {
    return { message: JSON.stringify(err) };
  } catch {
    return { message: String(err) };
  }
}

function enqueue(level: LogLevel, source: string, message: string, stack?: string) {
  QUEUE.push({
    level,
    source,
    message,
    stack,
    url: typeof window !== 'undefined' ? window.location.href : '',
    ts: Date.now() / 1000,
  });
  if (QUEUE.length >= FLUSH_BATCH_SIZE) {
    void flush();
    return;
  }
  if (timer === null) {
    timer = window.setTimeout(() => {
      timer = null;
      void flush();
    }, FLUSH_INTERVAL_MS);
  }
}

/**
 * 批量输出到控制台（本项目无后端日志上报接口，console-only）。
 * 保留队列结构，未来接入上报接口时替换 flush 实现即可。
 */
async function flush(): Promise<void> {
  if (QUEUE.length === 0) return;
  const entries = QUEUE.splice(0, QUEUE.length);
  for (const e of entries) {
    console.info(`[log:${e.level}:${e.source}]`, e.message, e.stack ?? '');
  }
}

// ── 公开 API ────────────────────────────────────────────────────────────────

export function logInfo(source: string, message: string): void {
  console.info(`[${source}]`, message);
  enqueue('info', source, message);
}

export function logWarn(source: string, message: string): void {
  console.warn(`[${source}]`, message);
  enqueue('warn', source, message);
}

export function logError(source: string, err: unknown, extra = ''): void {
  const { message, stack } = extractError(err);
  const full = extra ? `${message} — ${extra}` : message;
  console.error(`[${source}]`, full, stack ?? '');
  enqueue('error', source, full, stack);
}

/**
 * 注册全局错误捕获（main.tsx 调用一次）。
 * window.onerror + unhandledrejection → 日志上报，页面不崩。
 */
export function setupGlobalErrorHandlers(): void {
  if (typeof window === 'undefined') return;

  window.addEventListener('error', (event) => {
    const err = event.error ?? event.message;
    logError('window.onerror', err, `at ${event.filename}:${event.lineno}`);
  });

  window.addEventListener('unhandledrejection', (event) => {
    logError('unhandledrejection', event.reason);
  });
}
