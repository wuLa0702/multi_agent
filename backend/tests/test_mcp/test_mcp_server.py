"""MCP 端点派生守卫（2026-10-16）：注册表 → MCP 工具，**不再手工重列**。

覆盖三条不变量：
1. 暴露清单 == 登记表里 `requires_approval=False` 的工具（顺序也一致）
2. **需审批的工具绝不暴露**（MCP 没有 HITL 通道，暴露 = 可绕过审批执行代码）
3. 每个暴露工具：描述 == 登记表；参数带 description；框架注入参数 `config` 不出现

背景：改造前本文件的手写清单已漂移到"只包 2 个工具（登记表 14 个）"，
且描述与登记表口径不一致——是「同一件事写两遍」第 6 次。
"""

from __future__ import annotations

import asyncio

from src.tools.channels.mcp_server import EXCLUDED_PARAMS, EXPOSED_TOOL_NAMES, mcp
from src.tools.registry import impl_specs


def _expected_names() -> list[str]:
    """应当暴露的工具名：登记表顺序 + 无需审批。"""
    return [spec.name for spec in impl_specs() if not spec.requires_approval]


def test_exposed_tools_match_registry() -> None:
    """不变量 1：暴露清单由登记表派生（含顺序），不是手写清单。"""
    assert EXPOSED_TOOL_NAMES == _expected_names()


def test_approval_required_tools_not_exposed() -> None:
    """不变量 2：需审批的工具一个都不能出现在 MCP 端点上（安全）。"""
    exposed = set(EXPOSED_TOOL_NAMES)
    leaked = [
        spec.name for spec in impl_specs() if spec.requires_approval and spec.name in exposed
    ]
    assert not leaked, f"需审批的工具被暴露（可绕过审批执行）：{leaked}"


def test_exposed_tools_schema_is_complete() -> None:
    """不变量 3：描述取自登记表；参数有 description；`config` 已隐藏。"""
    by_name = {spec.name: spec for spec in impl_specs()}
    tools = asyncio.run(mcp.list_tools())

    assert {tool.name for tool in tools} == set(EXPOSED_TOOL_NAMES)

    for tool in tools:
        assert tool.description == by_name[tool.name].description, (
            f"{tool.name}：MCP 描述与登记表不一致"
        )
        properties = (tool.parameters or {}).get("properties", {})
        for hidden in EXCLUDED_PARAMS:
            assert hidden not in properties, f"{tool.name} 泄漏了框架参数 {hidden}"
        for param, schema in properties.items():
            assert schema.get("description"), f"{tool.name}.{param} 缺 description"
