"""MCP Client 测试：McpClientManager 读 DB 配置 → MultiServerMCPClient 收集工具。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- _load_connections：DB 行 → connections dict（sse/stdio 两种 transport）
- 全链路：stdio 子进程 echo server → connect_all → get_tools（前缀 + BaseTool 类型）
- 未知 transport 跳过 + 无启用 server 时工具为空
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.mcp.client import McpClientManager

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_echo_server.py"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def _insert_server(conn, **fields) -> None:
    """往 mcp_servers 插入一行（默认值补齐）。"""
    defaults = {
        "name": "echo",
        "transport": "stdio",
        "url": "",
        "command": sys.executable,
        "args": json.dumps([str(_FIXTURE)]),
        "headers": "{}",
        "is_active": 1,
        "sort_order": 0,
    }
    defaults.update(fields)
    now = _now_iso()
    await conn.execute(
        """INSERT INTO mcp_servers
           (name, transport, url, command, args, headers, is_active, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["name"],
            defaults["transport"],
            defaults["url"],
            defaults["command"],
            defaults["args"],
            defaults["headers"],
            defaults["is_active"],
            defaults["sort_order"],
            now,
            now,
        ),
    )
    await conn.commit()


@pytest.fixture
async def conn(tmp_db_path):
    """隔离 SQLite 连接（schema 已建，含 mcp_servers 表）。"""
    from src.core import db as core_db

    c = await core_db.get_connection()
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_load_connections_stdio(conn) -> None:
    """正常：stdio 行 → {name: {transport, command, args, env(UTF-8)}}。"""
    await _insert_server(conn)

    connections = await McpClientManager._load_connections(conn)

    assert connections == {
        "echo": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(_FIXTURE)],
            # Windows 子进程 UTF-8 强制（04-logging.md；防 GBK 污染父进程流）
            "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        }
    }


@pytest.mark.asyncio
async def test_load_connections_sse(conn) -> None:
    """正常：sse 行 → {name: {transport, url, headers}}。"""
    await _insert_server(
        conn,
        name="remote",
        transport="sse",
        url="http://localhost:9000/mcp",
        headers=json.dumps({"Authorization": "Bearer x"}),
    )

    connections = await McpClientManager._load_connections(conn)

    assert connections == {
        "remote": {
            "transport": "sse",
            "url": "http://localhost:9000/mcp",
            "headers": {"Authorization": "Bearer x"},
        }
    }


@pytest.mark.asyncio
async def test_load_connections_skips_unknown_transport(conn) -> None:
    """边界：未知 transport 行跳过；inactive 行不加载。"""
    await _insert_server(conn, name="bad", transport="carrier_pigeon")
    await _insert_server(conn, name="disabled", is_active=0)

    connections = await McpClientManager._load_connections(conn)

    assert connections == {}


@pytest.mark.asyncio
async def test_connect_all_stdio_roundtrip(conn) -> None:
    """全链路：stdio 子进程 echo server → 收集 BaseTool + server 名前缀。"""
    await _insert_server(conn)

    manager = McpClientManager()
    try:
        await manager.connect_all(conn)

        tools = manager.get_tools()
        assert len(tools) >= 1
        # tool_name_prefix=True：工具名带 server 名前缀
        assert any(t.name == "echo_echo" for t in tools), f"工具名：{[t.name for t in tools]}"
        assert all(hasattr(t, "invoke") for t in tools), "应为 langchain BaseTool"

        # 实际调用（真实 stdio 往返）
        result = await tools[0].ainvoke({"text": "hi"})
        assert "echo: hi" in str(result)
    finally:
        manager.reset()


@pytest.mark.asyncio
async def test_connect_all_no_servers(conn) -> None:
    """边界：无启用 server → 空工具列表，client 为 None。"""
    manager = McpClientManager()
    try:
        await manager.connect_all(conn)
        assert manager.get_tools() == []
        assert manager.get_client() is None
    finally:
        manager.reset()
