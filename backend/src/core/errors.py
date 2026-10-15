"""异常四分类：可重试 / 不可重试 / 业务 / 系统。

约定（06-structure-optimization §4 + 计划-容错处理 v1.2）：
统一异常体系 + category 分类，降级策略精准匹配异常类型——
- 可重试（网络抖动/超时/限流）→ 上层重试 N 次，仍失败降级
- 不可重试（参数错/权限拒绝/校验失败）→ 直接返回业务错误码，不重试
- 业务异常（业务规则不满足）→ 业务错误码 + 降级返回/默认兜底
- 系统异常（未知内部错误）→ 记 error 日志 + 按链路矩阵降级（不暴露细节）

边界判定口诀（v1.2）：输入问题→不可重试；规则限制→业务；瞬时故障→可重试；其它未知→系统。
`BusinessError` 与 `NonRetryableError` 区分：前者是业务规则约束（改了输入也不一定过），
后者是输入/权限本身非法（改对输入就过）。

兼容：`retryable` 属性保留（映射 category=="retryable"），旧代码引用不破。

另含**工具归一错误码** `ToolErrorCode`（阶段 2.1 新增）：工具层不抛异常，
以错误码随 `ToolResult` 返回，供审计 / SSE / 编排程序化消费。
"""

from __future__ import annotations


class AppError(Exception):
    """应用异常基类（统一携带 message + code + category）。"""

    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        *,
        category: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        # category 显式优先（语义：retryable 仅向后兼容）；都不传 → 默认 system
        if category is None:
            if retryable is not None:
                category = "retryable" if retryable else "non-retryable"
            else:
                category = "system"
        self.category = category
        self._retryable = category == "retryable"

    @property
    def retryable(self) -> bool:
        """兼容属性：是否可重试（category == "retryable"）。"""
        return self._retryable


class RetryableError(AppError):
    """可重试异常：网络超时、连接抖动、临时故障（瞬时故障重试，仍失败降级）。"""

    def __init__(self, message: str, code: str = "RETRYABLE") -> None:
        super().__init__(message, code, category="retryable")


class NonRetryableError(AppError):
    """不可重试异常：参数错误、权限拒绝、业务校验失败（改对输入就过，不重试）。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST") -> None:
        super().__init__(message, code, category="non-retryable")


class BusinessError(AppError):
    """业务异常：业务规则不满足（改了输入也不一定过，如次数用尽）→ 业务错误码 + 降级/默认兜底。"""

    def __init__(self, message: str, code: str = "BUSINESS") -> None:
        super().__init__(message, code, category="business")


class SystemError(AppError):
    """系统异常：未知内部错误 → 记 error 日志 + 按链路矩阵降级（不暴露内部细节）。"""

    def __init__(self, message: str, code: str = "INTERNAL") -> None:
        super().__init__(message, code, category="system")


class ConfigError(NonRetryableError):
    """配置缺失或非法（如 LLM API Key 未填、URL 格式错误）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFIG_ERROR")


class ToolErrorCode:
    """工具归一错误码（`设计-工具中心阶段2输出侧-v1.md` §3）。

    与上面的异常类**同源不同层**：异常类负责「抛」，本组错误码负责「装」——
    工具不抛异常，一律降级返回，错误语义经
    `tools/result.py::ToolResult.error_code` 传给下游（审计 / SSE / 编排）。

    用常量类而非 `enum.StrEnum`：`error_code` 声明为 `str`，而 StrEnum 成员的
    `__hash__` 取**成员名**（`TIMEOUT`）而非值（`timeout`），与裸字符串混用做
    `in frozenset(...)` 判定会静默失配。
    """

    NOT_CONFIGURED = "not_configured"
    INVALID_ARG = "invalid_arg"
    DENIED = "denied"
    UNPAID = "unpaid"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM_ERROR = "upstream_error"
    INTERNAL = "internal"


# 可重试错误码（对齐 06 §4：瞬时故障 → 重试 N 次，仍失败降级）
RETRYABLE_TOOL_ERRORS: frozenset[str] = frozenset({
    ToolErrorCode.TIMEOUT,
    ToolErrorCode.RATE_LIMITED,
    ToolErrorCode.UPSTREAM_ERROR,
})


def is_retryable_tool_error(error_code: str) -> bool:
    """判断工具错误码是否可重试（供填 `ToolResult.retryable`，免去逐工具手写映射）。

    Args:
        error_code: `ToolErrorCode` 中的取值

    Returns:
        可重试错误码 → `True`；未知码 → `False`（拿不准就不重试，宁可降级）
    """
    return error_code in RETRYABLE_TOOL_ERRORS
