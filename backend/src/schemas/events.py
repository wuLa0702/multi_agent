"""SSE 流式对话事件模型（接口契约：方案-后端接口定义-v1 §5.3）。

统一信封规则：每条事件是 JSON 对象，必含 type 字段，帧只用 data: 行。
事件顺序保证（§5.5）：首事件必为 start；尾事件为 done 或 error（二选一）。

当前实现（最初级对话闭环）：
- start / token / done / error 四类
后续阶段按契约补齐：tool_call / subagent / approve / summarize
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


class ErrorEvent(SSEEvent):
    """流内错误（SSE 已建立后发生；请求阶段错误走 HTTP 4xx）。"""

    type: Literal["error"] = "error"
    code: str = Field(description="错误码（对齐接口文档 §7）")
    detail: str = Field(description="具体原因")
    retryable: bool = Field(default=False, description="是否可重试")
