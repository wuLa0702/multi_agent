"""MCP 管理 REST 路由（2026-08-04 后端开发计划 P1，设置页去 mock）。

- GET    /v1/mcp-servers        连接配置列表（mcp_servers 表全量）
- PATCH  /v1/mcp-servers/{id}   启停（同步 is_active + 触发工具热刷新）
- DELETE /v1/mcp-servers/{id}   删除连接（含 installed_skills 关联清理）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agent.services import mcp_service, skill_service
from src.api.error_handlers import api_error
from src.db import connection as db_conn

router = APIRouter(prefix="/v1/mcp-servers", tags=["mcp-servers"])


class McpServerOut(BaseModel):
    """MCP 连接配置（对外视图，不含鉴权 headers 明文）。"""

    id: int
    name: str
    transport: str
    url: str
    is_active: bool
    source: str
    version: str


class McpServerUpdateRequest(BaseModel):
    """启停请求。"""

    is_active: bool


class McpServerListResponse(BaseModel):
    """连接列表。"""

    status: str = "ok"
    items: list[McpServerOut]
    total: int


class PendingToolsResponse(BaseModel):
    """待登记清单：已拉取到但未配治理元数据的 MCP 工具（当前不挂载）。

    Attributes:
        status: ok
        items: 未登记的挂载名（`{server}_{tool}`）
        total: 条数
    """

    status: str = "ok"
    items: list[str]
    total: int


def _error(status: int, code: str, detail: str) -> HTTPException:
    """统一错误（契约 §3.3）；信封构造委托 `api_error`，本文件不再自建模型。"""
    return api_error(status, code, detail)


def _row_to_out(row) -> McpServerOut:
    """DB 行 → 对外模型。"""
    return McpServerOut(
        id=row["id"],
        name=row["name"],
        transport=row["transport"],
        url=row["url"],
        is_active=bool(row["is_active"]),
        source=row["source"],
        version=row["version"],
    )


@router.get("", response_model=McpServerListResponse)
async def list_mcp_servers() -> McpServerListResponse:
    """连接配置列表（含手动配置与 Skill Market 安装的）。"""
    async with db_conn.connection() as conn:
        cursor = await conn.execute(
            "SELECT id, name, transport, url, is_active, source, version "
            "FROM mcp_servers ORDER BY sort_order, id"
        )
        rows = await cursor.fetchall()
    items = [_row_to_out(r) for r in rows]
    return McpServerListResponse(items=items, total=len(items))


@router.get("/pending-tools", response_model=PendingToolsResponse)
async def list_pending_tools() -> PendingToolsResponse:
    """**待登记清单**：已拉取到但未配治理元数据的 MCP 工具。

    这些工具当前**不挂载**（fail-closed，定案 X1）——本接口把"未登记就不可用"
    从"莫名其妙的缺失"变成"看得见的待办"。

    Returns:
        `{status, items, total}`；`items` 为未登记的挂载名（`{server}_{tool}`）
    """
    from src.tools.channels.mcp_meta import pending_tool_names

    names = pending_tool_names(get_mcp_client_manager().get_tools())
    return PendingToolsResponse(items=names, total=len(names))


@router.patch("/{server_id}")
async def update_mcp_server(server_id: int, req: McpServerUpdateRequest):
    """启停连接：更新 is_active + 触发 MCP 工具热刷新。"""
    hit = await skill_service.update_mcp_server_active(server_id, req.is_active)
    if not hit:
        raise _error(404, "MCP_SERVER_NOT_FOUND", f"MCP 连接不存在：{server_id}")

    # 热刷新（唯一入口，见 mcp_service docstring：此前此处漏了 rebuild_agent，
    # 导致老会话仍用旧工具清单）
    await mcp_service.refresh_agent_tools()
    return {"status": "ok", "id": server_id, "is_active": req.is_active}


@router.delete("/{server_id}")
async def delete_mcp_server(server_id: int):
    """删除连接（含 installed_skills 关联清理）+ 热刷新。

    热刷新在此**必须**做：不刷新的话，已删除 server 的工具仍留在图里，
    模型会去调一个不存在的服务（此前缺这一步）。
    """
    hit = await skill_service.delete_mcp_server(server_id)
    if not hit:
        raise _error(404, "MCP_SERVER_NOT_FOUND", f"MCP 连接不存在：{server_id}")
    await mcp_service.refresh_agent_tools()
    return {"status": "ok", "id": server_id}
