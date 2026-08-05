"""Permissions 权限标准模板：技能只读 + 高危写入审批（开关门控）+ 子代理覆盖。

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

from deepagents import FilesystemPermission

# ── 高危写入 interrupt 审批开关 ──
# 当前 SSE approve 事件链路（前端审批面板）未接入——interrupt 规则命中会挂起
# 而无审批出口。链路接入后翻转本常量即全链路生效（唯一激活点）。
INTERRUPT_PERMISSIONS_ENABLED = False


def build_main_permissions() -> list[FilesystemPermission]:
    """主 Agent 声明式权限。

    - /skills/** 写 deny：技能目录只读（agent 工具层直接拒绝，P0 激活）
    - /memories/private/**、/memories/secrets/** 写 interrupt：高危记忆文件
      写入挂起人工审批（INTERRUPT_PERMISSIONS_ENABLED 门控，默认不激活）

    Returns:
        FilesystemPermission 列表（传给 create_deep_agent(permissions=...)）
    """
    perms = [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills/**"],
            mode="deny",
        ),
    ]
    if INTERRUPT_PERMISSIONS_ENABLED:
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
