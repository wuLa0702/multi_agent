"""受控网页抓取工具（决策-沙箱网络隔离与受控抓取工具-v1 §3.1，2026-08-11）。

背景：评估 trace 定位模型在沙箱自写爬虫（curl/urllib）——工具集只有搜索
（发现）没有抓取（获取）。本工具补上受控内容获取：
- 服务端执行（后端进程 httpx 出网），沙箱只做计算
- 自动过 ToolAudit（抓了哪个 URL 有审计记录）
- HTML 清洗 + 截断（防上下文膨胀）；仅 http/https；无 JS 执行
"""

from __future__ import annotations

import re
from html import unescape

import httpx

from src.agent.middlewares.tool_audit import security_audit
from src.core.retry import retry_tool

# ── 抓取限制（决策 §3.1：安全 + 防膨胀）──
_FETCH_TIMEOUT_SECONDS = 10.0  # 兜底常量（settings.tool_timeout_seconds 优先，P1-d）
_MAX_BODY_CHARS = 8000  # 输出截断上限（防上下文膨胀）
_MAX_REDIRECTS = 5
_UA = "Mozilla/5.0 (compatible; multi-agent-fetch/1.0)"

# HTML 标签/脚本/样式清洗
_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>")
_WS_RE = re.compile(r"\s+")

# URL 注入校验（安全机制 D3）：纯 http/https + 无注入字符（空格/引号/分号/<>）
_SAFE_URL_RE = re.compile(r"^https?://[^\s\"'<>;]+$")


@security_audit(tool="fetch_url")
def _validate_url(url: str) -> str | None:
    """URL 严格校验（D3）：http/https + 无注入字符（security_audit 统一审计）。

    Args:
        url: 目标 URL

    Returns:
        None=合法；str=拦截原因（security_audit 自动记审计）
    """
    if not _SAFE_URL_RE.match(url):
        return "URL 注入/协议非法"
    return None


def clean_html(html: str, max_chars: int = _MAX_BODY_CHARS) -> str:
    """HTML → 纯文本（去 script/style/标签，压缩空白，截断）。

    Args:
        html: 原始 HTML
        max_chars: 输出截断上限

    Returns:
        清洗后的纯文本（≤ max_chars 字符）
    """
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


@retry_tool(retries=2, extra_exceptions=(httpx.HTTPStatusError,))
def fetch_url(url: str, max_chars: int = _MAX_BODY_CHARS) -> str:
    from src.core.config import settings  # 超时统一（P1-d）：settings.tool_timeout_seconds
    timeout = settings.tool_timeout_seconds
    """受控抓取网页正文（服务端执行，自动过工具审计）。

    Args:
        url: 目标 URL（仅 http/https）
        max_chars: 输出截断上限

    Returns:
        页面纯文本（截断）；失败返回错误提示字符串（工具降级不中断 run）

    Raises:
        ValueError: 非法 URL（非 http/https）

    P1 容错（2026-08-12 批次2.5 R-4）：网络瞬时故障（超时/连接/5xx）**上抛给
    @retry_tool 重试**（读操作幂等）——重试耗尽才降级；HTTP 4xx/非法 URL 就地降级。
    """
    if _validate_url(url) is not None:
        return f"链接格式非法（仅支持纯 http/https URL）：{url}"
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
            return f"抓取失败：HTTP {resp.status_code}（{url}）"  # 4xx 不可重试
        return clean_html(resp.text, max_chars=max_chars)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        raise  # 网络瞬时故障 → retry_tool 重试
    except Exception as exc:  # noqa: BLE001 - 其余网络异常统一降级提示
        return f"抓取失败（{type(exc).__name__}）：{url}"
