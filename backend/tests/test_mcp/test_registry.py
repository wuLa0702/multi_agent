"""工具注册表单测：tools/registry.py（工具名 → 实现函数映射）。"""

from __future__ import annotations

import pytest

from src.tools import registry


def test_registry_contains_known_tools() -> None:
    """注册表包含搜索与沙箱两个工具（当前业务能力全集）。"""
    assert "internet_search" in registry.TOOL_REGISTRY
    assert "run_code_in_sandbox" in registry.TOOL_REGISTRY


def test_get_tool_returns_mounted_base_tool() -> None:
    """按名称取到挂载形态工具（阶段 2.2.0 起为 BaseTool，非裸实现函数）。"""
    from langchain_core.tools import BaseTool

    tool = registry.get_tool("internet_search")
    assert isinstance(tool, BaseTool)
    assert tool.name == "internet_search"


def test_get_tool_returns_content_and_artifact_tool() -> None:
    """不变量：取到的工具必须声明 content_and_artifact（阶段 2 双通道的前提）。

    若退回默认 `content`，工具返回的元组会被 `_stringify` 成
    `"('文本', {...})"` 塞给 LLM。
    """
    for name in registry.TOOL_REGISTRY:
        assert registry.get_tool(name).response_format == "content_and_artifact", name


def test_get_tool_unknown_name_fails_fast() -> None:
    """未知工具名抛 KeyError（配置错误尽早暴露，不让 agent 带病启动）。"""
    with pytest.raises(KeyError, match="未注册工具"):
        registry.get_tool("nonexistent_tool")
