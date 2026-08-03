"""MCP 客户端管理：连接外部 MCP server，收集工具注入 agent。

模式（与 core/model_registry.py 同款）：
- lifespan 启动时 connect_all（读 mcp_servers 表 → MultiServerMCPClient → get_tools）
- 进程内缓存；配置变更后 reload（管理 API 接入时用）
- MultiServerMCPClient 每次工具调用自动建/销 session，无需手动管理连接

tool_name_prefix=True：多 server 同名工具加 server 名前缀，避免冲突
（如 "bocha_search" vs "tavily_search"）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

import aiosqlite
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

_manager: "McpClientManager | None" = None
_manager_lock = threading.Lock()


class McpClientManager:
    """外部 MCP server 连接管理（DB 配置 → 工具列表缓存）。

    Attributes:
        _client: MultiServerMCPClient 实例（懒创建，connect_all 时初始化）
        _tools: 收集到的 langchain BaseTool 列表（agent 构建时注入）
    """

    def __init__(self) -> None:
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] = []

    async def connect_all(self, conn: aiosqlite.Connection) -> None:
        """读取 mcp_servers 表 active server → 构建 client → 收集工具。

        Args:
            conn: 已初始化 schema 的 SQLite 连接

        Raises:
            Exception: 连接/取工具失败（由 lifespan 捕获降级为仅内部工具）
        """
        connections = await self._load_connections(conn)
        if not connections:
            logger.info("mcp_servers 表无启用 server，agent 仅使用内部工具")
            self._client = None
            self._tools = []
            return

        client = MultiServerMCPClient(connections, tool_name_prefix=True)
        # 逐个 server 取工具（gather return_exceptions）：单个 server 连不上
        # （缺 key / 服务下线）只跳过它，不影响其他 server 与整体启动
        tasks = [
            client.get_tools(server_name=name)
            for name in connections
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tools: list[BaseTool] = []
        failed: list[str] = []
        for name, result in zip(connections, results, strict=True):
            if isinstance(result, BaseException):
                failed.append(name)
                logger.warning("MCP server %s 连接/取工具失败（跳过）：%s", name, result)
            else:
                tools.extend(result)
        if failed:
            logger.warning("MCP 客户端共 %d 个 server，%d 个失败跳过", len(connections), len(failed))

        self._client = client
        self._tools = tools
        logger.info("MCP 客户端已连接 %d 个 server，收集 %d 个工具", len(connections) - len(failed), len(tools))

    async def reload(self, conn: aiosqlite.Connection) -> None:
        """配置变更后重建连接与工具缓存（管理 API 接入后调用）。"""
        await self.connect_all(conn)

    def reset(self) -> None:
        """清空缓存（测试隔离）。"""
        self._client = None
        self._tools = []

    def get_tools(self) -> list[BaseTool]:
        """当前 MCP 工具列表（agent 构建时注入；未连接时为空列表）。"""
        return self._tools

    def get_client(self) -> MultiServerMCPClient | None:
        """底层 client（测试 / 高级用例）。"""
        return self._client

    @staticmethod
    async def _load_connections(
        conn: aiosqlite.Connection,
    ) -> dict[str, dict]:
        """mcp_servers 表 → MultiServerMCPClient connections 格式。

        Args:
            conn: SQLite 连接

        Returns:
            {server_name: {transport, url | command/args, ...}}；无启用 server 时为空 dict
        """
        cur = await conn.execute(
            """SELECT name, transport, url, command, args, headers
               FROM mcp_servers WHERE is_active = 1 ORDER BY sort_order"""
        )
        rows = await cur.fetchall()

        connections: dict[str, dict] = {}
        for row in rows:
            name = row["name"]
            transport = row["transport"]
            if transport in ("sse", "streamable_http"):
                connections[name] = {
                    "transport": transport,
                    "url": row["url"],
                    "headers": json.loads(row["headers"] or "{}"),
                }
            elif transport == "stdio":
                connections[name] = {
                    "transport": "stdio",
                    "command": row["command"],
                    "args": json.loads(row["args"] or "[]"),
                    # Windows 子进程默认 GBK 输出（04-logging.md：项目强制 UTF-8），
                    # 不注入会把 GBK 字节写进父进程 stderr 流（测试捕获/日志乱码）
                    "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                }
            else:
                logger.warning("mcp_servers %s: 未知 transport=%s，跳过", name, transport)
        return connections


def get_mcp_client_manager() -> McpClientManager:
    """进程内单例（线程安全懒创建）。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = McpClientManager()
    return _manager
