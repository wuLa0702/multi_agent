"""fetch_url 受控抓取工具单测（决策-沙箱网络隔离与受控抓取工具-v1 §3.1）。

覆盖：HTML 清洗 / 截断 / 协议校验 / 状态码 / 超时 / 异常降级（工具失败不中断 run）。
"""

from __future__ import annotations

import httpx
import pytest

from src.agent.tools.fetch_tool import clean_html, fetch_url


class TestCleanHtml:
    def test_strips_tags_and_scripts(self) -> None:
        """去 script/style/标签 + 解实体 + 压缩空白。"""
        html = "<html><script>var x=1;</script><style>a{}</style><p>Hello&nbsp; <b>World</b></p></html>"
        assert clean_html(html) == "Hello World"

    def test_truncates_long_text(self) -> None:
        """超长 → 截断（防上下文膨胀）。"""
        text = "x" * 10000
        assert len(clean_html(f"<p>{text}</p>", max_chars=100)) == 100

    def test_empty(self) -> None:
        assert clean_html("") == ""


class TestFetchUrl:
    def test_invalid_protocol(self) -> None:
        """非 http/https → 降级提示（不抛异常）。"""
        out = fetch_url("ftp://x.com")
        assert "仅支持 http/https" in out

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """200 + HTML → 清洗后文本（截断生效）。"""

        class FakeResp:
            status_code = 200
            text = "<html><p>DeepSeek 价格 <b>¥2/百万 token</b></p></html>"

        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())
        out = fetch_url("https://api.deepseek.com/pricing")
        assert "DeepSeek 价格" in out and "¥2/百万 token" in out

    def test_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4xx/5xx → 降级提示。"""

        class FakeResp:
            status_code = 404
            text = ""

        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())
        assert "HTTP 404" in fetch_url("https://x.com/missing")

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """超时 → 降级提示。"""

        def _raise(*a, **k):
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx, "get", _raise)
        assert "抓取超时" in fetch_url("https://slow.com")

    def test_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """其他异常 → 降级提示（工具失败不中断 run）。"""

        def _raise(*a, **k):
            raise ConnectionError("conn refused")

        monkeypatch.setattr(httpx, "get", _raise)
        assert "抓取失败" in fetch_url("https://x.com")


def test_fetch_url_registered() -> None:
    """注册表含 fetch_url（决策 #1：搜索发现 + 抓取获取 双工具）。"""
    from src.mcp.registry import get_tool

    assert callable(get_tool("fetch_url"))
