"""异常 → 归一错误码翻译单测（阶段 2.2.1）。

契约见 `docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md` §3。
"""

from __future__ import annotations

import httpx
import pytest

from src.core.errors import RetryableError, ToolErrorCode
from src.tools.contract.error_map import classify_exception, code_for_http_status


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=httpx.Response(status, request=request)
    )


class TestCodeForHttpStatus:
    """HTTP 状态码映射。"""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, ToolErrorCode.DENIED),
            (402, ToolErrorCode.UNPAID),
            (403, ToolErrorCode.DENIED),
            (404, ToolErrorCode.NOT_FOUND),
            (429, ToolErrorCode.RATE_LIMITED),
            (400, ToolErrorCode.INVALID_ARG),
            (422, ToolErrorCode.INVALID_ARG),
            (500, ToolErrorCode.UPSTREAM_ERROR),
            (502, ToolErrorCode.UPSTREAM_ERROR),
            (503, ToolErrorCode.UPSTREAM_ERROR),
        ],
    )
    def test_mapping(self, status: int, expected: str) -> None:
        assert code_for_http_status(status) == expected

    def test_all_mapped_codes_are_declared(self) -> None:
        """不变量：映射结果必须是 ToolErrorCode 里登记过的码（防拼写漂移）。"""
        declared = {v for k, v in vars(ToolErrorCode).items() if not k.startswith("_")}
        for status in (400, 401, 402, 403, 404, 429, 500, 502):
            assert code_for_http_status(status) in declared


class TestClassifyException:
    """异常类型映射。"""

    def test_timeout(self) -> None:
        assert classify_exception(httpx.ReadTimeout("t")) == ToolErrorCode.TIMEOUT
        assert classify_exception(TimeoutError("t")) == ToolErrorCode.TIMEOUT

    def test_connection_errors(self) -> None:
        assert classify_exception(httpx.ConnectError("c")) == ToolErrorCode.UPSTREAM_ERROR
        assert classify_exception(httpx.ReadError("r")) == ToolErrorCode.UPSTREAM_ERROR

    def test_http_status_takes_priority(self) -> None:
        """HTTPStatusError 先判状态码，不被上游故障兜底吞掉。"""
        assert classify_exception(_status_error(404)) == ToolErrorCode.NOT_FOUND
        assert classify_exception(_status_error(429)) == ToolErrorCode.RATE_LIMITED

    def test_project_retryable_error(self) -> None:
        """项目自定义的瞬时故障标记 → 上游故障（可重试）。"""
        assert classify_exception(RetryableError("抖动")) == ToolErrorCode.UPSTREAM_ERROR

    def test_unknown_is_internal(self) -> None:
        """未识别一律 internal（不猜）。"""
        assert classify_exception(ValueError("x")) == ToolErrorCode.INTERNAL
        assert classify_exception(RuntimeError("x")) == ToolErrorCode.INTERNAL
        assert classify_exception(None) == ToolErrorCode.INTERNAL

    def test_result_is_always_declared(self) -> None:
        """不变量：任何输入都不能产出未登记的码。"""
        declared = {v for k, v in vars(ToolErrorCode).items() if not k.startswith("_")}
        samples = [
            _status_error(400), _status_error(500), httpx.ReadTimeout("t"),
            httpx.ConnectError("c"), RetryableError("r"), ValueError("v"), None,
        ]
        assert all(classify_exception(s) in declared for s in samples)
