"""HITL 审批配置（人在回路设计 §5.1）：按工具风险分级的 interrupt_on。

- 高危（任意代码执行）→ approve+edit+reject；中危（命令/文件/技能）→
  approve+reject；只读/无副作用工具 → False 不审批
- settings.hitl_enabled 门控：默认关，业务接入时开
- 文件权限 interrupt（mode="interrupt"）由 core/permissions.py 模板扩展（设计 §5.1）
- 恢复链路（审批 API / approve 事件）依赖 P0-V2 验证（设计 §6.2：astream_events
  中断检测与 Command(resume) 形态），验证通过后接入 chat.py

设计文档：docs/decisions/方案-人在回路与Rubric评分-详细设计-v1.md §5.1 / §7.1
"""

from __future__ import annotations

from langchain.agents.middleware import InterruptOnConfig

# 工具名 → interrupt_on 配置（True=默认四决策 / False=不审批 / 配置=自定义决策集）
HITL_INTERRUPT_ON: dict[str, bool | InterruptOnConfig] = {
    # 沙箱执行域：可执行任意代码/命令，高危
    "run_code_in_sandbox": InterruptOnConfig(
        allowed_decisions=["approve", "edit", "reject"]
    ),
    "run_command_in_sandbox": InterruptOnConfig(
        allowed_decisions=["approve", "reject"]
    ),
    # 文件同步域：工作区进出，中危
    "upload_workspace_file": InterruptOnConfig(allowed_decisions=["approve", "reject"]),
    "download_sandbox_file": InterruptOnConfig(allowed_decisions=["approve", "reject"]),
    # 技能执行域：脚本执行，中危
    "run_skill_script": InterruptOnConfig(allowed_decisions=["approve", "reject"]),
    # 只读/搜索：无副作用，不审批
    "internet_search": False,
}


def build_hitl_interrupt_on(enabled: bool) -> dict[str, bool | InterruptOnConfig] | None:
    """构建 interrupt_on（hitl_enabled 门控；禁用 → None 不挂载审批）。

    Args:
        enabled: settings.hitl_enabled

    Returns:
        启用 → HITL_INTERRUPT_ON；禁用 → None（create_deep_agent 不配 interrupt_on）
    """
    return HITL_INTERRUPT_ON if enabled else None
