"""HITL 审批配置（P0 HITL 设计 §5.1）：interrupt_on **从工具登记表派生**。

## 2026-10-15 改造（阶段 4 审批接线）

改造前，本模块手写一张 `HITL_INTERRUPT_ON` 表，与 `tools/registry.py` 的工具元数据
构成「**同一份信息写两遍**」：改一处忘另一处 → 危险工具可能**悄悄执行、无人审批**。

改造后**删掉手写表，改为从 `TOOL_REGISTRY` 派生**：

- 要不要审批 → 读 `ToolSpec.requires_approval`
- 允许人类做哪些决策 → 读 `ToolSpec.allowed_decisions`

配套保险：`tests/test_agent/test_hitl.py::TestApprovalEquivalenceLock` 把改造前的
手写表抄成"标准答案"，锁住"只是换写法，弹窗行为一字未变"。

**为什么按钮集不写死在这**：它是**工具的性质**（这工具允不允许"人类改了再来"），
与"危险程度/是否幂等"同级 —— 故都归登记表，本模块只做消费。

设计文档：`docs/decisions/2026-08-11-设计-P0-HITL机制-v1.md` §5.1 / §7.2 ｜
`docs/决策/2026-10-15-设计-阶段3横切与阶段4编排-v1.md` §4.1
"""

from __future__ import annotations

from langchain.agents.middleware import InterruptOnConfig

from src.tools.registry import TOOL_REGISTRY

# HITL 工具清单（hitl_enabled 门控挂载——关 HITL 时不挂载，避免模型调用
# 永远抛错/无审批出口的工具）
HITL_TOOLS = ("ask_human", "publish_report")


def build_hitl_interrupt_on(enabled: bool) -> dict[str, InterruptOnConfig] | None:
    """构建 interrupt_on（**从工具登记表派生**；hitl_enabled 门控）。

    Args:
        enabled: settings.hitl_enabled

    Returns:
        启用 → `{工具名: InterruptOnConfig}`（只含 `requires_approval=True` 的工具）；
        禁用 → None（create_deep_agent 不配 interrupt_on）

    Raises:
        ValueError: 有工具声明 `requires_approval=True` 却没配 `allowed_decisions`
            —— 配置错误**必须 fail fast**：静默跳过等于"这个工具永不审批"，
            正是本改造要杜绝的事故
    """
    if not enabled:
        return None
    missing = [
        spec.name
        for spec in TOOL_REGISTRY.values()
        if spec.requires_approval and not spec.allowed_decisions
    ]
    if missing:
        raise ValueError(
            f"工具声明需审批但未配 allowed_decisions：{missing}"
            "（配置错误：静默跳过会让该工具永不审批，故 fail fast）"
        )
    return {
        spec.name: InterruptOnConfig(allowed_decisions=list(spec.allowed_decisions))
        for spec in TOOL_REGISTRY.values()
        if spec.requires_approval
    }


def should_mount_hitl_tools(enabled: bool) -> bool:
    """HITL 工具挂载门控（与 hitl_enabled 一致）。

    Args:
        enabled: settings.hitl_enabled

    Returns:
        enabled（True 时挂载 ask_human/publish_report，模型"想清楚了再问、
        交付前申请审核"）
    """
    return enabled
