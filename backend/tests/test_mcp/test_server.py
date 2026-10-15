"""MCP Server 测试：FastMCP 暴露内部工具，进程内 Client 往返验证。

覆盖（20-testing.md：正常 / 错误）：
- list_tools：internet_search + run_code_in_sandbox 两个工具在列
- call_tool：调用成功返回（内部实现 mock，不实际调外部 API）
- 工具描述含使用说明（模型可理解）
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client, FastMCPTransport

from src.tools.channels.mcp_server import mcp


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
    """正常：调用 internet_search 工具返回搜索实现结果（内部 mock）。

    阶段 2.2.1 起内部实现返回 `ToolResult` 信封（不再返回裸字符串），
    MCP 包装层负责 `render()` 成文本——故 mock 也要给信封。
    """
    from src.tools.result import ToolResult

    mocker.patch(
        "src.tools.channels.mcp_server._internet_search",
        return_value=ToolResult(status="ok", message="mock 搜索结果", tool="internet_search"),
    )

    async with Client(FastMCPTransport(mcp)) as client:
        result = await client.call_tool("internet_search", {"query": "测试"})

    assert result.content, "调用应返回内容"
    text = "".join(getattr(b, "text", "") for b in result.content)
    assert "mock 搜索结果" in text


@pytest.mark.asyncio
async def test_server_renders_error_envelope_as_text(mocker) -> None:
    """错误态：信封经 MCP 出去是**带前缀的中文文本**，不是对象、不是 JSON。"""
    from src.tools.result import ToolResult

    mocker.patch(
        "src.tools.channels.mcp_server._internet_search",
        return_value=ToolResult(
            status="error",
            message="搜索不可用：BOCHA_API_KEY 未配置（.env.dev），请直接基于已有知识回答。",
            error_code="not_configured",
            tool="internet_search",
        ),
    )

    async with Client(FastMCPTransport(mcp)) as client:
        result = await client.call_tool("internet_search", {"query": "测试"})

    text = "".join(getattr(b, "text", "") for b in result.content)
    assert text.startswith("失败原因：")
    assert "not_configured" not in text, "错误码不进给 LLM / 外部 Agent 的文本"


@pytest.mark.asyncio
async def test_server_call_sandbox(mocker) -> None:
    """正常：调用 run_code_in_sandbox 工具返回沙箱结果（内部 mock）。"""
    mocker.patch("src.tools.channels.mcp_server._run_code_in_sandbox", return_value="sandbox output")

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
