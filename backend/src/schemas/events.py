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


class ErrorEvent(SSEEvent):
    """流内错误（SSE 已建立后发生；请求阶段错误走 HTTP 4xx）。"""

    type: Literal["error"] = "error"
    code: str = Field(description="错误码（对齐接口文档 §7）")
    detail: str = Field(description="具体原因")
    retryable: bool = Field(default=False, description="是否可重试")
