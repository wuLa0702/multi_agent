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

# ── 抓取限制（决策 §3.1：安全 + 防膨胀）──
_FETCH_TIMEOUT_SECONDS = 10.0
_MAX_BODY_CHARS = 8000  # 输出截断上限（防上下文膨胀）
_MAX_REDIRECTS = 5
_UA = "Mozilla/5.0 (compatible; multi-agent-fetch/1.0)"

# HTML 标签/脚本/样式清洗
_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>")
_WS_RE = re.compile(r"\s+")

# URL 注入校验（安全机制 D3）：纯 http/https + 无注入字符（空格/引号/分号/<>）
_SAFE_URL_RE = re.compile(r"^https?://[^\s\"'<>;]+$")


def _validate_url(url: str) -> bool:
    """URL 严格校验（D3）：http/https + 无注入字符。

    Args:
        url: 目标 URL

    Returns:
        True=合法
    """
    return bool(_SAFE_URL_RE.match(url))


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


def fetch_url(url: str, max_chars: int = _MAX_BODY_CHARS) -> str:
    """受控抓取网页正文（服务端执行，自动过工具审计）。

    Args:
        url: 目标 URL（仅 http/https）
        max_chars: 输出截断上限

    Returns:
        页面纯文本（截断）；失败返回错误提示字符串（工具降级不中断 run）

    Raises:
        ValueError: 非法 URL（非 http/https）
    """
    if not _validate_url(url):
        return f"链接格式非法（仅支持纯 http/https URL）：{url}"
    try:
        resp = httpx.get(
            url,
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            headers={"User-Agent": _UA},
        )
        if resp.status_code >= 400:
            return f"抓取失败：HTTP {resp.status_code}（{url}）"
        return clean_html(resp.text, max_chars=max_chars)
    except httpx.TimeoutException:
        return f"抓取超时（{_FETCH_TIMEOUT_SECONDS}s）：{url}"
    except Exception as exc:  # noqa: BLE001 - 网络异常多样，统一降级提示
        return f"抓取失败（{type(exc).__name__}）：{url}"
