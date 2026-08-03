"""Skill Market 数据模型：市场条目 + 已安装记录 + 请求/响应。

层级：市场条目（SkillMarketItem）来自外部市场 API 归一化；已安装记录
（InstalledSkill）来自 installed_skills 表；请求/响应模型服务 REST 层。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SKILL_TYPE_MCP = "mcp_server"
SKILL_TYPE_MD = "skill_md"
SKILL_SOURCE_MANUAL = "manual"
SKILL_SOURCE_SMITHERY = "smithery"


class SkillMarketItem(BaseModel):
    """外部市场条目（Smithery 等，归一化后统一结构）。

    mcp_server 类：transport/url/command/args 提供连接配置；
    skill_md 类：git_url 提供 SKILL.md 下载来源。
    """

    name: str
    description: str = ""
    source: str = SKILL_SOURCE_SMITHERY
    source_url: str = ""
    version: str = ""
    skill_type: str = SKILL_TYPE_MCP
    use_count: int = 0
    verified: bool = False
    # mcp_server 连接配置
    transport: str = "streamable_http"
    url: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    # skill_md 下载来源（GitHub 仓库 URL）
    git_url: str = ""


class InstalledSkill(BaseModel):
    """本地已安装 Skill 记录。"""

    id: int
    name: str
    skill_type: str
    source: str
    source_url: str
    version: str
    install_path: str
    is_active: bool
    created_at: str
    updated_at: str


class MarketplaceListResponse(BaseModel):
    """市场浏览响应：条目列表 + 分页信息。"""

    source: str
    items: list[SkillMarketItem]
    total: int
    page: int
    has_more: bool


class InstallRequest(BaseModel):
    """安装请求：按市场来源定位条目。

    mcp_server 类提供连接配置（由市场详情补全）；skill_md 类提供 git_url 下载。
    force=True 时已安装也重新拉取覆盖（一键升级）；默认幂等跳过。
    """

    source: str = SKILL_SOURCE_SMITHERY
    source_url: str = ""
    name: str = ""
    skill_type: str = SKILL_TYPE_MCP
    transport: str = "streamable_http"
    url: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    git_url: str = ""
    force: bool = False


class SkillUpdateRequest(BaseModel):
    """启用/停用请求。"""

    is_active: bool


class InstalledSkillListResponse(BaseModel):
    """已安装列表响应。"""

    items: list[InstalledSkill]
    total: int
