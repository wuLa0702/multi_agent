"""calculate 工具：安全算术求值 —— **模板工具（function call 形态）**。

## 为什么需要它

LLM 的算术不可靠：大数乘除、浮点累加、括号优先级经常出错。给它一个**确定性**
计算器，比让它"心算"可信得多；也让 Agent 少一轮自我怀疑。

## 为什么不直接用 `eval`

`eval("__import__('os').system('...')")` 会执行任意代码。本工具用 `ast`
**白名单**解析：只允许数字字面量、`+ - * / // % **` 二元运算、正负号一元运算，
其余节点（属性访问 / 函数调用 / 下标 / 字符串…）一律拒绝。

## 防护

- 指数绝对值上限 `_MAX_EXPONENT`（防 `9**9**9` 把进程算死）
- 除零 / 语法错 / 非实数结果（如负数开方）→ `error` 信封，**不抛异常**

## 作为模板怎么读

本文件是"纯函数工具"的**最小完整形态**，四个要点缺一不可：

1. **参数注解**——`Annotated[..., Field(description=...)]`：LLM 靠它理解入参
   （`tools/contract/adapter.py` 经签名推断 `args_schema`）
2. **入参校验**——非法输入返回 `error` 信封，**不抛异常**（抛错会中断整个 run）
3. **结构化出参**——`ToolResult`（`status` / `message` / `data` / `error_code`）
4. **登记**——在 `tools/registry.py::_IMPL_SPECS` 加一行（唯一真相源）
"""

from __future__ import annotations

import ast
import operator
from typing import Annotated

from pydantic import Field

from src.core.errors import ToolErrorCode
from src.tools.contract.result import ToolResult

_TOOL_NAME = "calculate"

#: 指数绝对值上限（防 9**9**9 这类把进程算死）
_MAX_EXPONENT = 100


def _pow(base: float, exponent: float) -> float:
    """带指数上限的幂运算（底层函数，按规范豁免）。"""
    if abs(exponent) > _MAX_EXPONENT:
        raise ValueError(f"指数绝对值不得超过 {_MAX_EXPONENT}")
    return base**exponent


#: 允许的二元运算符（白名单）
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _pow,
}

#: 允许的一元运算符（白名单）
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _evaluate(node: ast.AST) -> float:
    """递归求值（底层函数，按规范豁免）——只认白名单节点。

    Args:
        node: AST 节点

    Returns:
        数值结果

    Raises:
        ValueError: 出现白名单外的节点 / 运算符
    """
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("只支持数字字面量")
        return value
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
        return op(_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的一元运算：{type(node.op).__name__}")
        return op(_evaluate(node.operand))
    raise ValueError(f"不支持的表达式片段：{type(node).__name__}")


def _format_number(value: float) -> str:
    """数值 → 紧凑文本（整数不带小数点，底层函数按规范豁免）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value)


def calculate(
    expression: Annotated[
        str,
        Field(
            description=(
                "算术表达式，支持 + - * / // % ** 与括号；"
                "例：(1+2)*3、2**10、100/7。**禁止**函数调用/变量/字符串——会被拒绝"
            )
        ),
    ],
) -> ToolResult:
    """对算术表达式求值（安全白名单解析，**绝不 eval**）。

    Args:
        expression: 算术表达式文本

    Returns:
        `ok` 信封（`data` 带 expression / result）；
        表达式为空 / 语法错 / 除零 / 白名单外语法 → `error: invalid_arg`
    """
    expr = expression.strip()
    if not expr:
        return ToolResult(
            status="error",
            message="计算失败：表达式为空",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    try:
        value = _evaluate(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        return ToolResult(
            status="error",
            message="计算失败：除数为 0",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
        return ToolResult(
            status="error",
            message=f"计算失败：{exc}",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    if isinstance(value, complex) or not isinstance(value, (int, float)):
        return ToolResult(
            status="error",
            message="计算失败：结果不是实数",
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    return ToolResult(
        status="ok",
        message=f"{expr} = {_format_number(value)}",
        data={"expression": expr, "result": value},
        tool=_TOOL_NAME,
    )
