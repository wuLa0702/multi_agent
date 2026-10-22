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
    """幂等门控（阶段 4 批次 3）：重试包装由注册表派生，`is_idempotent` 是唯一开关。

    改造前，重试参数写在 `impl/search.py` / `impl/fetch.py` 的 `@retry_tool`
    装饰器上，与登记表的 `is_idempotent` 互不相干（同一件事写两遍）——
    下面几条把"两边必须一致"从**巧合**变成**结构保证 + 快照**。
    """

    def test_derived_spec_wraps_retry(self) -> None:
        """派生结果：配了 retry 的被包装，没配的不被包装。"""
        from src.tools.registry import _IMPL_SPECS, _apply_retry

        # `_apply_retry` 的输出即"已包重试"的形态（输出适配在其后、更外层）；
        # retry_tool 用 functools.wraps → `__wrapped__` 是"被包装过"的判据
        assert hasattr(_apply_retry(_IMPL_SPECS["internet_search"]).fn, "__wrapped__")
        assert hasattr(_apply_retry(_IMPL_SPECS["fetch_url"]).fn, "__wrapped__")
        # run_skill_script 脚本含写操作（build_report.py 写文件）→ 不配重试
        assert not hasattr(
            _apply_retry(_IMPL_SPECS["run_skill_script"]).fn, "__wrapped__"
        )

    def test_retry_declaration_requires_idempotent(self) -> None:
        """不变量（硬）：配 retry ⟹ 声明 is_idempotent（写操作重试有幂等风险）。"""
        from src.tools.registry import _IMPL_SPECS

        for name, spec in _IMPL_SPECS.items():
            if spec.retry is not None:
                assert spec.is_idempotent, f"{name}：配了 retry 却未声明 is_idempotent"

    def test_retry_config_rejected_on_non_idempotent(self) -> None:
        """门控真会拦：非幂等工具配 retry → ValueError（fail fast，不静默忽略）。"""
        from dataclasses import replace

        from src.tools.registry import _IMPL_SPECS, RetryPolicy, _apply_retry

        bad = replace(_IMPL_SPECS["run_skill_script"], retry=RetryPolicy())
        with pytest.raises(ValueError, match="未声明 is_idempotent"):
            _apply_retry(bad)

    def test_idempotent_tools_snapshot(self) -> None:
        """快照：当前幂等工具集合（改动时此断言会红→强制人工确认）。

        2026-10-16 新增 3 个通用工具（calculate / current_time / json_extract）：
        均为**无副作用的本地计算 / 解析**，重复执行结果一致，故标幂等。
        注意——**幂等 ≠ 自动重试**：三者都没配 `retry`（本地计算重试无意义），
        `is_idempotent` 在这里只表示"可安全重复执行"。
        """
        from src.tools.registry import _IMPL_SPECS

        assert {n for n, s in _IMPL_SPECS.items() if s.is_idempotent} == {
            "internet_search",
            "fetch_url",
            "calculate",
            "current_time",
            "json_extract",
        }


class TestOnExhausted:
    """重试耗尽的可插拔降级（阶段 2.2.1）：降级属业务决定，由调用方注入。"""

    def test_default_returns_string(self) -> None:
        """不传 on_exhausted → 保持老行为（降级字符串），其他调用方零影响。"""

        def always_fail():
            raise httpx.ReadTimeout("timeout")

        out = retry_tool(retries=1, delays=(0,))(always_fail)()
        assert isinstance(out, str)
        assert "工具调用失败" in out

    def test_factory_gets_last_exception(self) -> None:
        """传入工厂 → 耗尽时调用它，并递上最后一个异常（供判错误码）。"""
        seen: dict[str, Exception] = {}

        def build(exc: Exception) -> dict:
            seen["exc"] = exc
            return {"code": type(exc).__name__}

        def always_fail():
            raise httpx.ReadTimeout("boom")

        out = retry_tool(retries=1, delays=(0,), on_exhausted=build)(always_fail)()
        assert out == {"code": "ReadTimeout"}
        assert isinstance(seen["exc"], httpx.ReadTimeout)

    def test_factory_not_called_on_success(self) -> None:
        """成功路径不碰工厂（只在耗尽时触发）。"""
        called = {"n": 0}

        def build(exc: Exception) -> str:
            called["n"] += 1
            return "degraded"

        assert retry_tool(on_exhausted=build)(lambda: "ok")() == "ok"
        assert called["n"] == 0

    async def test_async_branch_supports_factory(self) -> None:
        """async 分支同样支持 on_exhausted（sync/async 两条实现不能漏一条）。"""

        async def always_fail():
            raise httpx.ReadTimeout("timeout")

        wrapped = retry_tool(retries=1, delays=(0,), on_exhausted=lambda e: "degraded")(
            always_fail
        )
        assert await wrapped() == "degraded"
