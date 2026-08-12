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
