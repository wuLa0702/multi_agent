"""MCP Server：把项目内部工具暴露为标准 MCP 端点（外部 Agent 可接入）。

- 工具同源：包装 src/agent/tools/ 的实现（registry 是工具真相源）
- 挂载：main.py `app.mount("/mcp", mcp.http_app())`，共享 FastAPI 端口
- 消费方：外部 MCP Client（Claude Desktop / 其他 agent 系统 / 本项目自身
  也可用 langchain_mcp_adapters 连自己验证闭环）
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.agent.tools.sandbox_tool import run_code_in_sandbox as _run_code_in_sandbox
from src.agent.tools.search import internet_search as _internet_search

mcp = FastMCP("multi-agent")


@mcp.tool(
    name="internet_search",
    description=(
        "网络搜索（博查 Bocha）：传入关键词，返回结构化结果（标题/链接/摘要）。"
        "适合需要最新资料的调研任务；搜索失败返回错误说明，不会中断运行。"
    ),
)
def internet_search(query: str, max_results: int = 5) -> str:
    """包装内部搜索工具（同源，注册表是真相源）。"""
    return _internet_search(query, max_results)


@mcp.tool(
    name="run_code_in_sandbox",
    description=(
        "在隔离 OpenSandbox 沙箱中执行 Python 代码并返回输出。"
        "适合运行测试/验证脚本等不可信代码，不影响本地环境。"
    ),
)
def run_code_in_sandbox(code: str, filename: str = "script.py") -> str:
    """包装内部沙箱工具（同源，注册表是真相源）。"""
    return _run_code_in_sandbox(code, filename)
