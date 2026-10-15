"""受控网页抓取工具（决策-沙箱网络隔离与受控抓取工具-v1 §3.1，2026-08-11）。

背景：评估 trace 定位模型在沙箱自写爬虫（curl/urllib）——工具集只有搜索
（发现）没有抓取（获取）。本工具补上受控内容获取：
- 服务端执行（后端进程 httpx 出网），沙箱只做计算
- 自动过 ToolAudit（抓了哪个 URL 有审计记录）
- HTML 清洗 + 截断（防上下文膨胀）；仅 http/https；无 JS 执行

**输出（阶段 2.2.2）**：返回 `ToolResult` 信封。正文被截断 → `degraded`
（**本工具是唯一真正需要 `degraded` 的**：结果拿到了但不完整）。
"""

from __future__ import annotations

import re
from functools import partial
from html import unescape

import httpx

from src.core.errors import ToolErrorCode
from src.core.retry import retry_tool
from src.tools.error_map import classify_exception, code_for_http_status
from src.tools.result import ToolResult, exhausted_result
from src.tools.validators import validate_url

_TOOL_NAME = "fetch_url"

# ── 抓取限制（决策 §3.1：安全 + 防膨胀）──
_FETCH_TIMEOUT_SECONDS = 10.0  # 兜底常量（settings.tool_timeout_seconds 优先，P1-d）
_MAX_BODY_CHARS = 8000  # 输出截断上限（防上下文膨胀）
_MAX_REDIRECTS = 5
_UA = "Mozilla/5.0 (compatible; multi-agent-fetch/1.0)"

# HTML 标签/脚本/样式清洗
_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_html(html: str, max_chars: int | None = _MAX_BODY_CHARS) -> str:
    """HTML → 纯文本（去 script/style/标签，压缩空白，截断）。

    Args:
        html: 原始 HTML
        max_chars: 输出截断上限；`None` = **不截断**——供调用方自行判定
            是否被截断（`degraded` 态需要知道"切没切过"，切完再问就晚了）

    Returns:
        清洗后的纯文本（`max_chars=None` 时为全文）
    """
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text if max_chars is None else text[:max_chars]


@retry_tool(
    retries=2,
    extra_exceptions=(httpx.HTTPStatusError,),
    on_exhausted=partial(exhausted_result, tool=_TOOL_NAME),
)
def fetch_url(url: str, max_chars: int = _MAX_BODY_CHARS) -> ToolResult:
    """受控抓取网页正文（服务端执行，自动过工具审计）。

    Args:
        url: 目标 URL（仅 http/https）
        max_chars: 输出截断上限

    Returns:
        `ok` 信封（正文完整）/ `degraded` 信封（正文被截断）/ `error` 信封；
        失败不抛异常（工具降级不中断 run），`data` 带 `{url, text, truncated}`

    P1 容错（2026-08-12 批次2.5 R-4）：网络瞬时故障（超时/连接/5xx）**上抛给
    @retry_tool 重试**（读操作幂等）——重试耗尽才降级；HTTP 4xx/非法 URL 就地降级。
    """
    from src.core.config import settings  # 超时统一（P1-d）：settings.tool_timeout_seconds

    timeout = settings.tool_timeout_seconds
    if validate_url(url) is not None:
        return ToolResult(
            status="error",
            message=f"链接格式非法（仅支持纯 http/https URL）：{url}",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            headers={"User-Agent": _UA},
        )
        if resp.status_code >= 400:
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            # 4xx 不可重试 → 就地降级
            return ToolResult(
                status="error",
                message=f"抓取失败：HTTP {resp.status_code}（{url}）",
                error_code=code_for_http_status(resp.status_code),
                tool=_TOOL_NAME,
            )
        full_text = clean_html(resp.text, max_chars=None)
        truncated = len(full_text) > max_chars
        text = full_text[:max_chars]
        return ToolResult(
            status="degraded" if truncated else "ok",
            message=text,
            data={"url": url, "text": text, "truncated": truncated},
            tool=_TOOL_NAME,
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        raise  # 网络瞬时故障 → retry_tool 重试
    except Exception as exc:  # noqa: BLE001 - 其余网络异常统一降级提示
        return ToolResult(
            status="error",
            message=f"抓取失败（{type(exc).__name__}）：{url}",
            error_code=classify_exception(exc),
            tool=_TOOL_NAME,
        )
