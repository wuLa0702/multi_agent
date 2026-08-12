"""数据访问层（DAO）：Skill Market 安装记录 + mcp_servers 来源追踪。

规范（12-backend.md）：与 repository.py 同款——显式 conn、参数化 SQL、
写操作 commit、aiosqlite.Row；时间统一 UTC ISO 字符串。
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from src.schemas.skill import InstalledSkill


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（DB 存储格式）。"""
    return datetime.now(timezone.utc).isoformat()


# ── 行 → 模型 ──

def _row_to_installed_skill(row: aiosqlite.Row) -> InstalledSkill:
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

async def list_installed(conn: aiosqlite.Connection) -> list[InstalledSkill]:
    """已安装 Skill 列表（更新时间倒序）。"""
    cursor = await conn.execute(
        "SELECT * FROM installed_skills ORDER BY updated_at DESC"
    )
    rows = await cursor.fetchall()
    return [_row_to_installed_skill(r) for r in rows]


async def get_installed(conn: aiosqlite.Connection, skill_id: int) -> InstalledSkill | None:
    """按 ID 查已安装 Skill；不存在返回 None。"""
    cursor = await conn.execute(
        "SELECT * FROM installed_skills WHERE id = ?", (skill_id,)
    )
    row = await cursor.fetchone()
    return _row_to_installed_skill(row) if row else None


async def get_installed_by_source(
    conn: aiosqlite.Connection, source: str, source_url: str
) -> InstalledSkill | None:
    """按市场来源查已安装 Skill（幂等安装去重用）。"""
    cursor = await conn.execute(
        "SELECT * FROM installed_skills WHERE source = ? AND source_url = ?",
        (source, source_url),
    )
    row = await cursor.fetchone()
    return _row_to_installed_skill(row) if row else None


async def insert_installed(
    conn: aiosqlite.Connection,
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
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (name, skill_type, source, source_url, version, install_path, now, now),
    )
    await conn.commit()
    return InstalledSkill(
        id=cursor.lastrowid,
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


async def update_active(conn: aiosqlite.Connection, skill_id: int, is_active: bool) -> bool:
    """更新启用状态；返回是否命中。"""
    cursor = await conn.execute(
        "UPDATE installed_skills SET is_active = ?, updated_at = ? WHERE id = ?",
        (int(is_active), _now_iso(), skill_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_installed(conn: aiosqlite.Connection, skill_id: int) -> bool:
    """删除已安装记录；返回是否命中。"""
    cursor = await conn.execute("DELETE FROM installed_skills WHERE id = ?", (skill_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def list_mcp_skill_ids(conn: aiosqlite.Connection, server_id: int) -> list[int]:
    """查某 MCP server（install_path=server_id）关联的 installed_skills id 列表。

    Args:
        conn: SQLite 连接
        server_id: mcp_servers.id

    Returns:
        关联 skill id 列表（删除连接时先清关联记录）
    """
    cursor = await conn.execute(
        "SELECT id FROM installed_skills "
        "WHERE skill_type='mcp_server' AND install_path = ?",
        (str(server_id),),
    )
    rows = await cursor.fetchall()
    return [row["id"] for row in rows]


# ── mcp_servers 来源追踪 ──

async def get_mcp_server_by_source_url(
    conn: aiosqlite.Connection, source_url: str
) -> aiosqlite.Row | None:
    """按市场条目 URL 查 mcp_servers 行（幂等安装去重用）。"""
    cursor = await conn.execute(
        "SELECT * FROM mcp_servers WHERE source_url = ?", (source_url,)
    )
    return await cursor.fetchone()


async def insert_mcp_server(
    conn: aiosqlite.Connection,
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
           VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?)""",
        (name, transport, url, command, args, headers, source, source_url, version, now, now, now),
    )
    await conn.commit()
    return cursor.lastrowid


async def update_mcp_server_active(
    conn: aiosqlite.Connection, server_id: int, is_active: bool
) -> bool:
    """更新 mcp_servers 启用状态；返回是否命中。"""
    cursor = await conn.execute(
        "UPDATE mcp_servers SET is_active = ?, updated_at = ? WHERE id = ?",
        (int(is_active), _now_iso(), server_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def delete_mcp_server_by_id(conn: aiosqlite.Connection, server_id: int) -> bool:
    """删除 mcp_servers 行；返回是否命中。"""
    cursor = await conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    await conn.commit()
    return cursor.rowcount > 0
