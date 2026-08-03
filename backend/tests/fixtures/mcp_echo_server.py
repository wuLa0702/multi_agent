"""MCP stdio 测试 server：回显工具（test_mcp/test_client.py 的 stdio 目标）。

运行：python mcp_echo_server.py（作为 stdio 子进程被 MultiServerMCPClient 拉起）。
"""

from fastmcp import FastMCP

mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> str:
    """原样回显输入文本（测试用）。"""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
