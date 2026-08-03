"""工具注册表单测：mcp/registry.py（工具名 → 实现函数映射）。"""

from __future__ import annotations

import pytest

from src.mcp import registry


def test_registry_contains_known_tools() -> None:
    """注册表包含搜索与沙箱两个工具（当前业务能力全集）。"""
    assert "internet_search" in registry.TOOL_REGISTRY
    assert "run_code_in_sandbox" in registry.TOOL_REGISTRY


def test_get_tool_returns_implementation() -> None:
    """按名称取到实现函数（可调用，非占位）。"""
    tool = registry.get_tool("internet_search")
    assert callable(tool)
    assert tool.__name__ == "internet_search"


def test_get_tool_unknown_name_fails_fast() -> None:
    """未知工具名抛 KeyError（配置错误尽早暴露，不让 agent 带病启动）。"""
    with pytest.raises(KeyError, match="未注册工具"):
        registry.get_tool("nonexistent_tool")
