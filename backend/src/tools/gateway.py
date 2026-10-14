"""工具调度中心：所有工具调用的统一进口（校验 / 降级 / 未来脱敏与埋点）。

**为什么建在中间件层**：内部工具与外部 MCP 工具都被包成 `BaseTool`，
**都过同一个 `awrap_tool_call` 钩子**（`ToolCallRequest.tool` 由 LangGraph 的
`ToolNode` 注入）——一处接入即同时覆盖两条路径，不必分别改造。

**与 langchain 自身校验的分工**：langchain 也会按 `args_schema` 校验，但失败会
抛 `ValidationError`（可中断 run）；本中间件在**中间件链**上再兜一层，把失败
转成**工具级错误消息**（`ToolMessage(status="error")`）返回，与项目
「工具失败降级不中断」（`06-structure-optimization.md` §4）一致。

**中间件顺序**：`[ToolAuditMiddleware(), ToolGatewayMiddleware()]`——
审计在外层（先记下本次调用，即使被网关拦也留痕），网关在内层（校验 + 可能短路）。

设计依据：`docs/决策/2026-10-14-设计-工具中心落地-v1.md` §3.1。
"""

from __future__ import annotations

import logging

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class ToolGatewayMiddleware(AgentMiddleware):
    """调用前统一校验：失败 → 日志 + 降级为错误 ToolMessage（不中断 run）。

    校验失败属**不可重试**（参数没变，重试必然再失败）——因此只记日志 +
    把原因回给模型，让它改参数，**不做重试、不做跨工具降级**。
    """

    async def awrap_tool_call(self, request, handler):
        """校验入参 → 通过则放行，失败则短路返回错误消息。"""
        schema = self._schema_of(request)
        if schema is None:
            # 无 schema（工具未注册到 ToolNode / MCP 远端工具）→ 不做本地校验，放行
            return await handler(request)
        args = (request.tool_call or {}).get("args", {}) or {}
        try:
            schema.model_validate(args)
        except ValidationError as exc:
            return self._reject(request, exc)
        return await handler(request)

    @staticmethod
    def _schema_of(request):
        """取工具的入参模型（`ToolCallRequest.tool` 由框架注入，可为 None）。"""
        tool = getattr(request, "tool", None)
        return getattr(tool, "args_schema", None) if tool is not None else None

    @staticmethod
    def _reject(request, exc: ValidationError) -> ToolMessage:
        """校验失败 → 日志 + 归一错误消息（模型据此改参数，禁止同参重试）。"""
        tool_call = request.tool_call or {}
        name = tool_call.get("name", "")
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(p) for p in first.get("loc", ())) or "参数"
        reason = first.get("msg", "参数不合法")
        logger.warning(
            "工具参数校验失败（降级不中断）：tool=%s field=%s reason=%s", name, field, reason
        )
        return ToolMessage(
            content=f"参数校验失败（{name}）：{field} {reason}。请修正参数后重试，不要用相同参数重试。",
            tool_call_id=tool_call.get("id", ""),
            status="error",
        )
