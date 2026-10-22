"""MCP Server 测试：FastMCP 端点**从注册表派生**，进程内 Client 往返验证。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- list_tools：暴露清单 == 登记表里 `requires_approval=False` 的工具
- **安全**：需审批的工具不暴露（MCP 无 HITL 通道）
- call_tool：调用成功返回文本（实现 mock，不实际调外部 API）
- 错误态：信封经 MCP 出去是**带前缀的中文文本**，不是对象 / JSON
- 描述：全部非空

2026-10-16 改造：此前本文件断言"手工重列的两个工具"
（`internet_search` + `run_code_in_sandbox`）；改为派生后清单变为 7 个，
且 `run_code_in_sandbox` **因需审批被排除**——这正是本次要守住的安全边界。
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client, FastMCPTransport

from src.tools.channels.mcp_server import EXPOSED_TOOL_NAMES, mcp
from src.tools.contract.result import ToolResult


@pytest.mark.asyncio
async def test_server_lists_derived_tools() -> None:
    """正常：暴露清单与派生结果一致（不是手写清单）。"""
    async with Client(FastMCPTransport(mcp)) as client:
        tools = await client.list_tools()

    names = [t.name for t in tools]
    assert names == EXPOSED_TOOL_NAMES
    assert len(names) == len(EXPOSED_TOOL_NAMES)


@pytest.mark.asyncio
async def test_approval_required_tools_not_exposed() -> None:
    """安全：需审批的工具（代码执行 / 文件同步 / HITL）**一个都不能暴露**。

    MCP 没有审批通道 —— 暴露出去等于让外部客户端绕过审批直接执行代码。
    """
    async with Client(FastMCPTransport(mcp)) as client:
        names = {t.name for t in await client.list_tools()}

    for forbidden in (
        "run_code_in_sandbox",
        "run_command_in_sandbox",
        "upload_workspace_file",
        "download_sandbox_file",
        "run_skill_script",
        "ask_human",
        "publish_report",
    ):
        assert forbidden not in names, f"{forbidden} 需审批，不应暴露给 MCP"


@pytest.mark.asyncio
async def test_server_call_internet_search(mocker) -> None:
    """正常：调用 internet_search 返回内部实现渲染后的文本（实现 mock）。"""
    mocker.patch.dict(
        "src.tools.channels.mcp_server._IMPLS",
        {
            "internet_search": lambda **_: ToolResult(
                status="ok", message="mock 搜索结果", tool="internet_search"
            )
        },
    )

    async with Client(FastMCPTransport(mcp)) as client:
        result = await client.call_tool("internet_search", {"query": "测试"})

    text = "".join(getattr(b, "text", "") for b in result.content)
    assert "mock 搜索结果" in text


@pytest.mark.asyncio
async def test_server_renders_error_envelope_as_text(mocker) -> None:
    """错误态：信封经 MCP 出去是**带前缀的中文文本**，错误码不外泄。"""
    mocker.patch.dict(
        "src.tools.channels.mcp_server._IMPLS",
        {
            "internet_search": lambda **_: ToolResult(
                status="error",
                message="搜索不可用：BOCHA_API_KEY 未配置（.env.dev），请直接基于已有知识回答。",
                error_code="not_configured",
                tool="internet_search",
            )
        },
    )

    async with Client(FastMCPTransport(mcp)) as client:
        result = await client.call_tool("internet_search", {"query": "测试"})

    text = "".join(getattr(b, "text", "") for b in result.content)
    assert text.startswith("失败原因：")
    assert "not_configured" not in text, "错误码不进给 LLM / 外部 Agent 的文本"


@pytest.mark.asyncio
async def test_server_tool_descriptions_are_documented() -> None:
    """边界：每个暴露工具的描非空且有实际内容（模型靠描述决定何时调用）。"""
    async with Client(FastMCPTransport(mcp)) as client:
        tools = await client.list_tools()

    assert tools, "至少应暴露一个工具"
    for tool in tools:
        assert tool.description, f"{tool.name} 应有描述"
        assert len(tool.description) > 10, f"{tool.name} 描述过短"
