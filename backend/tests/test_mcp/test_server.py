"""MCP Server 测试：FastMCP 暴露内部工具，进程内 Client 往返验证。

覆盖（20-testing.md：正常 / 错误）：
- list_tools：internet_search + run_code_in_sandbox 两个工具在列
- call_tool：调用成功返回（内部实现 mock，不实际调外部 API）
- 工具描述含使用说明（模型可理解）
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client, FastMCPTransport

from src.mcp.server import mcp


@pytest.mark.asyncio
async def test_server_lists_internal_tools() -> None:
    """正常：MCP server 暴露两个内部工具。"""
    async with Client(FastMCPTransport(mcp)) as client:
        tools = await client.list_tools()

    names = {t.name for t in tools}
    assert "internet_search" in names
    assert "run_code_in_sandbox" in names


@pytest.mark.asyncio
async def test_server_call_internet_search(mocker) -> None:
    """正常：调用 internet_search 工具返回搜索实现结果（内部 mock）。"""
    mocker.patch("src.mcp.server._internet_search", return_value="mock 搜索结果")

    async with Client(FastMCPTransport(mcp)) as client:
        result = await client.call_tool("internet_search", {"query": "测试"})

    assert result.content, "调用应返回内容"
    text = "".join(getattr(b, "text", "") for b in result.content)
    assert "mock 搜索结果" in text


@pytest.mark.asyncio
async def test_server_call_sandbox(mocker) -> None:
    """正常：调用 run_code_in_sandbox 工具返回沙箱结果（内部 mock）。"""
    mocker.patch("src.mcp.server._run_code_in_sandbox", return_value="sandbox output")

    async with Client(FastMCPTransport(mcp)) as client:
        result = await client.call_tool("run_code_in_sandbox", {"code": "print(1)"})

    text = "".join(getattr(b, "text", "") for b in result.content)
    assert "sandbox output" in text


@pytest.mark.asyncio
async def test_server_tool_descriptions_are_documented() -> None:
    """边界：工具描述非空且包含使用说明（模型靠描述决定何时调用）。"""
    async with Client(FastMCPTransport(mcp)) as client:
        tools = await client.list_tools()

    by_name = {t.name: t for t in tools}
    for name in ("internet_search", "run_code_in_sandbox"):
        assert by_name[name].description, f"{name} 应有描述"
        assert len(by_name[name].description) > 10
