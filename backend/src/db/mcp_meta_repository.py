"""数据访问层（DAO）：MCP 工具的治理元数据（`mcp_tool_meta` 表）。

规范（规则 06 §2）：与 `skill_repository` 同款——显式接收连接、参数化 SQL、
写操作 commit、行由连接层 dict_row 提供（`row["col"]` 取值）；时间统一 UTC ISO。

**这一层只搬数据，不解析治理语义**：查询返回**原始行 dict**，由
`tools/channels/mcp_meta.py` 解析成 `McpToolPolicy`。
⚠️ 不能让本模块 import `tools.*`——`db/` 是底座层，反向依赖能力层会违反分层
（`tests/test_tools/test_layering.py` 会红）。同款先例：`mcp_client._load_connections`
与 `get_mcp_server_by_source_url` 也返回原始行。

设计依据：`docs/决策/2026-10-15-设计-工具动态注册两方案对比-v1.md` §8.1/§8.2。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from psycopg import AsyncConnection


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（DB 存储格式）。"""
    return datetime.now(timezone.utc).isoformat()


async def list_meta_rows(conn: AsyncConnection) -> list[dict]:
    """全部治理元数据（预加载入口）。

    Returns:
        原始行 dict 列表（排序固定，便于人工核对与测试断言）
    """
    cursor = await conn.execute(
        "SELECT * FROM mcp_tool_meta ORDER BY server_name, tool_name"
    )
    return list(await cursor.fetchall())


async def existing_tool_names(conn: AsyncConnection, server_name: str) -> set[str]:
    """某 server 已登记治理元数据的工具名集合（**以 DB 为准**）。

    「自动登记不覆盖人工调整」必须查 DB 而不是内存缓存——缓存可能滞后于库
    （例如同一进程内刚被别的路径改过），拿它判重会导致误覆盖或误跳过。

    Args:
        conn: PG 连接
        server_name: MCP server slug

    Returns:
        该 server 下已登记的远端工具名集合
    """
    cursor = await conn.execute(
        "SELECT tool_name FROM mcp_tool_meta WHERE server_name = %s", (server_name,)
    )
    rows = await cursor.fetchall()
    return {row["tool_name"] for row in rows}


async def upsert_meta(
    conn: AsyncConnection,
    server_name: str,
    tool_name: str,
    *,
    risk_level: str = "low",
    requires_approval: bool = False,
    allowed_decisions: list[str] | None = None,
    is_idempotent: bool = False,
    retry: dict | None = None,
    note: str = "",
) -> None:
    """新增或更新一条治理元数据（按 `(server_name, tool_name)` 冲突则更新）。

    Args:
        conn: PG 连接
        server_name: MCP server 名（对应 `mcp_servers.name`）
        tool_name: 远端原始工具名（不含 server 前缀）
        risk_level: low / medium / high
        requires_approval: 是否需 HITL 审批
        allowed_decisions: 审批允许的决策集（`requires_approval=True` 时应非空）
        is_idempotent: 是否幂等（重试门控）
        retry: 重试参数 dict（如 `{"retries": 2, "delays": [0.5, 1.0]}`）；None = 不重试
        note: 备注（人工核对用）
    """
    now = _now_iso()
    await conn.execute(
        """INSERT INTO mcp_tool_meta
           (server_name, tool_name, risk_level, requires_approval, allowed_decisions,
            is_idempotent, retry, note, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (server_name, tool_name) DO UPDATE SET
               risk_level        = EXCLUDED.risk_level,
               requires_approval = EXCLUDED.requires_approval,
               allowed_decisions = EXCLUDED.allowed_decisions,
               is_idempotent     = EXCLUDED.is_idempotent,
               retry             = EXCLUDED.retry,
               note              = EXCLUDED.note,
               updated_at        = EXCLUDED.updated_at""",
        (
            server_name,
            tool_name,
            risk_level,
            int(requires_approval),
            json.dumps(allowed_decisions or [], ensure_ascii=False),
            int(is_idempotent),
            json.dumps(retry, ensure_ascii=False) if retry else "",
            note,
            now,
            now,
        ),
    )
    await conn.commit()


async def delete_meta(
    conn: AsyncConnection, server_name: str, tool_name: str
) -> bool:
    """删除一条治理元数据；返回是否命中。

    删除后该工具即回到"未登记"状态 → 不再挂载（默认拒绝，定案 X1）。
    """
    cursor = await conn.execute(
        "DELETE FROM mcp_tool_meta WHERE server_name = %s AND tool_name = %s",
        (server_name, tool_name),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_by_server(conn: AsyncConnection, server_name: str) -> int:
    """删除某 server 的全部治理元数据（连接删除时联动清理）；返回删除行数。

    ⚠️ 不做联动的话：删了 MCP 连接、元数据还留着——将来同名 server 再装回来，
    会**继承旧治理声明**（可能与其真实能力不符），属隐蔽的越权面。
    """
    cursor = await conn.execute(
        "DELETE FROM mcp_tool_meta WHERE server_name = %s", (server_name,)
    )
    await conn.commit()
    return cursor.rowcount
