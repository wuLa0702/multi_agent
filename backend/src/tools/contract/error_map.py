"""异常 / HTTP 状态码 → 工具归一错误码（`ToolResult.error_code` 的唯一翻译处）。

**为什么单独一层**：`ToolErrorCode` 是输出契约（`core/errors.py`），但
「哪种异常对应哪个码」若散到各工具里写 if/elif，11 个工具就是 11 套口径、
必然漂移（阶段 0 的「两处清单漂移」是同类教训）。集中一处翻译，
工具只说「这个异常 → 你帮我判码」。

分层：本模块属能力层（`tools/`），依赖底座 `core/errors.py` 的常量，
方向正确（上层 → 底座）。
"""

from __future__ import annotations

import httpx

from src.core.errors import RetryableError, ToolErrorCode

# HTTP 状态码 → 归一错误码（未列出的 4xx 归 invalid_arg，≥500 归 upstream_error）
_HTTP_STATUS_MAP: dict[int, str] = {
    401: ToolErrorCode.DENIED,
    402: ToolErrorCode.UNPAID,
    403: ToolErrorCode.DENIED,
    404: ToolErrorCode.NOT_FOUND,
    429: ToolErrorCode.RATE_LIMITED,
}


def code_for_http_status(status: int) -> str:
    """HTTP 状态码 → 归一错误码。

    Args:
        status: HTTP 响应状态码

    Returns:
        映射表命中的码；4xx 未列出归 `invalid_arg`；≥500 归 `upstream_error`
    """
    if status in _HTTP_STATUS_MAP:
        return _HTTP_STATUS_MAP[status]
    if status >= 500:
        return ToolErrorCode.UPSTREAM_ERROR
    return ToolErrorCode.INVALID_ARG


def classify_exception(exc: BaseException) -> str:
    """异常 → 归一错误码（未识别一律 `internal`，不猜）。

    Args:
        exc: 捕获到的异常（含 `None` 兜底：重试耗尽时理论不会为 None，
            但若发生则归 `internal`，不让类型错误掩盖真实故障）

    Returns:
        `ToolErrorCode` 中的取值

    Note:
        判定顺序要紧——`HTTPStatusError` 与超时/连接异常互不继承，
        但都属 `httpx.HTTPError`；先判具体类型再落 `internal` 兜底。
    """
    if exc is None:
        return ToolErrorCode.INTERNAL
    if isinstance(exc, httpx.HTTPStatusError):
        return code_for_http_status(exc.response.status_code)
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return ToolErrorCode.TIMEOUT
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError)):
        return ToolErrorCode.UPSTREAM_ERROR
    if isinstance(exc, RetryableError):
        # 项目自定义的「瞬时故障」标记，未细分类别 → 归上游故障（可重试）
        return ToolErrorCode.UPSTREAM_ERROR
    return ToolErrorCode.INTERNAL
