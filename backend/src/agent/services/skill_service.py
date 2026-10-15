"""技能/MCP 数据服务——skill 仓储中转（api 禁直调 db/）。"""

from __future__ import annotations

from src.db import connection as db_conn
from src.db import skill_repository
from src.schemas.skill import InstalledSkill


async def list_installed_skills() -> list[InstalledSkill]:
    """已安装技能列表。"""
    async with db_conn.connection() as conn:
        return await skill_repository.list_installed(conn)


async def update_mcp_server_active(server_id: int, is_active: bool) -> bool:
    """切换 MCP server 启用状态；失败返回 False。"""
    async with db_conn.connection() as conn:
        return await skill_repository.update_mcp_server_active(
            conn, server_id, is_active
        )


async def delete_mcp_server(server_id: int) -> bool:
    """删除 MCP server（含关联 installed_skills 清理）；失败返回 False。

    SQL 均收敛在 skill_repository（唯一 SQL 出口），本服务只做编排。
    """
    async with db_conn.connection() as conn:
        skill_ids = await skill_repository.list_mcp_skill_ids(conn, server_id)
        for skill_id in skill_ids:
            await skill_repository.delete_installed(conn, skill_id)
        return await skill_repository.delete_mcp_server_by_id(conn, server_id)
