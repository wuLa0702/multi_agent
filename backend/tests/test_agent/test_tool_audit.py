"""ToolAuditMiddleware 测试（深化方案 §7.1 T6：工具调用审计）。

覆盖：普通工具只记名 / 敏感工具脱敏截断 / 审计异常不阻断工具执行。
request 用鸭子类型（SimpleNamespace 携带 tool_call/runtime），不依赖图执行。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from src.agent.middlewares.tool_audit import ToolAuditMiddleware


def _make_request(name: str, args: dict | None = None, session_id: str = "s1"):
    """构造鸭子类型 ToolCallRequest（仅含审计需要的字段）。"""
    runtime = SimpleNamespace(context=SimpleNamespace(session_id=session_id))
    return SimpleNamespace(tool_call={"name": name, "args": args or {}}, runtime=runtime)


async def _fake_handler(request):
    """假工具执行：原样返回 ToolMessage（调用成功信号）。"""
    return ToolMessage(content="ok", tool_call_id="tc1", name=request.tool_call["name"])


def test_tool_audit_records_name_only(audit_records) -> None:
    """T6：普通工具（非敏感）只记名 + 会话定位，不记 args。"""
    middleware = ToolAuditMiddleware()
    request = _make_request("internet_search", {"query": "测试"})

    middleware._safe_audit(request)  # 同步路径直接调内部方法（async 钩子由图执行驱动）

    rec = json.loads(audit_records[-1].getMessage())
    assert rec["layer"] == "tool_call"
    assert rec["tool"] == "internet_search"
    assert rec["thread_id"] == "s1"
    assert rec["decision"] == "audit"
    assert "args" not in rec, "非敏感工具不记参数"


def test_tool_audit_sanitizes_sensitive_args(audit_records) -> None:
    """T6：敏感工具脱敏——code → code_len；超长值截断 300 字符。"""
    middleware = ToolAuditMiddleware()

    middleware._safe_audit(_make_request("run_code_in_sandbox", {"code": "print(1)" * 100, "filename": "a.py"}))
    rec = json.loads(audit_records[-1].getMessage())
    assert "code" not in rec["args"], "code 必须脱敏（密钥纪律）"
    assert rec["args"]["code_len"] == len("print(1)" * 100)
    assert rec["args"]["filename"] == "a.py"
    assert len(rec["args"]["filename"]) <= 300


async def test_tool_audit_never_blocks(monkeypatch) -> None:
    """T6：审计 logger 打炸（monkeypatch 抛异常）→ 工具仍正常执行。"""
    middleware = ToolAuditMiddleware()
    monkeypatch.setattr(
        "src.agent.middlewares.tool_audit.audit_logger.info",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit boom")),
    )

    result = await middleware.awrap_tool_call(_make_request("internet_search"), _fake_handler)
    assert result.content == "ok", "审计失败不得阻断工具执行"
