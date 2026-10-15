"""工具统一输出信封：`ToolResult` 三态 + LLM 文本渲染。

设计依据：`docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md`。

**为什么要这层**：11 个工具此前一律返回裸 `str`，成功 / 降级 / 失败三种语义
混在同一根字符串里，下游（审计 / SSE / 编排）只能靠 `"失败" in text` 猜。

**双通道**（阶段 2 核心设计）：

| 消费者 | 通道 | 内容 |
|---|---|---|
| LLM | `ToolMessage.content` | `render(result)` 渲染的中文文本（不塞 JSON，避免 token 膨胀） |
| 程序（审计 / SSE / 编排） | `ToolMessage.artifact` | `result.data` + `status` + `error_code`（结构化） |

阶段 2.1 只落**契约**（本模块 + `core/errors.py` 的 `ToolErrorCode`），**零行为变更**——
尚无工具调用它；逐工具改造在 2.2，下游消费在 2.3。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.core.errors import is_retryable_tool_error
from src.tools.error_map import classify_exception

ToolStatus = Literal["ok", "degraded", "error"]


@dataclass(frozen=True)
class ToolResult:
    """工具统一输出信封（成功 / 降级 / 失败三态）。

    Attributes:
        status: `ok`=正常完成；`degraded`=部分可用（截断 / 兜底 / 降级路径）；
            `error`=失败，没有可用结果
        message: 人类可读中文（统一文案，经 `render()` 给 LLM 看）
        data: 结构化内容（`ok` / `degraded` 时），供审计、SSE 事件、编排消费
        error_code: 归一错误码（取值见 `core.errors.ToolErrorCode`）；`status="ok"` 时为空串
        retryable: 是否可重试——供编排层（阶段 4）决定重试 / 降级；
            取值应对齐 `core.errors.is_retryable_tool_error(error_code)`
        tool: 工具名（审计与事件定位用）

    Examples:
        >>> render(ToolResult(status="ok", message="已写入 wiki: a.md", tool="write_wiki"))
        '已写入 wiki: a.md'
        >>> render(ToolResult(status="error", message="链接格式非法", error_code="invalid_arg"))
        '失败原因：链接格式非法'
    """

    status: ToolStatus
    message: str
    data: dict[str, Any] | None = None
    error_code: str = ""
    retryable: bool = False
    tool: str = ""


def exhausted_result(exc: BaseException, *, tool: str) -> ToolResult:
    """重试耗尽 → 降级错误信封（供 `retry_tool(on_exhausted=...)` 注入）。

    文案与改造前逐字一致（不静默改）：
    `工具调用失败（{异常类名}）：{异常}。请稍后重试。`

    `retryable` 按错误**性质**填：耗尽是「这一轮试完了」，不代表故障性质变成
    永久——编排层换时机 / 换工具仍可能成功，故与 `is_retryable_tool_error`
    的映射保持一致，不另立口径。

    Args:
        exc: 重试耗尽时的最后一个异常
        tool: 工具名（审计与事件定位用）

    Returns:
        `error` 信封（错误码由 `error_map.classify_exception` 翻译）
    """
    error_code = classify_exception(exc)
    return ToolResult(
        status="error",
        message=f"工具调用失败（{type(exc).__name__}）：{exc}。请稍后重试。",
        error_code=error_code,
        retryable=is_retryable_tool_error(error_code),
        tool=tool,
    )


def render(result: ToolResult) -> str:
    """把 `ToolResult` 渲染成 LLM 可读文本（对齐 06 §6「中文 + 冒号分隔」）。

    Args:
        result: 工具输出信封

    Returns:
        `ok` 原样返回 `message`；`degraded` 加 `（部分结果）` 前缀（提示 LLM 不完整）；
        `error` 加 `失败原因：` 前缀（与 06 §6 文案规范一致）。
    """
    if result.status == "ok":
        return result.message
    if result.status == "degraded":
        return f"（部分结果）{result.message}"
    return f"失败原因：{result.message}"
