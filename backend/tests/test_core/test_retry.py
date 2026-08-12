"""core/retry.py 重试装饰器单测（计划-容错处理 v1.2，P1-b）。

覆盖：sync/async 双版本 / 只重试可重试异常 / 重试耗尽降级 / 非重试异常不重试 /
extra_exceptions / 幂等工具接入（注册表）。
"""

from __future__ import annotations

import asyncio
import httpx
import pytest

from src.core.errors import BusinessError, NonRetryableError, RetryableError
from src.core.retry import retry_tool


class TestRetryToolSync:
    """同步工具重试。"""

    def test_retries_retryable_then_success(self, caplog) -> None:
        """可重试异常 1 次后成功 → 重试命中，返回真实结果。"""
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RetryableError("瞬时故障")
            return "ok"

        wrapped = retry_tool(retries=2, delays=(0, 0))(flaky)
        assert wrapped() == "ok"
        assert calls["n"] == 2

    def test_retries_exhausted_returns_degraded(self) -> None:
        """重试耗尽 → 降级错误字符串（不抛异常，不中断 run）。"""
        def always_fail():
            raise RetryableError("持续故障")

        wrapped = retry_tool(retries=2, delays=(0, 0))(always_fail)
        out = wrapped()
        assert isinstance(out, str)
        assert "工具调用失败" in out
        assert "持续故障" in out

    def test_no_retry_for_business_error(self) -> None:
        """业务/不可重试异常不重试，且不吞异常——冒泡由上层精确处理（结构优化 §4 禁吞异常）。"""
        calls = {"n": 0}

        def biz_fail():
            calls["n"] += 1
            raise BusinessError("次数用尽")

        wrapped = retry_tool(retries=2, delays=(0, 0))(biz_fail)
        with pytest.raises(BusinessError):
            wrapped()
        assert calls["n"] == 1  # 不重试

    def test_catches_httpx_network_error(self) -> None:
        """httpx 网络异常被内置捕获并重试（v1.1：不依赖 RetryableError）。"""
        calls = {"n": 0}

        def conn_fail():
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("connect refused")
            return "ok"

        wrapped = retry_tool(retries=2, delays=(0, 0))(conn_fail)
        assert wrapped() == "ok"
        assert calls["n"] == 2

    def test_extra_exceptions(self) -> None:
        """调用方 extra_exceptions 指定的异常也重试（方案 C）。"""
        calls = {"n": 0}

        class MyTransient(Exception):
            pass

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise MyTransient("自定义瞬时")
            return "ok"

        wrapped = retry_tool(retries=2, delays=(0, 0), extra_exceptions=(MyTransient,))(flaky)
        assert wrapped() == "ok"
        assert calls["n"] == 2


class TestRetryToolAsync:
    """异步工具重试（v1.1：asyncio.sleep 不阻塞事件循环）。"""

    @pytest.mark.asyncio
    async def test_async_retries_then_success(self) -> None:
        """async 工具：瞬时失败重试后成功。"""
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RetryableError("瞬时故障")
            await asyncio.sleep(0)
            return "ok"

        wrapped = retry_tool(retries=2, delays=(0, 0))(flaky)
        assert await wrapped() == "ok"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_async_retries_exhausted_degraded(self) -> None:
        async def always_fail():
            raise httpx.ReadTimeout("timeout")

        wrapped = retry_tool(retries=1, delays=(0,))(always_fail)
        out = await wrapped()
        assert "工具调用失败" in out


class TestRegistryIntegration:
    """注册表接入：只包读操作幂等工具（v1.2：run_skill_script 排除）。"""

    def test_registry_retries_search_and_fetch(self) -> None:
        """internet_search / fetch_url 包重试；run_skill_script 不包（写操作幂等风险）。"""
        from src.mcp.registry import TOOL_REGISTRY

        search = TOOL_REGISTRY["internet_search"]
        fetch = TOOL_REGISTRY["fetch_url"]
        skill = TOOL_REGISTRY["run_skill_script"]
        # wraps 保留 __name__，用 __wrapped__ 判断是否被装饰器包装
        assert hasattr(search, "__wrapped__")  # 已包重试
        assert hasattr(fetch, "__wrapped__")  # 已包重试
        assert not hasattr(skill, "__wrapped__")  # 未包（写操作幂等风险）
