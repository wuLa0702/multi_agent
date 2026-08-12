"""Permissions 权限标准模板：技能只读 + 高危写入审批（hitl_enabled 门控）+ 子代理覆盖。

基于 deepagents 官方 FilesystemPermission（deepagents 0.7.1 核实）：
- operations 仅 read/write 两粒度（write 覆盖 write_file/edit_file/delete/upload_files）
- 路径必须 "/" 开头、禁 ".."；建议限定在 CompositeBackend 路由前缀内
- 规则有序：先匹配先生效（deny /skills/** 必须放最前）
- interrupt → 自动合成 interrupt_on（approve/edit/reject/respond），
  审批后经 resume_run_id 恢复（checkpointer 已就绪）
- 子代理 spec["permissions"] 整体替换父级（graph.py:663 核实）

设计文档：docs/decisions/方案-CompositeBackend深化改造-v1.md §3.1 / §6.3
"""

from __future__ import annotations

from pathlib import Path

from deepagents import FilesystemPermission


def validate_workspace_path(path: str, session_id: str) -> bool:
    """校验 agent 产出的文件路径在工作区白名单内（安全机制 D1，完整校验）。

    修复（2026-08-12 评审大1）：原实现未用 session_id，跨会话穿越（other/secret）
    放行——现拼 workspace/{session_id}/ 前缀 + resolve 检查最终路径在会话目录下。

    底层函数，按规范豁免（通用解析封装）。

    Args:
        path: agent 给出的文件路径（相对 workspace/{session_id}/）
        session_id: 会话 ID（必填，工作区隔离——防跨会话越权）

    Returns:
        True=合法（无外部协议/绝对路径/穿越，且在会话工作区内）
    """
    if not path or "://" in path:  # 禁外部协议（file:// javascript:// 等）
        return False
    if not session_id:
        return False
    base = (Path("workspace") / session_id).resolve()
    full = (base / path).resolve()
    return str(full).startswith(str(base.resolve()))


def build_main_permissions() -> list[FilesystemPermission]:
    """主 Agent 声明式权限。

    - /skills/** 写 deny：技能目录只读（agent 工具层直接拒绝，P0 激活）
    - /memories/private/**、/memories/secrets/** 写 interrupt：高危记忆文件
      写入挂起人工审批（v1.2 评审修正：由 settings.hitl_enabled 统一门控——
      删除原独立常量 INTERRUPT_PERMISSIONS_ENABLED，单配置点防双开关不一致）

    Returns:
        FilesystemPermission 列表（传给 create_deep_agent(permissions=...)）
    """
    from src.core.config import settings  # 惰性导入防循环

    perms = [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills/**"],
            mode="deny",
        ),
    ]
    if settings.hitl_enabled:
        perms.append(
            FilesystemPermission(
                operations=["write"],
                paths=["/memories/private/**", "/memories/secrets/**"],
                mode="interrupt",
            )
        )
    return perms


def build_subagent_permissions(subagent_name: str) -> list[FilesystemPermission]:
    """子代理独立权限（整体替换父级，graph.py:663 语义）。

    Args:
        subagent_name: 子代理名（subagents/*.yaml 的 name）

    Returns:
        FilesystemPermission 列表；未知子代理返回 []（继承父级规则）
    """
    if subagent_name == "search_agent":
        # 搜索子代理无文件需求：写全拒绝（读保留——SkillsMiddleware 读技能不受影响）
        return [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]
    return []
