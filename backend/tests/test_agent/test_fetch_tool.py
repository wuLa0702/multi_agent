"""fetch_url 受控抓取工具单测（决策-沙箱网络隔离与受控抓取工具-v1 §3.1）。

覆盖：HTML 清洗 / 截断 / 协议校验 / 状态码 / 超时 / 异常降级（工具失败不中断 run）
+ 阶段 2.2.2 输出信封（ok / **degraded（正文截断）** / error + 归一错误码）。
"""

from __future__ import annotations

import httpx
import pytest

from src.core.errors import ToolErrorCode
from src.tools.impl.fetch import _MAX_BODY_CHARS, clean_html, fetch_url


class TestCleanHtml:
    def test_strips_tags_and_scripts(self) -> None:
        """去 script/style/标签 + 解实体 + 压缩空白。"""
        html = "<html><script>var x=1;</script><style>a{}</style><p>Hello&nbsp; <b>World</b></p></html>"
        assert clean_html(html) == "Hello World"

    def test_truncates_long_text(self) -> None:
        """超长 → 截断（防上下文膨胀）。"""
        text = "x" * 10000
        assert len(clean_html(f"<p>{text}</p>", max_chars=100)) == 100

    def test_max_chars_none_means_no_truncation(self) -> None:
        """`max_chars=None` = 不截断——供调用方自行判定是否被截断（degraded 判定前提）。"""
        text = "x" * 10000
        assert len(clean_html(f"<p>{text}</p>", max_chars=None)) == 10000

    def test_empty(self) -> None:
        assert clean_html("") == ""


class _FakeResp:
    """假响应（httpx.get 的替身）。"""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.request = httpx.Request("GET", "https://x.com")


class TestFetchUrl:
    def test_invalid_protocol(self) -> None:
        """非 http/https → error: invalid_arg（不抛异常；安全机制 D3 注入校验消息）。"""
        result = fetch_url("ftp://x.com")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.INVALID_ARG
        assert result.retryable is False
        assert "链接格式非法" in result.message

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """200 + HTML → ok 信封（清洗后文本 + 结构化 data）。"""
        monkeypatch.setattr(
            httpx, "get",
            lambda *a, **k: _FakeResp(200, "<html><p>DeepSeek 价格 <b>¥2/百万 token</b></p></html>"),
        )
        result = fetch_url("https://api.deepseek.com/pricing")

        assert result.status == "ok"
        assert result.error_code == ""
        assert "DeepSeek 价格" in result.message and "¥2/百万 token" in result.message
        assert result.data is not None
        assert result.data["url"] == "https://api.deepseek.com/pricing"
        assert result.data["truncated"] is False

    def test_truncated_body_is_degraded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """正文超限被截断 → **degraded**（拿到了但不完整；本工具唯一需要该态的场景）。"""
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: _FakeResp(200, "<p>" + "x" * (_MAX_BODY_CHARS + 500) + "</p>")
        )
        result = fetch_url("https://x.com/huge")

        assert result.status == "degraded"
        assert result.data is not None
        assert result.data["truncated"] is True
        assert len(result.message) == _MAX_BODY_CHARS

    def test_http_404_is_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4xx → error + 按状态码归一（404 → not_found），且不重试。"""
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(404, ""))
        result = fetch_url("https://x.com/missing")

        assert result.status == "error"
        assert result.error_code == ToolErrorCode.NOT_FOUND
        assert "HTTP 404" in result.message

    def test_http_403_is_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """403 → error + denied。"""
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(403, ""))
        assert fetch_url("https://x.com/private").error_code == ToolErrorCode.DENIED

    def test_timeout_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """超时 → retry_tool 重试（P1 容错 R-4）→ 耗尽降级为**错误信封**。"""

        def _raise(*a, **k):
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx, "get", _raise)
        result = fetch_url("https://slow.com")

        assert result.status == "error"
        assert result.error_code == ToolErrorCode.TIMEOUT
        assert result.retryable is True, "超时属瞬时故障，性质上可重试"
        assert "工具调用失败" in result.message

    def test_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """其他异常 → error: internal（工具失败不中断 run）。"""

        def _raise(*a, **k):
            raise ConnectionError("conn refused")

        monkeypatch.setattr(httpx, "get", _raise)
        result = fetch_url("https://x.com")

        assert result.status == "error"
        assert result.error_code == ToolErrorCode.INTERNAL
        assert "抓取失败" in result.message


def test_fetch_url_registered() -> None:
    """注册表含 fetch_url（决策 #1：搜索发现 + 抓取获取 双工具）。"""
    from langchain_core.tools import BaseTool

    from src.tools.registry import get_tool

    tool = get_tool("fetch_url")
    assert isinstance(tool, BaseTool)
    assert tool.name == "fetch_url"


def test_mounted_tool_carries_degraded_in_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：截断经注册表挂载后，artifact 里如实带 degraded（程序侧唯一可见处）。"""
    from src.tools.registry import get_tool

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _FakeResp(200, "<p>" + "x" * (_MAX_BODY_CHARS + 1) + "</p>")
    )
    message = get_tool("fetch_url").invoke(
        {"name": "fetch_url", "args": {"url": "https://x.com"}, "id": "c1", "type": "tool_call"}
    )

    assert message.artifact["status"] == "degraded"
    assert message.artifact["data"]["truncated"] is True
    assert message.content.startswith("（部分结果）")
