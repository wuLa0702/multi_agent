"""异常分级：可重试 / 不可重试 / 配置错误。

约定（旧项目 MCP 复盘经验）：统一异常体系 + 错误码分等级——
- 可重试（网络抖动、临时故障）→ 上层自动重试 N 次
- 不可重试（参数错、权限拒绝）→ 直接返回错误响应
- 配置错误 → 启动/调用时快速失败

v3 接入 Agent/MCP 时，把各层异常收敛到这里统一出口。
"""

from __future__ import annotations


class AppError(Exception):
    """应用异常基类（统一携带 message + code + retryable）。"""

    def __init__(self, message: str, code: str = "APP_ERROR", *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class RetryableError(AppError):
    """可重试异常：网络超时、连接抖动、临时故障。"""

    def __init__(self, message: str, code: str = "RETRYABLE") -> None:
        super().__init__(message, code, retryable=True)


class NonRetryableError(AppError):
    """不可重试异常：参数错误、权限拒绝、业务校验失败。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST") -> None:
        super().__init__(message, code, retryable=False)


class ConfigError(NonRetryableError):
    """配置缺失或非法（如 LLM API Key 未填、URL 格式错误）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFIG_ERROR")
