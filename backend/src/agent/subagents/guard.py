"""子代理容错包装层（面试描述点-容错：重试 + 错误摘要回传主 Agent）。

子代理是独立编译的子图，可能失败：LLM 超时 / 网络抖动 / 递归超限 / 未知异常。
不接任何处理时：异常冒泡到 langgraph ToolNode，被转成 error ToolMessage 回传
主 Agent（框架默认兜底）——主 Agent 是 LLM，看到错误自行决定下一步。

本包装层（GuardedSubAgent）在子代理这一层接管，形成两层兜底：
1. 可重试异常（超时/网络瞬时故障）→ 自动重试 N 次（退避，成本护栏）
2. 仍失败 / 不可重试异常 → 返回"已重试 N 次"的错误摘要作为子代理输出回传
   主 Agent——不中断 run，主 Agent 拿到摘要自行决定重试或降级

设计：docs/决策/2026-08-11-计划-容错处理-v1.md §3.3（子代理行：错误摘要回传）
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig

logger = logging.getLogger(__name__)

SUBAGENT_RETRIES = 1
SUBAGENT_RETRY_DELAY = 0.5

# 可重试异常（对齐 core/retry.py _NETWORK_EXCEPTIONS）：超时/网络瞬时故障
_SUBAGENT_RETRYABLE: tuple[type[Exception], ...] = (
    TimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
)


def guard_subagent(runnable: Runnable, name: str) -> GuardedSubAgent:
    """给子代理 runnable 挂容错包装（幂等：已包装的不重复包）。

    Args:
        runnable: 子代理编译后的 runnable（create_deep_agent 产物）
        name: 子代理名（日志 / 错误摘要定位）

    Returns:
        包装后的 GuardedSubAgent
    """
    if isinstance(runnable, GuardedSubAgent):
        return runnable
    return GuardedSubAgent(runnable, name)


class GuardedSubAgent(Runnable):
    """子代理容错包装：可重试异常自动重试 + 最终失败错误摘要回传。

    输出契约（deepagents CompiledSubAgent）：返回 state dict，必须含
    messages 键——成功时原样透传；失败时构造 [AIMessage(错误摘要)] 作为
    子代理最终回复（主 Agent 经 ToolMessage 看到）。
    """

    def __init__(self, runnable: Runnable, name: str) -> None:
        self._runnable = runnable
        self._name = name
        super().__init__()

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        """同步执行：重试可重试异常，最终失败返回错误摘要 state。"""
        last_exc: Exception | None = None
        retried = 0
        for attempt in range(SUBAGENT_RETRIES + 1):
            try:
                return self._runnable.invoke(input, config)
            except Exception as exc:  # noqa: BLE001 —— 容错层统一接管，不冒泡中断 run
                last_exc = exc
                if not _is_retryable(exc) or attempt >= SUBAGENT_RETRIES:
                    break
                retried += 1
                _log_retry(self._name, retried, exc)
                time.sleep(SUBAGENT_RETRY_DELAY)
        return _error_state(self._name, last_exc, retried)

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        """异步执行：重试可重试异常（asyncio.sleep 不阻塞事件循环），失败返回错误摘要。"""
        last_exc: Exception | None = None
        retried = 0
        for attempt in range(SUBAGENT_RETRIES + 1):
            try:
                return await self._runnable.ainvoke(input, config)
            except Exception as exc:  # noqa: BLE001 —— 容错层统一接管，不冒泡中断 run
                last_exc = exc
                if not _is_retryable(exc) or attempt >= SUBAGENT_RETRIES:
                    break
                retried += 1
                _log_retry(self._name, retried, exc)
                await asyncio.sleep(SUBAGENT_RETRY_DELAY)
        return _error_state(self._name, last_exc, retried)


def _is_retryable(exc: Exception) -> bool:
    """是否为可重试异常（超时/网络瞬时故障）。"""
    return isinstance(exc, _SUBAGENT_RETRYABLE)


def _log_retry(name: str, attempt: int, exc: Exception) -> None:
    """重试日志（对齐容错计划 §4.3 采集口径：grep "重试" 统计命中）。"""
    logger.info(
        "子代理 %s 重试 %d/%d（%s）",
        name, attempt, SUBAGENT_RETRIES, type(exc).__name__,
    )


def _error_state(name: str, exc: Exception | None, retried: int) -> dict[str, list[AIMessage]]:
    """构造错误摘要 state（子代理最终回复 = 主 Agent 看到的 ToolMessage 内容）。"""
    exc_type = type(exc).__name__ if exc else "UnknownError"
    message = str(exc) if exc else "未知错误"
    logger.error(
        "子代理 %s 执行失败（%s）：%s（已重试 %d 次）",
        name, exc_type, message, retried,
    )
    summary = (
        f"子代理 {name} 执行失败（{exc_type}）：{message}。"
        f"已重试 {retried} 次，请换一种方式或基于已有信息回答，不要重试。"
    )
    return {"messages": [AIMessage(content=summary)]}
