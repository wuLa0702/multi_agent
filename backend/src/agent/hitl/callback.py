"""HITL 中断检测回调（P0 HITL 设计 §5.5）：GraphCallbackHandler 采集中断点。

⚠️ 实证修正（2026-08-11，设计 §3.3-②）：astream_events 不产 on_interrupt
事件——中断检测必须经 config["callbacks"] 的 GraphCallbackHandler.on_interrupt；
事件携带真实 checkpoint_id + interrupts（value = HITLRequest 形态）。

回调只采集不决策：中断上下文写入收集器，流内循环（try/finally）检测到后
登记 Redis 并产出 approve 事件（单一事件出口，保持 stream_agent_events 职责）。
"""

from __future__ import annotations

from langgraph.callbacks import GraphCallbackHandler, GraphInterruptEvent


class HitlCallback(GraphCallbackHandler):
    """采集 graph 中断事件（checkpoint_id + HITLRequest 负载）。

    Attributes:
        interrupted: 最近一次中断上下文（None=未中断）——
            {"checkpoint_id": str, "hitl_request": {"action_requests", "review_configs"}}
    """

    def __init__(self) -> None:
        self.interrupted: dict | None = None

    def on_interrupt(self, event: GraphInterruptEvent) -> None:
        """中断回调：记录 checkpoint_id 与审批负载（流内据此产出 approve 事件）。

        Args:
            event: langgraph 中断生命周期事件（含真实 checkpoint_id）
        """
        if not event.interrupts:
            return
        self.interrupted = {
            "checkpoint_id": event.checkpoint_id,
            "hitl_request": event.interrupts[0].value,
        }
