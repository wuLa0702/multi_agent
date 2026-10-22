"""MCP Server：从工具注册表**自动派生** MCP 端点（外部 Agent 可接入）。

- **工具同源**：全部从 `tools/registry.py::impl_specs()` 派生；名字 / 描述 /
  参数 schema 都取登记表，**本文件不再手写任何工具清单**
- **挂载**：`main.py` 经 `McpMountMiddleware` 转发 `/mcp` → `mcp.http_app()`
- **消费方**：外部 MCP Client（Claude Desktop / 其他 agent 系统 / 本项目自身）

## 为什么改成自动派生（2026-10-16）

此前本文件用 `@mcp.tool(name=..., description=...)` **手工重列**工具，与登记表
构成「同一件事写两遍」——实测已漂移：只包了 **2 个**工具（登记表 14 个），
且描述与登记表口径不一致。现在改成读 `impl_specs()`，**加工具只改登记表一处**。

## 暴露范围（安全约束，不是偷懒）

**只暴露 `requires_approval=False` 的工具**。MCP 当前**没有 HITL 审批通道**——
若把 `run_code_in_sandbox` 这类需审批的工具暴露出去，外部客户端可**绕过审批
直接执行代码**。将来若要暴露，须先在 MCP 侧接审批（属新设计，不在本次范围）。

## 协议差异

MCP 是**文本协议**且面向外部 Agent（无 artifact 通道）→ 只发 `render()` 后的
文本，不透传内部 `ToolResult` 对象。参数 schema 沿用登记表签名（`Annotated +
Field` 的描述会一并带过去），但**隐藏 `config`**（框架注入参数，外部不该看到，
也填不对）。
"""

from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from fastmcp import FastMCP

from src.tools.contract.result import render
from src.tools.registry import ToolSpec, impl_specs

mcp = FastMCP("multi-agent")

#: 不暴露给 MCP 客户端的框架注入参数（由 langchain 在调用时注入）
EXCLUDED_PARAMS: tuple[str, ...] = ("config",)

#: 工具名 → **裸实现**。端点**调用时才查表**（而不是闭包捕获），
#: 这样测试可以用 `mocker.patch.dict(_IMPLS, {...})` 替换实现；
#: 将来若做实现热替换，这里也是天然接缝。
_IMPLS: dict[str, Any] = {spec.name: spec.fn for spec in impl_specs()}


def _make_endpoint(spec: ToolSpec) -> Any:
    """把一条工具声明包装成 MCP 端点函数（同签名 / 同描述 / 只回文本）。

    签名沿用裸实现 —— `inspect.signature` 读的就是它，参数描述由
    `Annotated[..., Field(description=…)]` 保留，无需重写。

    Args:
        spec: 实现层声明（`fn` 为裸实现函数）

    Returns:
        可交给 `mcp.tool()` 的包装函数
    """
    impl = spec.fn
    signature = inspect.signature(impl)
    # ⚠️ 实现模块都有 `from __future__ import annotations` → 注解是**字符串**，
    # 必须在**实现模块自己的命名空间**里解析（`Annotated` / `Field` 在那边导入）。
    resolved = get_type_hints(impl, include_extras=True)

    def _entry(*args: Any, **kwargs: Any) -> str:
        """执行内部工具（调用时查表 → 可 mock），渲染成 MCP 的文本响应。"""
        return render(_IMPLS[spec.name](*args, **kwargs))

    _entry.__name__ = spec.name
    _entry.__doc__ = spec.description
    # ⚠️ **必须显式给签名与注解**：包装函数本身是 `(*args, **kwargs)`，而
    # FastMCP 直接拒绝变参函数（`Functions with *args are not supported`）；
    # pydantic 又用 `get_type_hints` 读 `__annotations__` 建参数模型。
    # 两者都指向裸实现后，参数 schema 即由登记表签名推断，`config` 再经
    # `exclude_args` 剔除。
    # 返回注解改成 `str`：签名原样是 `-> ToolResult`，FastMCP 会据此推断
    # structured output 并要求返回 dict；而 MCP 这边只发 `render()` 后的文本。
    _entry.__signature__ = signature.replace(return_annotation=str)  # type: ignore[attr-defined]
    _entry.__annotations__ = {
        **{name: resolved[name] for name in signature.parameters if name in resolved},
        "return": str,
    }
    return _entry


def _register_tools() -> list[str]:
    """把注册表里**无需审批**的工具注册为 MCP 端点。

    Returns:
        实际暴露的工具名列表（注册顺序同登记表）
    """
    exposed: list[str] = []
    for spec in impl_specs():
        if spec.requires_approval:
            # MCP 无审批通道 → 暴露等于绕过审批（见模块 docstring「暴露范围」）
            continue
        # 只有部分工具带框架注入参数（`config`）——按实际签名过滤，
        # 否则 FastMCP 会对没有该参数的工报 "does not exist in function"
        hidden = [p for p in EXCLUDED_PARAMS if p in inspect.signature(spec.fn).parameters]
        mcp.tool(
            name=spec.name,
            description=spec.description,
            exclude_args=hidden or None,
        )(_make_endpoint(spec))
        exposed.append(spec.name)
    return exposed


#: 实际暴露的工具名（启动自检 / 测试断言用）
EXPOSED_TOOL_NAMES: list[str] = _register_tools()
