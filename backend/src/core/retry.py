"""工具调用重试（P1 容错：瞬时故障重试，重试耗尽降级返回）。

原则（06-structure-optimization §4 + 计划-容错处理 v1.2）：
- 只重试可重试异常（RetryableError / httpx 网络异常 / TimeoutError / 调用方 extra_exceptions）
- 业务/不可重试/系统异常不重试，直接降级
- 重试耗尽 → 返回错误提示字符串（与工具降级现状一致，不中断 run）
- 只用于**读操作幂等工具**（写操作重试有幂等风险，见 v1.2 评审——run_skill_script 排除）
- v1.1：自动检测 sync/async（asyncio.sleep 不阻塞事件循环）；内置 httpx 网络异常
- v1.2：去 ConnectTimeout/ReadTimeout 冗余（TimeoutException 父类捕获）
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from functools import wraps

import httpx

from src.core.errors import RetryableError

logger = logging.getLogger(__name__)

DEFAULT_RETRIES = 2
DEFAULT_DELAYS = (0.5, 1.0)  # 退避：0.5s / 1s

# 内置可重试网络异常（httpx 库抛的不会被 RetryableError 捕获）
_NETWORK_EXCEPTIONS = (
    httpx.TimeoutException,  # 含 ConnectTimeout/ReadTimeout（父类捕获子类，v1.2 去冗余）
    httpx.ConnectError,
    httpx.ReadError,
    TimeoutError,
)


def retry_tool(
    retries: int = DEFAULT_RETRIES,
    delays: tuple[float, ...] = DEFAULT_DELAYS,
    extra_exceptions: tuple[type[Exception], ...] = (),
) -> Callable:
    """工具函数重试装饰器（自动检测 sync/async，两种形态分别处理）。

    只应包裹**读操作幂等工具**（v1.2：写操作重试有幂等风险）。

    Args:
        retries: 最大重试次数
        delays: 每次重试的退避秒数
        extra_exceptions: 调用方额外指定的可重试异常类型（方案 C）

    Returns:
        包装后的工具函数（重试耗尽仍失败 → 降级错误字符串）
    """
    retryable = _NETWORK_EXCEPTIONS + extra_exceptions

    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exc: Exception | None = None
                for attempt in range(retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except (RetryableError, *retryable) as exc:
                        last_exc = exc
                        if attempt < retries:
                            delay = delays[min(attempt, len(delays) - 1)]
                            logger.info(
                                "工具 %s 重试 %d/%d（%s）",
                                func.__name__, attempt + 1, retries, type(exc).__name__,
                            )
                            await asyncio.sleep(delay)
                logger.error("工具 %s 重试耗尽：%s", func.__name__, last_exc)
                return f"工具调用失败（{type(last_exc).__name__}）：{last_exc}。请稍后重试。"

            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                last_exc: Exception | None = None
                for attempt in range(retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except (RetryableError, *retryable) as exc:
                        last_exc = exc
                        if attempt < retries:
                            delay = delays[min(attempt, len(delays) - 1)]
                            logger.info(
                                "工具 %s 重试 %d/%d（%s）",
                                func.__name__, attempt + 1, retries, type(exc).__name__,
                            )
                            time.sleep(delay)
                logger.error("工具 %s 重试耗尽：%s", func.__name__, last_exc)
                return f"工具调用失败（{type(last_exc).__name__}）：{last_exc}。请稍后重试。"

            return sync_wrapper

    return decorator
