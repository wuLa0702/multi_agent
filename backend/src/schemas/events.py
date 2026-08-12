"""SSE 流式对话事件模型（接口契约：方案-后端接口定义-v1 §5.3）。

统一信封规则：每条事件是 JSON 对象，必含 type 字段，帧只用 data: 行。
事件顺序保证（§5.5）：首事件必为 start；尾事件为 done 或 error（二选一）。

当前实现：
- start / token / done / error 四类（最初级闭环）
- tool_call / subagent 两类（2026-08-05 引入方案 P1 落地，契约 v3 定稿）
后续阶段按契约补齐：approve / summarize
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SSEEvent(BaseModel):
    """SSE 事件基类（契约要求：必含 type 字段）。"""

    type: str = Field(description="事件类型，见接口文档 §5.2")


class StartEvent(SSEEvent):
    """流建立即发（新对话 + resume 均发）。"""

    type: Literal["start"] = "start"
    run_id: str = Field(description="本次 run 的 ID（resume 时前端回传）")
    session_id: str = Field(description="会话 ID")
    resumed: bool = Field(default=False, description="True = 审批后恢复")


class TokenEvent(SSEEvent):
    """主 Agent 生成的增量文本（前端追加渲染，不做缓冲聚合）。"""

    type: Literal["token"] = "token"
    text: str = Field(description="增量文本")


class DoneEvent(SSEEvent):
    """Agent 执行完成，流关闭。"""

    type: Literal["done"] = "done"
    run_id: str = Field(description="本次 run 的 ID")
    session_id: str = Field(description="会话 ID")
    duration_ms: int = Field(description="本次 run 耗时（毫秒）")
    context_used: int | None = Field(
        default=None,
        description="上下文累计用量（历史估算 + 本轮实际 token，2026-08-04 P2）",
    )
    context_warning: bool = Field(
        default=False,
        description="用量告警（#4，2026-08-05）：context_used > 80% 窗口时 True——"
        "告知用户'为什么回答变模糊了'（与 summarizer 互补：压缩=自动兜底，告警=告知原因）",
    )
    context_total: int = Field(
        default=128_000,
        description="上下文上限（模型窗口，2026-08-04 P2）",
    )


class ToolCallEvent(SSEEvent):
    """工具调用事件（契约 v3 定稿，2026-08-05 落地）：前端驱动"工具调用进度条"。

    Attributes:
        tool: 工具名（如 run_code_in_sandbox）
        status: running / completed / error
        input: 入参截断 ≤300（密钥纪律，同 ToolAudit 脱敏）
        output: 结果截断 ≤300
        id: 事件序号（前端去重/排序）
    """

    type: Literal["tool_call"] = "tool_call"
    tool: str = Field(description="工具名")
    status: Literal["running", "completed", "error"] = Field(description="工具调用状态")
    input: str = Field(default="", description="入参（截断 ≤300，脱敏）")
    output: str | None = Field(default=None, description="结果（截断 ≤300）")
    id: int = Field(description="事件序号（流内自增，前端去重/排序）")


class SubagentEvent(SSEEvent):
    """子代理生命周期事件（契约 v3 定稿，2026-08-05 落地）：前端驱动"子代理卡片"。

    Attributes:
        name: 子代理名（search_agent）
        status: started / completed / failed
        depth: 嵌套深度（递归展平后可渲染树形层级）
        id: 事件序号
    """

    type: Literal["subagent"] = "subagent"
    name: str = Field(description="子代理名")
    status: Literal["started", "completed", "failed"] = Field(description="子代理状态")
    depth: int = Field(default=0, description="嵌套深度（0 = 顶层）")
    id: int = Field(description="事件序号（流内自增）")


class CostAlertEvent(SSEEvent):
    """成本软告警（2026-08-11 成本控制 §5.6）：超阈值提示前端，只记录不硬限制。"""

    type: Literal["cost_alert"] = "cost_alert"
    session_id: str = Field(description="会话 ID")
    total_cost: float = Field(description="累计会话成本（元）")
    threshold: float = Field(description="触发阈值（元）")


class ErrorEvent(SSEEvent):
    """流内错误（SSE 已建立后发生；请求阶段错误走 HTTP 4xx）。"""

    type: Literal["error"] = "error"
    code: str = Field(description="错误码（对齐接口文档 §7）")
    detail: str = Field(description="具体原因")
    retryable: bool = Field(default=False, description="是否可重试")


class ApproveEvent(SSEEvent):
    """审批/澄清事件（P0 HITL 设计 §5.2）：流内中断挂起，等待人类决策。

    Attributes:
        run_id: chat.py 本次流 run_id（流标识；会话内多个中断可用它区分，
            v1.1 拍板：与 checkpoint_id 职责分离）
        checkpoint_id: 中断点真实 checkpoint_id（GraphInterruptEvent 提供，
            v1.1 新增独立字段）——resume 恢复键，前端透传作 resume_run_id
        call_id: 工具调用 id（v1.2：多 action 顺序匹配键，add_decision 按它定位）
        tool_name: 工具名（run_code_in_sandbox / ask_human / publish_report）
        arguments: 待审参数（v1.2：逐字段截断 ≤300 脱敏——同 ToolCallEvent 口径）
        message: 人类可读审批说明（ask_human 时为问题原文；publish_report 为报告摘要）
        allowed_decisions: 该工具允许的决策集（前端按钮渲染）
        kind: approval=审批卡片 / clarification=澄清回答框（前端忽略未知字段）
        id: 事件序号（流内自增）
    """

    type: Literal["approve"] = "approve"
    run_id: str = Field(description="chat.py 流 run_id（流标识）")
    checkpoint_id: str = Field(description="中断点真实 checkpoint_id（resume 恢复键）")
    call_id: str = Field(description="工具调用 id（多 action 顺序匹配键）")
    tool_name: str = Field(description="工具名")
    arguments: dict = Field(default_factory=dict, description="待审参数（截断脱敏）")
    message: str = Field(description="审批说明/澄清问题原文/报告摘要")
    allowed_decisions: list[str] = Field(description="允许的决策集")
    kind: Literal["approval", "clarification"] = Field(default="approval")
    id: int = Field(description="事件序号")
