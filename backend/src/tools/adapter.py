"""输出适配层：`ToolResult` 信封 → langchain `BaseTool`（双通道落地）。

设计依据：`docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md` §4。

**职责单一**：把「返回 `ToolResult` 的普通函数」适配成**声明了
`response_format="content_and_artifact"` 的 langchain 工具**，让一个返回值
同时喂两个消费者、各走各的通道：

| 消费者 | 通道 | 内容 |
|---|---|---|
| LLM | `ToolMessage.content` | `render(result)` 的中文文本（不塞 JSON） |
| 程序（审计 / SSE / 编排） | `ToolMessage.artifact` | 结构化信封（`status` / `error_code` / `retryable` / `data`） |

**注意是两个通道、不是多份文档**：审计 / SSE / 编排是三个读者，读的是**同一个**
`artifact`，各取所需。`artifact` 的构造见 `artifact_of()`。

**为什么必须显式包在最外层**：`response_format` 默认值是 `"content"`，且**不会**
从返回类型注解推断（`langchain_core/tools/convert.py`）。不声明就直接返回信封，
结构化内容会被序列化成一整段文本塞进 `ToolMessage.content`、`artifact` 恒为 `None`
（2026-10-15 实测）：

| 返回值 | 不包（默认 `content`） | 包了（本模块） |
|---|---|---|
| `ToolResult(status="ok", message="出锅", data={"eggs": 3})` | `content="ToolResult(status='ok', message='出锅', data={'eggs': 3}, error_code='', retryable=False, tool='cook')"`；`artifact=None` | `content="出锅"`；`artifact={"eggs": 3}` |
| `("文本", {"eggs": 3})` | `content='["文本", {"eggs": 3}]'`；`artifact=None` | —（本模块只接受 `ToolResult`） |

要害是 `status` 退化成文本里的一个字段，下游无法程序化判断成功 / 降级 / 失败——
恰是阶段 2 要消灭的问题。

**为什么用 `functools.wraps`**：框架据函数签名与 docstring 推断 `args_schema`
（参数名 / 类型 / 默认值 / 描述）与 `description`。`wraps` 让 `__wrapped__` 指向
原函数，`inspect.signature` 随之穿透——签名与文档一字不改，避免出现
「`fetch_url` 描述为空」那类事故（阶段 1.3 首跑抓到的 bug）。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from langchain_core.tools import BaseTool, tool

from src.tools.result import ToolResult, render


def as_lc_tool(fn: Callable[..., ToolResult], *, name: str) -> BaseTool:
    """把 `-> ToolResult` 的函数适配为 langchain `content_and_artifact` 工具。

    Args:
        fn: 工具实现（返回 `ToolResult`）
        name: 暴露给 LLM 的工具名——须与 `TOOL_REGISTRY` 的键、HITL `interrupt_on`
            名单一致（审批按名匹配）

    Returns:
        声明了 `response_format="content_and_artifact"` 的 `BaseTool`；
        入参 schema 由 `fn` 的签名推断，`description` 取自 `fn` 的 docstring

    Raises:
        ValueError: `fn` 无 docstring（框架要求工具必须有描述，缺则 import 期即失败）
    """

    @wraps(fn)
    def _entry(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        """执行工具，把 `ToolResult` 拆成 `(content, artifact)` 双通道。"""
        result = fn(*args, **kwargs)
        return render(result), artifact_of(result)

    return tool(name, response_format="content_and_artifact")(_entry)


def artifact_of(result: ToolResult) -> dict[str, Any]:
    """信封 → `artifact`（给审计 / SSE / 编排的结构化旁路）。

    **为什么带上 status / error_code 而不是只放 data**：artifact 是程序侧
    唯一能看到三态的地方。`ToolMessage.status` 只有 `success` / `error`
    两级（`langchain_core` 语义），`ok` 与 `degraded` 都被压成 `success`——
    拿它顶替会丢掉「结果不完整」这个信号。

    Args:
        result: 工具输出信封

    Returns:
        含 `status` / `error_code` / `retryable` / `data` 四个键的 dict。
        `message` 与 `tool` **不重复携带**：前者已由 `render()` 进 `content`，
        后者即 `ToolMessage.name`。`data` 无内容时为 `None`（如实表达"无结构化载荷"）
    """
    return {
        "status": result.status,
        "error_code": result.error_code,
        "retryable": result.retryable,
        "data": result.data,
    }
