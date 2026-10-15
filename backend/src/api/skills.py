"""Skill Market REST 路由：市场浏览 + 安装管理（浏览/安装/列表/切换/卸载）。

- GET    /v1/skills/marketplace/list  市场浏览（Smithery 代理，带缓存）
- POST   /v1/skills/install            安装（mcp_server 查详情补连接 / skill_md 下载）
- GET    /v1/skills/installed          已安装列表
- PATCH  /v1/skills/{skill_id}         启用/停用
- DELETE /v1/skills/{skill_id}         卸载

安装/切换/卸载后：MCP 工具 reload + Agent 单例失效（下次请求重建）。
错误统一 ErrorResponse（契约 §3.3）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from src.agent.services import mcp_service, skill_service
from src.schemas.skill import (
    SKILL_TYPE_MCP,
    SKILL_TYPE_MD,
    InstallRequest,
    InstalledSkillListResponse,
    MarketplaceListResponse,
    SkillUpdateRequest,
)
from src.tools.market import installer
from src.tools.market.marketplace import get_market_item_detail, search_marketplace

router = APIRouter(prefix="/v1/skills", tags=["skills"])


def _error(status: int, code: str, detail: str) -> HTTPException:
    """统一错误响应（契约 §3.3：error/detail/code）。"""
    return HTTPException(
        status_code=status,
        detail={"error": "ErrorResponse", "detail": detail, "code": code},
    )


async def _refresh_agent_tools() -> None:
    """安装/切换/卸载后的热刷新（转发到唯一入口 `mcp_service.refresh_agent_tools`）。

    ⚠️ 2026-10-15 收口：本处原本自有一份 reload + rebuild_agent 实现，
    与 `api/mcp_servers.py` 的两条路径各写各的（且那两条各有缺失，见 G1）。
    现统一转发——**不要在本文件重新长出实现**，否则又变两处真相源。
    """
    await mcp_service.refresh_agent_tools()


@router.get("/marketplace/list", response_model=MarketplaceListResponse)
async def marketplace_list(
    source: str = Query("smithery", description="市场标识"),
    query: str = Query("", description="搜索关键词，空 = 热门列表"),
    page: int = Query(1, ge=1, description="页码（1 起）"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    skill_type: str = Query(SKILL_TYPE_MCP, description="mcp_server / skill_md"),
) -> MarketplaceListResponse:
    """市场浏览：代理外部市场搜索（Smithery 无需认证，带 5 分钟缓存）。"""
    return await search_marketplace(source, query, page, page_size, skill_type)


@router.post("/install")
async def install(req: InstallRequest):
    """一键安装：按市场条目落地本地。

    mcp_server 类：先拉市场详情补全连接地址，再写入 mcp_servers + 记录；
    skill_md 类：从 git_url 下载 SKILL.md 到本地目录。
    已安装（同来源同条目）幂等返回现有记录；req.force=True 重新拉取覆盖（升级）。
    """
    if req.skill_type not in (SKILL_TYPE_MCP, SKILL_TYPE_MD):
        raise _error(400, "INVALID_SKILL_TYPE", f"未知 skill_type：{req.skill_type}")

    # 由安装请求构造市场条目；mcp_server 无 url 时先查详情补全
    item = repo_model_to_item(req)
    if req.skill_type == SKILL_TYPE_MCP and not req.url:
        detail = await get_market_item_detail(req.source, req.source_url, req.skill_type)
        if detail is None or not detail.url:
            raise _error(502, "MARKETPLACE_UNAVAILABLE",
                         f"市场详情获取失败：{req.source_url}（无法确定连接地址）")
        item = detail

    try:
        async with db_conn.connection() as conn:
            record = await installer.install_skill(conn, item, force=req.force)
    except ValueError as e:
        raise _error(400, "INSTALL_FAILED", str(e)) from e

    # MCP 类：**安装后自动登记治理元数据**（"下载即用"）——否则 fail-closed
    # 会把它挡在门外（未登记不挂载）。默认值由 MCP 注解推导，本地表可覆盖。
    # 顺序：登记 →【必须】再热刷新（登记会刷新治理缓存，随后重建的图才认它）
    if req.skill_type == SKILL_TYPE_MCP:
        await mcp_service.register_server_tools(installer.slug_server_name(item.name))

    await _refresh_agent_tools()
    return record


@router.get("/installed", response_model=InstalledSkillListResponse)
async def installed_list() -> InstalledSkillListResponse:
    """已安装 Skill 列表（更新时间倒序）。"""
    items = await skill_service.list_installed_skills()
    return InstalledSkillListResponse(items=items, total=len(items))


@router.patch("/{skill_id}")
async def skill_update(skill_id: int, req: SkillUpdateRequest):
    """启用/停用 Skill（同步 mcp_servers 的 is_active）。"""
    async with db_conn.connection() as conn:
        hit = await installer.toggle_skill(conn, skill_id, req.is_active)
    if not hit:
        raise _error(404, "SKILL_NOT_FOUND", f"Skill 不存在：{skill_id}")

    await _refresh_agent_tools()
    return {"status": "ok", "id": skill_id, "is_active": req.is_active}


@router.delete("/{skill_id}")
async def skill_delete(skill_id: int):
    """卸载 Skill：删除 DB 记录 + 本地文件 + 触发热刷新。"""
    async with db_conn.connection() as conn:
        hit = await installer.uninstall_skill(conn, skill_id)
    if not hit:
        raise _error(404, "SKILL_NOT_FOUND", f"Skill 不存在：{skill_id}")

    await _refresh_agent_tools()
    return {"status": "ok", "id": skill_id}


def repo_model_to_item(req: InstallRequest):
    """InstallRequest → SkillMarketItem（复用市场条目结构，连接字段直接透传）。"""
    from src.schemas.skill import SkillMarketItem

    return SkillMarketItem(
        name=req.name,
        source=req.source,
        source_url=req.source_url,
        skill_type=req.skill_type,
        transport=req.transport,
        url=req.url,
        command=req.command,
        args=req.args,
        git_url=req.git_url,
    )
