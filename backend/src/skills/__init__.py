"""Skill Market 层：外部市场适配 + 本地安装管理。

依赖单向（api → skills → {db, mcp}）：市场数据来源归一化、安装生命周期管理。
"""

from src.skills.installer import install_skill, toggle_skill, uninstall_skill
from src.skills.marketplace import search_marketplace

__all__ = [
    "install_skill",
    "toggle_skill",
    "uninstall_skill",
    "search_marketplace",
]
