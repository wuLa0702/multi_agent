"""推理层 trace 观测中间件族（2026-08-11 决策 #4：TraceEvent 封装）。

职责：采集 Agent 执行推理事件（模型调用/工具调用/子代理启停）→ 落盘
logs/agent_trace.jsonl（trace logger，logging.py 配置）。与 ToolAudit /
TokenUsage 同族——Agent 层横切观测。

结构（决策 #4 折衷方案：框架 dict → 领域对象，单一接触面）：
- TraceEvent：领域对象（event/name/summary/run_id/parent_ids/ts）
- from_langgraph_event()：唯一接触面——langgraph astream_events dict →
  TraceEvent（框架版本漂移只改这里）
- trace_event()：入口（防御性隔离——旁路能力，任何异常不影响主链路）
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
_trace_logger = logging.getLogger("trace")  # logging.py 配置 → logs/agent_trace.jsonl


@dataclass
class TraceEvent:
    """推理层 trace 领域对象（决策 #4：结构清晰、无歧义）。

    Attributes:
        event: langgraph 事件类型（on_chat_model_start / on_tool_start / ...）
        name: 事件名（模型名/工具名/子代理名）
        summary: 内容摘要（防密钥 + 防上下文膨胀）
        run_id: 事件所属 run（区分主/子代理链）
        parent_ids: 父 run 链（层级定位）
        ts: 时间戳
        session_id: 会话 ID（可空）
    """

    event: str
    name: str
    summary: str
    run_id: str
    parent_ids: list[str] = field(default_factory=list)
    ts: str = ""
    session_id: str | None = None

    def to_json(self) -> dict:
        """序列化为扁平 JSON 行（落盘形态）。"""
        line = {
            "ts": self.ts,
            "event": self.event,
            "name": self.name,
            "summary": self.summary,
            "run_id": self.run_id,
            "parent_ids": self.parent_ids,
        }
        if self.session_id:
            line["session_id"] = self.session_id
        return line


def _truncate(text: str, limit: int = 200) -> str:
    """摘要截断（防上下文膨胀；同 ToolAudit 脱敏口径）。"""
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def from_langgraph_event(session_id: str | None, evt: dict) -> TraceEvent | None:
    """langgraph astream_events dict → TraceEvent（**唯一接触面**）。

    ⚠️ 2026-08-10 实测：on_chat_model_start 的 data.input 可能是
    {"messages": [...]} dict 或 list——dict 直接 [0] 会 KeyError: 0
    （曾中断主链路，chat 测试全红），统一归一为 list。

    Args:
        session_id: 会话 ID（None → TraceEvent.session_id 置空）
        evt: astream_events 事件 dict

    Returns:
        TraceEvent；非采集事件返回 None（不落盘）
    """
    event_type = evt.get("event", "")
    data = evt.get("data", {}) or {}
    name = evt.get("name", "")
    if event_type == "on_chat_model_start":
        messages = data.get("input") or []
        if isinstance(messages, dict):
            messages = messages.get("messages", []) or []
        first = messages[0] if isinstance(messages, list) and messages else None
        content = getattr(first, "content", None) or str(first)[:200]
        summary = f"messages={len(messages)} first={_truncate(str(content))}"
    elif event_type == "on_tool_start":
        summary = f"input={_truncate(str(data.get('input', '')))}"
    elif event_type == "on_tool_end":
        summary = f"output={_truncate(str(data.get('output', '')))}"
    elif event_type == "on_chain_start" and evt.get("metadata", {}).get("lc_agent_name"):
        summary = f"subagent_start={name}"
    elif event_type == "on_chain_end" and evt.get("metadata", {}).get("lc_agent_name"):
        summary = f"subagent_end={name}"
    else:
        return None
    return TraceEvent(
        event=event_type,
        name=name,
        summary=summary,
        run_id=evt.get("run_id", ""),
        parent_ids=evt.get("parent_ids") or [],
        ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
        session_id=session_id,
    )


def trace_event(session_id: str | None, evt: dict) -> None:
    """推理层 trace 落盘入口（只记不拦；trace logger 未配置时静默跳过）。

    ⚠️ 防御性隔离（2026-08-10 教训）：trace 是旁路能力，**任何异常不得
    影响主链路**——曾因 input 结构 KeyError 中断事件流导致 chat 全红；
    转换/序列化失败一律降级为 debug 日志。
    """
    try:
        event = from_langgraph_event(session_id, evt)
        if event is not None:
            _trace_logger.info(json.dumps(event.to_json(), ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 - 旁路采集，绝不冒泡
        logger.debug("trace 采集失败（不影响主链路）", exc_info=True)
