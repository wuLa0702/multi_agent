"""调度中心单测（阶段 1.1）：入参校验失败 → 降级 ToolMessage；通过 → 放行。"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from pydantic import BaseModel

from src.tools.gateway import ToolGatewayMiddleware


class _Args(BaseModel):
    """最小入参模型（模拟工具 args_schema）。"""

    n: int


class _FakeTool:
    """最小 BaseTool 替身（只暴露 args_schema）。"""

    def __init__(self, schema) -> None:
        self.args_schema = schema


def _request(args: dict, tool) -> SimpleNamespace:
    """构造最小 ToolCallRequest（toll_call / tool 两个字段够用）。"""
    return SimpleNamespace(tool_call={"name": "t", "args": args, "id": "call-1"}, tool=tool)


async def test_valid_args_passes_through() -> None:
    """参数合法 → 调 handler，原样返回。"""
    mw = ToolGatewayMiddleware()
    called: list = []

    async def handler(req):
        called.append(req)
        return ToolMessage(content="ok", tool_call_id="call-1")

    out = await mw.awrap_tool_call(_request({"n": 1}, _FakeTool(_Args)), handler)
    assert called, "合法参数应放行到 handler"
    assert out.content == "ok"


async def test_invalid_args_short_circuits() -> None:
    """参数非法 → 短路（不调 handler），返回 error ToolMessage。"""
    mw = ToolGatewayMiddleware()
    called: list = []

    async def handler(req):
        called.append(req)
        return ToolMessage(content="ok", tool_call_id="call-1")

    out = await mw.awrap_tool_call(_request({"n": "不是整数"}, _FakeTool(_Args)), handler)
    assert not called, "校验失败不得调用 handler"
    assert isinstance(out, ToolMessage)
    assert out.status == "error"
    assert "参数校验失败" in out.content
    assert out.tool_call_id == "call-1"


async def test_missing_required_arg_short_circuits() -> None:
    """缺必填参数 → 短路。"""
    mw = ToolGatewayMiddleware()

    async def handler(req):  # pragma: no cover - 不应被调用
        raise AssertionError("不应调用 handler")

    out = await mw.awrap_tool_call(_request({}, _FakeTool(_Args)), handler)
    assert isinstance(out, ToolMessage) and out.status == "error"


async def test_no_schema_passes_through() -> None:
    """无 schema（工具未注册 / MCP 远端工具）→ 放行，不做本地校验。"""
    mw = ToolGatewayMiddleware()
    called: list = []

    async def handler(req):
        called.append(req)
        return ToolMessage(content="ok", tool_call_id="call-1")

    out = await mw.awrap_tool_call(_request({"x": 1}, None), handler)
    assert called, "无 schema 应放行"
    assert out.content == "ok"
