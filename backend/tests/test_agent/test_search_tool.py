"""internet_search 单测（阶段 2.2.1）：两态信封 + 引擎降级透明 + 重试。

补上原本缺失的直接单测（此前只有 MCP 角度间接调用）。
全部 mock，不联网、不触发 Searchpin 的模型下载。
"""

from __future__ import annotations

import httpx

from src.core.config import settings
from src.core.errors import ToolErrorCode
from src.tools.impl import search as search_mod
from src.tools.impl.search import internet_search


def _pages() -> list[dict]:
    """Searchpin 形态的结果页（name/url/summary）。"""
    return [
        {"name": "结果一", "url": "https://a.com", "summary": "摘要一"},
        {"name": "结果二", "url": "https://b.com", "summary": "摘要二"},
    ]


def _http_error(status: int) -> httpx.HTTPStatusError:
    """构造指定状态码的 httpx 异常。"""
    request = httpx.Request("POST", "https://api.bochaai.com/v1/web-search")
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=httpx.Response(status, request=request)
    )


def _patch_searchpin(monkeypatch, pages: list[dict] | None) -> None:
    """固定 Searchpin 结果（None = 不可用/无结果 → 触发降级）。"""
    monkeypatch.setattr(search_mod.searchpin_client, "search", lambda q, n=5: pages)


def _patch_bocha_key(monkeypatch, key: str = "dummy") -> None:
    monkeypatch.setattr(settings, "bocha_api_key", key)


class TestOkPaths:
    """有结果就是 ok（含走了降级引擎）——搜不到 ≠ 降级。"""

    def test_searchpin_hit(self, monkeypatch) -> None:
        """Searchpin 命中：ok + engine=searchpin + 未走降级。"""
        _patch_searchpin(monkeypatch, _pages())
        result = internet_search("测试查询")
        assert result.status == "ok"
        assert result.error_code == ""
        assert result.data is not None
        assert result.data["engine"] == "searchpin"
        assert result.data["fallback_used"] is False
        assert result.data["query"] == "测试查询"
        assert result.data["results"] == [
            {"title": "结果一", "url": "https://a.com", "snippet": "摘要一"},
            {"title": "结果二", "url": "https://b.com", "snippet": "摘要二"},
        ]
        assert "https://a.com" in result.message

    def test_bocha_fallback_is_still_ok(self, monkeypatch) -> None:
        """Searchpin 不可用 → 博查命中：仍是 ok，但 fallback_used=True（降级透明）。"""
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)
        monkeypatch.setattr(search_mod.bocha_client, "search", lambda q, n=5: _pages())
        result = internet_search("测试查询")
        assert result.status == "ok"
        assert result.data is not None
        assert result.data["engine"] == "bocha"
        assert result.data["fallback_used"] is True

    def test_no_hits_is_ok_not_error(self, monkeypatch) -> None:
        """两路都没命中：ok + 空 results（搜不到是正常结果，不是失败）。"""
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)
        monkeypatch.setattr(search_mod.bocha_client, "search", lambda q, n=5: [])
        result = internet_search("测试查询")
        assert result.status == "ok"
        assert result.error_code == ""
        assert result.data is not None
        assert result.data["results"] == []

    def test_max_results_limits_payload(self, monkeypatch) -> None:
        """max_results 同时约束文本与结构化载荷。"""
        _patch_searchpin(monkeypatch, _pages())
        result = internet_search("测试查询", max_results=1)
        assert result.data is not None
        assert len(result.data["results"]) == 1
        assert "https://b.com" not in result.message


class TestErrorPaths:
    """失败路径：错误码必须能被下游程序化消费。"""

    def test_missing_bocha_key(self, monkeypatch) -> None:
        """未配置 key → not_configured（不可重试：重试也不会变出密钥）。"""
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch, "")
        result = internet_search("测试查询")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.NOT_CONFIGURED
        assert result.retryable is False
        assert result.tool == "internet_search"

    def test_http_403_is_unpaid(self, monkeypatch) -> None:
        """403（配额耗尽/key 无效）→ unpaid，且不重试（就地降级）。"""
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)
        calls = {"n": 0}

        def raise_403(q, n=5):
            calls["n"] += 1
            raise _http_error(403)

        monkeypatch.setattr(search_mod.bocha_client, "search", raise_403)
        result = internet_search("测试查询")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.UNPAID
        assert result.retryable is False
        assert calls["n"] == 1, "403 不应触发重试"

    def test_unexpected_exception_is_internal(self, monkeypatch) -> None:
        """未识别异常 → internal（不猜，归未知内部错误）。"""
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)

        def raise_value_error(q, n=5):
            raise ValueError("响应结构变了")

        monkeypatch.setattr(search_mod.bocha_client, "search", raise_value_error)
        result = internet_search("测试查询")
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.INTERNAL
        assert "响应结构变了" in result.message


class TestRetry:
    """重试：瞬时故障重试，耗尽后降级为信封（不再是裸字符串）。"""

    def test_429_retries_then_recovers(self, monkeypatch) -> None:
        """首次 429 → 重试后成功（瞬时故障重试生效）。"""
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)
        calls = {"n": 0}

        def flaky(q, n=5):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(429)
            return _pages()

        monkeypatch.setattr(search_mod.bocha_client, "search", flaky)
        result = internet_search("测试查询")
        assert result.status == "ok"
        assert calls["n"] == 2

    def test_exhausted_returns_tool_result_not_str(self, monkeypatch) -> None:
        """重试耗尽 → **错误信封**（阶段 2 契约：不再是裸字符串）。

        回归锁：改造前此处返回 `str`，会被输出适配层取 `.status` 时
        AttributeError 打崩（自检发现的崩溃路径）。
        """
        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)
        calls = {"n": 0}

        def always_429(q, n=5):
            calls["n"] += 1
            raise _http_error(429)

        monkeypatch.setattr(search_mod.bocha_client, "search", always_429)
        result = internet_search("测试查询")

        assert isinstance(result, type(search_mod.ToolResult(status="ok", message="")))
        assert result.status == "error"
        assert result.error_code == ToolErrorCode.RATE_LIMITED
        assert result.retryable is True
        assert calls["n"] == 3, "1 次首发 + 2 次重试 = 3（内层 retries=2）"


class TestMountedTool:
    """经注册表挂载后：content 给 LLM、artifact 带引擎溯源（端到端）。"""

    def test_artifact_exposes_engine_and_fallback(self, monkeypatch) -> None:
        """走降级也要在 artifact 里如实标出（编排层据此才知道一直在用付费引擎）。"""
        from src.tools.registry import get_tool

        _patch_searchpin(monkeypatch, None)
        _patch_bocha_key(monkeypatch)
        monkeypatch.setattr(search_mod.bocha_client, "search", lambda q, n=5: _pages())

        message = get_tool("internet_search").invoke(
            {"name": "internet_search", "args": {"query": "测试查询"}, "id": "c1",
             "type": "tool_call"}
        )
        assert message.artifact["status"] == "ok"
        assert message.artifact["data"]["engine"] == "bocha"
        assert message.artifact["data"]["fallback_used"] is True
        assert "https://a.com" in message.content
