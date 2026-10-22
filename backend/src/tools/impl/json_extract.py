"""json_extract 工具：按路径从 JSON 取值 —— **模板工具（完整处理链）**。

> 📌 术语说明：这里的"完整处理链"**不是另一种代码类型**，只是比 `impl/calc.py`
> 多了几步（解析 / 归一 / 多级错误提示）。本仓库真正的「**handler**」在别处：
> HTTP handler 在 `api/`，MCP 端点 handler 在 `tools/channels/mcp_server.py`。

## 用在哪

搜索/抓取/API 返回的 JSON 动辄几千字符，直接塞进上下文会挤占预算。本工具让
Agent 只取需要的那一个字段（如 `results[0].title`），把上下文留给推理。

## 路径语法

- `a.b.c`：逐层取对象键
- `a[0].b`：方括号取数组下标（非负整数）
- 混合：`data.items[2].tags[0]`
- 空串：取**整个文档**

## 作为模板怎么读

本文件演示「**带完整处理链**」的工具：比 `impl/calc.py` 多两步，正好是
多数真实工具都需要的：

```
入参校验 → 执行 → 结果归一 → 三态信封
   ↓        ↓        ↓           ↓
 空/非法   解析     截断长值    ok / error + error_code
```

**三道防线**（缺任一条，LLM 都会拿到看不懂的报错）：
1. JSON 语法错 → 回**出错位置**，不是一句 "invalid json"
2. 路径走不通 → 回**当前层可用的键**（LLM 据此自我纠正，不用猜）
3. 结果过长 → 截断并置 `degraded`（提示"不完整"，而不是假装没事）
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import Field

from src.core.errors import ToolErrorCode
from src.tools.contract.result import ToolResult

_TOOL_NAME = "json_extract"

#: 回给 LLM 的结果文本上限（防单个字段把上下文挤爆）
_MAX_RESULT_CHARS = 2000

#: 路径走不通时，列多少个兄弟键做提示
_MAX_HINT_KEYS = 8

PathToken = str | int


def _parse_path(path: str) -> list[PathToken]:
    """路径文本 → token 列表（底层函数，按规范豁免）。

    Args:
        path: 形如 `a.b[0].c` 的路径

    Returns:
        token 列表，元素为键名（str）或下标（int）

    Raises:
        ValueError: 出现空段 / 方括号内不是非负整数
    """
    tokens: list[PathToken] = []
    for raw_segment in path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise ValueError("路径中出现空段（连续的点）")
        name, _, rest = segment.partition("[")
        if name:
            tokens.append(name)
        while rest:
            index_text, _, rest = rest.partition("]")
            index_text = index_text.strip()
            if not index_text.isdigit():
                raise ValueError("方括号内必须是非负整数下标")
            tokens.append(int(index_text))
            rest = rest.lstrip("[")
    return tokens


def _walk(document: Any, tokens: list[PathToken]) -> Any:
    """按 token 逐层取值（底层函数，按规范豁免）。

    Raises:
        LookupError: 键不存在 / 下标越界 / 类型对不上
    """
    current = document
    for depth, token in enumerate(tokens):
        if isinstance(token, int):
            if not isinstance(current, list):
                raise LookupError(f"第 {depth + 1} 段要用下标，但当前是 {type(current).__name__}")
            if token >= len(current):
                raise LookupError(f"下标 [{token}] 越界（当前数组长度 {len(current)}）")
            current = current[token]
        else:
            if not isinstance(current, dict):
                raise LookupError(f"第 {depth + 1} 段要取键 {token!r}，但当前是 {type(current).__name__}")
            if token not in current:
                raise LookupError(f"键 {token!r} 不存在{_hint_keys(current)}")
            current = current[token]
    return current


def _hint_keys(mapping: dict) -> str:
    """把当前层可用键拼成提示（底层函数，按规范豁免）。"""
    keys = list(mapping)[:_MAX_HINT_KEYS]
    if not keys:
        return "（该对象为空）"
    suffix = " …" if len(mapping) > _MAX_HINT_KEYS else ""
    return f"；可用键：{', '.join(map(str, keys))}{suffix}"


def json_extract(
    data: Annotated[
        str,
        Field(description="JSON 文本（对象或数组）；**必须是合法 JSON**，解析失败会返回出错位置"),
    ],
    path: Annotated[
        str,
        Field(
            description=(
                "取值路径，点号取键、方括号取下标（如 results[0].title）；"
                "**留空则返回整个文档**"
            )
        ),
    ] = "",
) -> ToolResult:
    """按路径从 JSON 文本取值。

    Args:
        data: JSON 文本
        path: 路径（空串 = 整个文档）

    Returns:
        `ok` 信封（`data` 带 value / path）；超长 → `degraded`；
        JSON 非法 / 路径非法 / 路径走不通 → `error` 信封（附纠正提示）
    """
    try:
        document = json.loads(data)
    except json.JSONDecodeError as exc:
        return ToolResult(
            status="error",
            message=f"解析失败：第 {exc.lineno} 行第 {exc.colno} 列 {exc.msg}",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )

    if path.strip():
        try:
            tokens = _parse_path(path)
        except ValueError as exc:
            return ToolResult(
                status="error",
                message=f"路径非法：{exc}",
                error_code=ToolErrorCode.INVALID_ARG,
                tool=_TOOL_NAME,
            )
        try:
            value = _walk(document, tokens)
        except LookupError as exc:
            return ToolResult(
                status="error",
                message=f"取值失败：{exc}",
                error_code=ToolErrorCode.NOT_FOUND,
                tool=_TOOL_NAME,
            )
    else:
        value = document

    text = json.dumps(value, ensure_ascii=False, default=str)
    truncated = len(text) > _MAX_RESULT_CHARS
    if truncated:
        text = text[:_MAX_RESULT_CHARS] + "…"
    return ToolResult(
        status="degraded" if truncated else "ok",
        message=text,
        data={"path": path, "value": value, "truncated": truncated},
        tool=_TOOL_NAME,
    )
