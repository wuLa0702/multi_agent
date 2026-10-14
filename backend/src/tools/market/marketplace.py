"""外部 Skill 市场适配层：Smithery API 归一化为 SkillMarketItem。

实测（2026-08-03）：`GET https://api.smithery.ai/servers?q=&page=&pageSize=`
无需认证即可搜索 MCP server；`GET /skills?q=` 搜 SKILL.md 类技能；
`GET /servers/{qualifiedName}` 返回详情（deploymentUrl = MCP 端点）。
5 分钟内存缓存减少外部调用；每个市场独立函数，方便后续加 MCP.so。

各市场无统一协议（见 docs/参考/MCP外部市场-排行榜与注册表.md），
本模块是唯一对接点——API 变更只改这里。
"""

from __future__ import annotations

import logging
import time

import httpx

from src.schemas.skill import (
    SKILL_SOURCE_SMITHERY,
    SKILL_TYPE_MCP,
    SKILL_TYPE_MD,
    MarketplaceListResponse,
    SkillMarketItem,
)

logger = logging.getLogger(__name__)

SMITHERY_API_BASE = "https://api.smithery.ai"
_REQUEST_TIMEOUT = 15.0
_CACHE_TTL_SECONDS = 300  # 5 分钟缓存，避免每次浏览都打外部 API


# ── 简单进程内缓存（key → (过期时间, 响应)）──

_cache: dict[str, tuple[float, MarketplaceListResponse]] = {}


def _cache_get(key: str) -> MarketplaceListResponse | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, resp = entry
    if time.monotonic() > expires_at:
        _cache.pop(key, None)
        return None
    return resp


def _cache_set(key: str, resp: MarketplaceListResponse) -> None:
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, resp)


# ── Smithery 适配器 ──

def _parse_server_item(raw: dict) -> SkillMarketItem:
    """Smithery /servers 条目 → SkillMarketItem（mcp_server 类）。"""
    qn = raw.get("qualifiedName") or ""
    return SkillMarketItem(
        name=raw.get("displayName") or qn or "unknown",
        description=raw.get("description") or "",
        source=SKILL_SOURCE_SMITHERY,
        source_url=f"https://smithery.ai/servers/{qn}",
        version=qn,
        skill_type=SKILL_TYPE_MCP,
        use_count=raw.get("useCount") or 0,
        verified=bool(raw.get("verified")),
        # 连接配置由详情接口补全（install 时调用 GET /servers/{qn}）
        transport="streamable_http",
        url="",
    )


def _parse_skill_item(raw: dict) -> SkillMarketItem:
    """Smithery /skills 条目 → SkillMarketItem（skill_md 类）。

    注意：热门列表的 qualifiedName 可能为 null（实测 2026-08-03）——
    source_url 用 gitUrl 兜底，保证每个条目唯一（React key + 幂等去重都依赖它）。
    """
    qn = raw.get("qualifiedName") or ""
    git_url = raw.get("gitUrl") or ""
    fallback = git_url or raw.get("id") or ""
    source_url = f"https://smithery.ai/skills/{qn}" if qn else fallback
    return SkillMarketItem(
        name=raw.get("displayName") or qn or "unknown",
        description=raw.get("description") or "",
        source=SKILL_SOURCE_SMITHERY,
        source_url=source_url,
        version=qn or fallback,
        skill_type=SKILL_TYPE_MD,
        use_count=raw.get("totalActivations") or 0,
        verified=bool(raw.get("verified")),
        git_url=git_url,
    )


async def _fetch_smithery(
    query: str, page: int, page_size: int, skill_type: str
) -> MarketplaceListResponse:
    """调用 Smithery API 搜索（servers 或 skills），归一化为统一响应。

    Args:
        query: 搜索关键词（空 = 热门列表）
        page: 页码（1 起）
        page_size: 每页条数
        skill_type: mcp_server → /servers；skill_md → /skills

    Returns:
        归一化市场条目列表 + 分页

    Raises:
        httpx.HTTPError: 外部 API 不可达（由 API 层降级返回空列表）
    """
    endpoint = "skills" if skill_type == SKILL_TYPE_MD else "servers"
    params = {"page": page, "pageSize": page_size}
    if query:
        params["q"] = query

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.get(f"{SMITHERY_API_BASE}/{endpoint}", params=params)
        resp.raise_for_status()
        data = resp.json()

    items = data.get(endpoint) or []
    pagination = data.get("pagination") or {}
    parsed = [_parse_skill_item(i) if skill_type == SKILL_TYPE_MD else _parse_server_item(i)
              for i in items]
    total = pagination.get("totalCount") or len(parsed)
    page_now = pagination.get("currentPage") or page
    total_pages = pagination.get("totalPages") or 1
    return MarketplaceListResponse(
        source=SKILL_SOURCE_SMITHERY,
        items=parsed,
        total=total,
        page=page_now,
        has_more=page_now < total_pages,
    )


async def _fetch_server_detail(qualified_name: str) -> dict:
    """拉取 Smithery server 详情（含 deploymentUrl 连接配置）。"""
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.get(f"{SMITHERY_API_BASE}/servers/{qualified_name}")
        resp.raise_for_status()
        return resp.json()


# ── Smithery Connect 网关（托管 server 的正确连接方式）──
# 实测（2026-08-03）：托管端点 *.run.tools 直接连 401；正确链路是
# GET /namespaces 拿个人 namespace → POST /connect/{ns} 建 connection →
# 连 https://api.smithery.ai/connect/{ns}/{connectionId}/mcp（Bearer API key
# + MCP-Session-Id: smithery-stateless 跳过握手）。官方 @smithery/api 源码同款。

_namespace_cache: str | None = None


async def _smithery_namespace() -> str:
    """取个人 Smithery namespace（注册时自动生成，进程内缓存）。

    Raises:
        ValueError: 未配置 SMITHERY_API_KEY
        httpx.HTTPError: API 不可达
    """
    from src.core.config import settings

    global _namespace_cache
    if not settings.smithery_api_key:
        raise ValueError("SMITHERY_API_KEY 未配置（.env.dev）——Smithery 托管 server 需鉴权")
    if _namespace_cache:
        return _namespace_cache
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.get(
            f"{SMITHERY_API_BASE}/namespaces",
            headers={"Authorization": f"Bearer {settings.smithery_api_key}"},
        )
        resp.raise_for_status()
        namespaces = resp.json().get("namespaces") or []
    if not namespaces:
        raise ValueError("Smithery 账号无 namespace（注册后自动生成，请刷新页面确认）")
    _namespace_cache = namespaces[0]["name"]
    return _namespace_cache


async def create_smithery_connection(qualified_name: str) -> dict:
    """创建 Smithery connection，返回连接信息。

    Args:
        qualified_name: Smithery registry server 名（如 github / vercel/grep）

    Returns:
        {"connection_id": ..., "state": "connected"|"auth_required"|"error",
         "mcp_url": ..., "setup_url": ... | None}

    Raises:
        ValueError: 未配置 key / namespace 缺失
        httpx.HTTPError: API 不可达
    """
    from src.core.config import settings

    namespace = await _smithery_namespace()
    headers = {"Authorization": f"Bearer {settings.smithery_api_key}"}
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.post(
            f"{SMITHERY_API_BASE}/connect/{namespace}",
            headers={**headers, "Content-Type": "application/json"},
            json={"server": qualified_name, "transport": "http"},
        )
        resp.raise_for_status()
        data = resp.json()

    connection_id = data.get("connectionId") or ""
    status = data.get("status") or {}
    mcp_url = f"{SMITHERY_API_BASE}/connect/{namespace}/{connection_id}/mcp" if connection_id else ""
    return {
        "connection_id": connection_id,
        "state": status.get("state") or "connected",
        "mcp_url": mcp_url,
        "setup_url": status.get("setupUrl") or status.get("authorizationUrl"),
    }


async def search_marketplace(
    source: str,
    query: str,
    page: int,
    page_size: int,
    skill_type: str,
) -> MarketplaceListResponse:
    """市场搜索总入口：按 source 分发给对应适配器。

    Args:
        source: 市场标识（当前仅 smithery）
        query: 搜索关键词
        page: 页码（1 起）
        page_size: 每页条数（上限 100）
        skill_type: mcp_server / skill_md / all（2026-08-04 P2：后端合并两类）

    Returns:
        归一化响应；未知 source 返回空列表（不抛错，前端友好降级）
    """
    if source != SKILL_SOURCE_SMITHERY:
        logger.warning("未知市场 source=%s，返回空列表", source)
        return MarketplaceListResponse(source=source, items=[], total=0, page=page, has_more=False)

    page = max(1, page)
    page_size = min(100, max(1, page_size))

    # P2：skill_type=all 后端合并两类（各取半页，交错拼接）
    if skill_type == "all":
        half = max(1, page_size // 2)
        resp_a = await search_marketplace(source, query, page, half, SKILL_TYPE_MCP)
        resp_b = await search_marketplace(source, query, page, half, SKILL_TYPE_MD)
        items: list[SkillMarketItem] = []
        for a, b in zip(resp_a.items, resp_b.items, strict=False):
            items.extend([a, b])
        # 补齐单侧多出的
        items.extend(resp_a.items[len(resp_b.items) :])
        items.extend(resp_b.items[len(resp_a.items) :])
        return MarketplaceListResponse(
            source=source,
            items=items[:page_size],
            total=resp_a.total + resp_b.total,
            page=page,
            has_more=resp_a.has_more or resp_b.has_more,
        )

    cache_key = f"{source}|{skill_type}|{query}|{page}|{page_size}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = await _fetch_smithery(query, page, page_size, skill_type)
    except httpx.HTTPError as e:
        logger.warning("Smithery API 不可达（%s）——市场浏览降级为空", e)
        resp = MarketplaceListResponse(
            source=source, items=[], total=0, page=page, has_more=False
        )
    _cache_set(cache_key, resp)
    return resp


async def get_market_item_detail(source: str, source_url: str, skill_type: str) -> SkillMarketItem | None:
    """按市场条目页 URL 取完整详情（补全连接配置，供安装用）。

    mcp_server 类：解析 source_url 中的 qualifiedName → GET /servers/{qn} 取 deploymentUrl。
    skill_md 类：source_url 已含足够信息（git_url 在列表里），直接返回 None 由安装走列表字段。

    Args:
        source: 市场标识
        source_url: 市场条目页 URL（https://smithery.ai/servers/{qn}）
        skill_type: mcp_server / skill_md

    Returns:
        补全连接配置的 SkillMarketItem；无法解析返回 None（安装时降级跳过）
    """
    if source != SKILL_SOURCE_SMITHERY:
        return None
    if skill_type == SKILL_TYPE_MD:
        return None  # skill_md 连接信息在列表字段（git_url）里，无需详情

    # https://smithery.ai/servers/{namespace}/{slug} → qualifiedName
    marker = "/servers/"
    idx = source_url.rfind(marker)
    if idx == -1:
        return None
    qn = source_url[idx + len(marker):].rstrip("/")
    if not qn:
        return None

    try:
        detail = await _fetch_server_detail(qn)
    except httpx.HTTPError:
        logger.warning("Smithery 详情不可达：%s", qn)
        return None

    deployment_url = detail.get("deploymentUrl") or ""
    return SkillMarketItem(
        name=detail.get("displayName") or qn,
        description=detail.get("description") or "",
        source=SKILL_SOURCE_SMITHERY,
        source_url=f"https://smithery.ai/servers/{qn}",
        version=qn,
        skill_type=SKILL_TYPE_MCP,
        transport="streamable_http",
        url=deployment_url,
    )
