"""输出适配层：`ToolResult` 信封 → langchain `BaseTool`（双通道落地）。

设计依据：`docs/决策/2026-10-14-设计-工具中心阶段2输出侧-v1.md` §4。

**职责单一**：把「返回 `ToolResult` 的普通函数」适配成**声明了
`response_format="content_and_artifact"` 的 langchain 工具**，让一个返回值
同时喂两个消费者、各走各的通道：

| 消费者 | 通道 | 内容 |
|---|---|---|
| LLM | `ToolMessage.content` | `render(result)` 的中文文本（不塞 JSON） |
| 程序（审计 / SSE / 编排） | `ToolMessage.artifact` | `result.data`（结构化旁路） |

**为什么必须显式包在最外层**：`response_format` 默认值是 `"content"`，**不会**
从返回类型注解推断（`langchain_core/tools/convert.py`）。若函数直接返回
`(content, artifact)` 元组而不声明 `content_and_artifact`，元组会被当成 content
`_stringify` 成 `"('文本', {...})"` 塞给 LLM。所以这一步不能省。

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
        return render(result), (result.data or {})

    return tool(name, response_format="content_and_artifact")(_entry)
