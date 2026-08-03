"""Skill 安装管理器：市场条目 → 本地落地 → 触发 Agent 热加载。

mcp_server 类：写入 mcp_servers 表（McpClientManager 消费）→ reload 重建连接；
skill_md 类：下载 SKILL.md 写入 data/skills/skill_md/{name}/（SkillsMiddleware 扫描）。

安装/卸载/切换后统一调用：
- get_mcp_client_manager().reload(conn) —— MCP 工具热刷新
- rebuild_agent() —— Agent 单例下次请求重建（含新 SKILL.md）
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import aiosqlite
import httpx

from src.core.paths import get_skill_md_dir
from src.db import skill_repository as repo
from src.schemas.skill import (
    SKILL_SOURCE_SMITHERY,
    SKILL_TYPE_MCP,
    SKILL_TYPE_MD,
    InstalledSkill,
    SkillMarketItem,
)

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15.0

# GitHub 仓库树 URL → raw 文件 URL（SKILL.md 下载用）
# https://github.com/{owner}/{repo}/tree/{branch}/{path} →
# https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}/SKILL.md
_GITHUB_TREE_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)"
)


def _is_valid_skill_name(name: str) -> bool:
    """SKILL.md 目录名合法性：小写字母数字连字符（deepagents 规范）。"""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name))


async def _download_skill_md(git_url: str, name: str) -> Path:
    """从 GitHub raw URL 下载 SKILL.md 到本地 skill 目录。

    Args:
        git_url: GitHub 仓库树 URL（Smithery skills 条目的 gitUrl 字段）
        name: skill 名（目录名，deepagents 规范小写连字符）

    Returns:
        写入后的 SKILL.md 路径

    Raises:
        ValueError: git_url 无法解析 / skill 名不合法
        httpx.HTTPError: 下载失败
    """
    if not _is_valid_skill_name(name):
        raise ValueError(f"非法 skill 名：{name}（需小写字母数字连字符）")

    m = _GITHUB_TREE_RE.match(git_url)
    if not m:
        raise ValueError(f"无法解析 GitHub URL：{git_url}")
    owner, repo_name, branch, path = m.groups()
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{branch}/{path}/SKILL.md"

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(raw_url)
        resp.raise_for_status()

    target_dir = get_skill_md_dir() / name
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_file = target_dir / "SKILL.md"
    skill_file.write_text(resp.text, encoding="utf-8")
    return skill_file


async def _resolve_mcp_connection(item: SkillMarketItem) -> tuple[str, str]:
    """解析 mcp_server 的连接地址与鉴权 headers。

    Smithery 托管 server：调 Connect 网关建 connection，URL 用
    /connect/{ns}/{connectionId}/mcp（*.run.tools 直连 401，见 marketplace.py）；
    需要 OAuth 的 server（state=auth_required）抛错提示授权。
    其他来源（manual / 第三方直连 URL）：直接用条目自带 url + 空 headers。
    """
    if item.source == SKILL_SOURCE_SMITHERY:
        from src.skills.marketplace import create_smithery_connection

        version = item.version or item.name
        conn = await create_smithery_connection(version)
        if conn["state"] == "auth_required":
            setup = conn.get("setup_url") or "Smithery 官网该 server 页面"
            raise ValueError(
                f"{item.name} 需要 OAuth 授权：请先在浏览器访问 {setup} 完成授权后重试安装"
            )
        if not conn["mcp_url"]:
            raise ValueError(f"Smithery 连接创建失败：{item.name}")
        return conn["mcp_url"], _auth_headers_for(item)
    if not item.url:
        raise ValueError(f"MCP server 缺少连接地址：{item.name}")
    return item.url, "{}"


def _auth_headers_for(item: SkillMarketItem) -> str:
    """Smithery Connect 网关的鉴权 headers（JSON 字符串）。

    - Authorization: Bearer API key（个人账号）
    - MCP-Session-Id: smithery-stateless（官方 SDK 同款——跳过 MCP 握手，
      Smithery 网关无状态）
    未配置 key 时返回空对象（server 连接失败由 McpClientManager 降级跳过）。
    """
    if item.source != SKILL_SOURCE_SMITHERY:
        return "{}"
    from src.core.config import settings

    if not settings.smithery_api_key:
        return "{}"
    return json.dumps({
        "Authorization": f"Bearer {settings.smithery_api_key}",
        "MCP-Session-Id": "smithery-stateless",
    })


async def install_skill(conn: aiosqlite.Connection, item: SkillMarketItem) -> InstalledSkill:
    """安装市场条目到本地；已安装则幂等跳过。

    Args:
        conn: SQLite 连接（已初始化 schema）
        item: 市场条目（已含连接配置或 git_url）

    Returns:
        已安装记录（新装或已存在）

    Raises:
        ValueError: 参数不完整 / skill 名不合法 / 下载失败
    """
    # 幂等：同来源同条目已装 → 直接返回现有记录
    existing = await repo.get_installed_by_source(conn, item.source, item.source_url)
    if existing is not None:
        logger.info("Skill 已安装，跳过：%s", item.source_url)
        return existing

    if item.skill_type == SKILL_TYPE_MCP:
        url, headers = await _resolve_mcp_connection(item)
        args_json = json.dumps(item.args)
        # name 必须 slug 化：McpClientManager tool_name_prefix=True 用它当工具前缀，
        # DeepSeek 等模型 API 要求工具名只含 [a-zA-Z0-9_-]（"Vercel Grep_xxx" 含空格会被 400 拒绝）
        server_name = re.sub(r"[^a-zA-Z0-9_-]", "_", item.name).strip("_") or "mcp_server"
        server_id = await repo.insert_mcp_server(
            conn,
            name=server_name,
            transport=item.transport,
            url=url,
            command=item.command,
            args=args_json,
            source=item.source,
            source_url=item.source_url,
            version=item.version,
            headers=headers,
        )
        record = await repo.insert_installed(
            conn,
            name=item.name,
            skill_type=SKILL_TYPE_MCP,
            source=item.source,
            source_url=item.source_url,
            version=item.version,
            install_path=str(server_id),  # 关联 mcp_servers.id
        )
        logger.info("Skill 安装成功（mcp_server id=%s）：%s", server_id, item.name)
        return record

    if item.skill_type == SKILL_TYPE_MD:
        if not item.git_url:
            raise ValueError(f"SKILL.md 缺少 git_url：{item.name}")
        skill_file = await _download_skill_md(item.git_url, item.name)
        record = await repo.insert_installed(
            conn,
            name=item.name,
            skill_type=SKILL_TYPE_MD,
            source=item.source,
            source_url=item.source_url,
            version=item.version,
            install_path=str(skill_file),
        )
        logger.info("Skill 安装成功（skill_md）：%s → %s", item.name, skill_file)
        return record

    raise ValueError(f"未知 skill_type：{item.skill_type}")


async def uninstall_skill(conn: aiosqlite.Connection, skill_id: int) -> bool:
    """卸载已安装 Skill：删除 DB 记录 + 本地文件。

    Args:
        conn: SQLite 连接
        skill_id: installed_skills.id

    Returns:
        是否命中（不存在返回 False）

    Raises:
        OSError: 本地文件删除失败（DB 已删，只记录警告不阻断）
    """
    record = await repo.get_installed(conn, skill_id)
    if record is None:
        return False

    # mcp_server：删除 mcp_servers 关联行（install_path 存的是 server_id）
    if record.skill_type == SKILL_TYPE_MCP and record.install_path.isdigit():
        await repo.delete_mcp_server_by_id(conn, int(record.install_path))
    # skill_md：删除本地目录（install_path 是 SKILL.md 文件路径）
    elif record.skill_type == SKILL_TYPE_MD and record.install_path:
        try:
            skill_file = Path(record.install_path)
            target_dir = skill_file.parent
            if target_dir.exists():
                for f in target_dir.iterdir():
                    f.unlink()
                target_dir.rmdir()
        except OSError:
            logger.warning("Skill 本地文件删除失败（已删 DB 记录）：%s", record.install_path)

    await repo.delete_installed(conn, skill_id)
    logger.info("Skill 卸载完成：%s（id=%s）", record.name, skill_id)
    return True


async def toggle_skill(conn: aiosqlite.Connection, skill_id: int, is_active: bool) -> bool:
    """启用/停用 Skill：同步 installed_skills 与关联 mcp_servers。

    Args:
        conn: SQLite 连接
        skill_id: installed_skills.id
        is_active: 目标状态

    Returns:
        是否命中（不存在返回 False）
    """
    record = await repo.get_installed(conn, skill_id)
    if record is None:
        return False

    await repo.update_active(conn, skill_id, is_active)
    if record.skill_type == SKILL_TYPE_MCP and record.install_path.isdigit():
        await repo.update_mcp_server_active(conn, int(record.install_path), is_active)
    logger.info("Skill 状态切换：%s → %s（id=%s）", record.name, is_active, skill_id)
    return True
