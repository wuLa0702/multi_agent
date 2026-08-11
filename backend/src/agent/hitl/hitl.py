"""HITL 审批配置（P0 HITL 设计 §5.1）：按工具风险分级的 interrupt_on。

- 高危（任意代码执行）→ approve+edit+reject；中危（命令/文件/技能）→
  approve+reject；只读/无副作用工具 → False 不审批
- 澄清域（ask_human）只开 respond；交付域（publish_report）approve/edit/reject
- settings.hitl_enabled 门控：默认关，业务接入时开
- 文件权限 interrupt（mode="interrupt"）由 core/permissions.py 模板扩展（设计 §5.1）

设计文档：docs/decisions/2026-08-11-设计-P0-HITL机制-v1.md §5.1 / §7.2
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
    # 澄清域（P0 设计 §5.1）：只开 respond——人类回答即工具结果；
    # 🔴 绝不配 approve/edit（官方警告：respond 仅限 ask-user 类工具）
    "ask_human": InterruptOnConfig(allowed_decisions=["respond"]),
    # 交付域（P0 设计 §4.5）：报告交付前人工审核——approve 通过 / reject+note
    # 修订 / edit 改报告；修订轮次上限见 settings.publish_review_max_revisions
    "publish_report": InterruptOnConfig(
        allowed_decisions=["approve", "edit", "reject"]
    ),
    # 只读/搜索：无副作用，不审批
    "internet_search": False,
}

# HITL 工具清单（hitl_enabled 门控挂载——关 HITL 时不挂载，避免模型调用
# 永远抛错/无审批出口的工具）
HITL_TOOLS = ("ask_human", "publish_report")


def build_hitl_interrupt_on(enabled: bool) -> dict[str, bool | InterruptOnConfig] | None:
    """构建 interrupt_on（hitl_enabled 门控；禁用 → None 不挂载审批）。

    Args:
        enabled: settings.hitl_enabled

    Returns:
        启用 → HITL_INTERRUPT_ON；禁用 → None（create_deep_agent 不配 interrupt_on）
    """
    return HITL_INTERRUPT_ON if enabled else None


def should_mount_hitl_tools(enabled: bool) -> bool:
    """HITL 工具挂载门控（与 hitl_enabled 一致）。

    Args:
        enabled: settings.hitl_enabled

    Returns:
        enabled（True 时挂载 ask_human/publish_report，模型"想清楚了再问、
        交付前申请审核"）
    """
    return enabled
