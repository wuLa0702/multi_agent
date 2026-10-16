"""数据访问层（DAO）：Skill Market 安装记录 + mcp_servers 来源追踪。

规范（规则 06 §2）：与 session_repo 同款——显式接收连接、参数化 SQL、
写操作 commit、行由连接层 dict_row 提供（`row["col"]` 取值）；
时间统一 UTC ISO 字符串。

方言要点（2026-10-15 PG 迁移）：占位符 `?` → `%s`；
自增主键取回由 `cursor.lastrowid` → `INSERT ... RETURNING id`。
"""

from __future__ import annotations

from datetime import datetime, timezone

from psycopg import AsyncConnection

from src.schemas.skill import InstalledSkill


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（DB 存储格式）。"""
    return datetime.now(timezone.utc).isoformat()


# ── 行 → 模型 ──

def _row_to_installed_skill(row: dict) -> InstalledSkill:
    """DB 行 → InstalledSkill 实体。"""
    return InstalledSkill(
        id=row["id"],
        name=row["name"],
        skill_type=row["skill_type"],
        source=row["source"],
        source_url=row["source_url"],
        version=row["version"],
        install_path=row["install_path"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── installed_skills CRUD ──

async def list_installed(conn: AsyncConnection) -> list[InstalledSkill]:
    """已安装 Skill 列表（更新时间倒序）。"""
    cursor = await conn.execute(
        "SELECT * FROM installed_skills ORDER BY updated_at DESC"
    )
    rows = await cursor.fetchall()
    return [_row_to_installed_skill(r) for r in rows]


async def get_installed(conn: AsyncConnection, skill_id: int) -> InstalledSkill | None:
    """按 ID 查已安装 Skill；不存在返回 None。"""
    cursor = await conn.execute(
        "SELECT * FROM installed_skills WHERE id = %s", (skill_id,)
    )
    row = await cursor.fetchone()
    return _row_to_installed_skill(row) if row else None


async def get_installed_by_source(
    conn: AsyncConnection, source: str, source_url: str
) -> InstalledSkill | None:
    """按市场来源查已安装 Skill（幂等安装去重用）。"""
    cursor = await conn.execute(
        "SELECT * FROM installed_skills WHERE source = %s AND source_url = %s",
        (source, source_url),
    )
    row = await cursor.fetchone()
    return _row_to_installed_skill(row) if row else None


async def insert_installed(
    conn: AsyncConnection,
    name: str,
    skill_type: str,
    source: str,
    source_url: str,
    version: str,
    install_path: str,
) -> InstalledSkill:
    """插入已安装记录；返回带自增 id 的实体。"""
    now = _now_iso()
    cursor = await conn.execute(
        """INSERT INTO installed_skills
           (name, skill_type, source, source_url, version, install_path,
            is_active, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s) RETURNING id""",
        (name, skill_type, source, source_url, version, install_path, now, now),
    )
    inserted = await cursor.fetchone()
    await conn.commit()
    return InstalledSkill(
        id=inserted["id"] if inserted else None,
        name=name,
        skill_type=skill_type,
        source=source,
        source_url=source_url,
        version=version,
        install_path=install_path,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


async def update_active(
    conn: AsyncConnection, skill_id: int, is_active: bool
) -> bool:
    """更新启用状态；返回是否命中。"""
    cursor = await conn.execute(
        "UPDATE installed_skills SET is_active = %s, updated_at = %s WHERE id = %s",
        (int(is_active), _now_iso(), skill_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_installed(conn: AsyncConnection, skill_id: int) -> bool:
    """删除已安装记录；返回是否命中。"""
    cursor = await conn.execute(
        "DELETE FROM installed_skills WHERE id = %s", (skill_id,)
    )
    await conn.commit()
    return cursor.rowcount > 0


async def list_mcp_skill_ids(conn: AsyncConnection, server_id: int) -> list[int]:
    """查某 MCP server（install_path=server_id）关联的 installed_skills id 列表。

    Args:
        conn: PG 连接
        server_id: mcp_servers.id

    Returns:
        关联 skill id 列表（删除连接时先清关联记录）
    """
    cursor = await conn.execute(
        "SELECT id FROM installed_skills "
        "WHERE skill_type='mcp_server' AND install_path = %s",
        (str(server_id),),
    )
    rows = await cursor.fetchall()
    return [row["id"] for row in rows]


# ── mcp_servers 来源追踪 ──

async def list_mcp_servers(conn: AsyncConnection) -> list[dict]:
    """MCP 连接配置列表（手动配置 + Skill Market 安装的）。

    ⚠️ **只取对外视图的 7 列**——`headers`（含 `Authorization` 明文）**不得外泄**，
    故不写 `SELECT *`（`get_mcp_server_by_source_url` 是内部去重用，不对外）。

    Args:
        conn: PG 连接

    Returns:
        行 dict 列表（键：id / name / transport / url / is_active / source / version）；
        排序 `sort_order, id`（手动配置与市场安装共用同一序列）
    """
    cursor = await conn.execute(
        "SELECT id, name, transport, url, is_active, source, version "
        "FROM mcp_servers ORDER BY sort_order, id"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_mcp_server_by_source_url(
    conn: AsyncConnection, source_url: str
) -> dict | None:
    """按市场条目 URL 查 mcp_servers 行（幂等安装去重用）。"""
    cursor = await conn.execute(
        "SELECT * FROM mcp_servers WHERE source_url = %s", (source_url,)
    )
    return await cursor.fetchone()


async def insert_mcp_server(
    conn: AsyncConnection,
    name: str,
    transport: str,
    url: str,
    command: str,
    args: str,
    source: str,
    source_url: str,
    version: str,
    headers: str = "{}",
) -> int:
    """插入外部 MCP server 连接配置；返回新行 id。

    Args:
        headers: HTTP headers JSON 字符串（如 {"Authorization": "Bearer ..."}，
            市场托管 server 鉴权用；默认空对象）
    """
    now = _now_iso()
    cursor = await conn.execute(
        """INSERT INTO mcp_servers
           (name, transport, url, command, args, headers, is_active, sort_order,
            source, source_url, version, installed_at, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, 1, 0, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, transport, url, command, args, headers, source, source_url, version, now, now, now),
    )
    inserted = await cursor.fetchone()
    await conn.commit()
    return inserted["id"]


async def update_mcp_server_active(
    conn: AsyncConnection, server_id: int, is_active: bool
) -> bool:
    """更新 mcp_servers 启用状态；返回是否命中。"""
    cursor = await conn.execute(
        "UPDATE mcp_servers SET is_active = %s, updated_at = %s WHERE id = %s",
        (int(is_active), _now_iso(), server_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_mcp_server_by_id(conn: AsyncConnection, server_id: int) -> bool:
    """删除 mcp_servers 行；返回是否命中。"""
    cursor = await conn.execute(
        "DELETE FROM mcp_servers WHERE id = %s", (server_id,)
    )
    await conn.commit()
    return cursor.rowcount > 0
