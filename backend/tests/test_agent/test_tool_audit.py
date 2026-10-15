"""ToolAuditMiddleware 测试（深化方案 §7.1 T6 + 阶段 2.3.1 两行制）。

覆盖：普通工具只记名 / 敏感工具脱敏截断 / 审计异常不阻断工具执行 /
**两行制（start + end）/ end 行带三态与错误码与耗时 / 异常路径留痕**。
request 用鸭子类型（SimpleNamespace 携带 tool_call/runtime），不依赖图执行。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from src.tools.audit import ToolAuditMiddleware


def _make_request(name: str, args: dict | None = None, session_id: str = "s1"):
    """构造鸭子类型 ToolCallRequest（仅含审计需要的字段）。"""
    runtime = SimpleNamespace(context=SimpleNamespace(session_id=session_id))
    return SimpleNamespace(tool_call={"name": name, "args": args or {}}, runtime=runtime)


def _tool_message(name: str, status: str = "ok", error_code: str = "") -> ToolMessage:
    """构造带 artifact 信封的工具返回值（阶段 2 双通道）。"""
    return ToolMessage(
        content="ok",
        tool_call_id="tc1",
        name=name,
        artifact={"status": status, "error_code": error_code, "retryable": False, "data": None},
    )


async def _fake_handler(request):
    """假工具执行：原样返回带信封的 ToolMessage（调用成功信号）。"""
    return _tool_message(request.tool_call["name"])


def _records(audit_records) -> list[dict]:
    return [json.loads(r.getMessage()) for r in audit_records]


class TestStartLine:
    """事前行（原 P1 行为，保持不破）。"""

    def test_records_name_only(self, audit_records) -> None:
        """T6：普通工具（非敏感）只记名 + 会话定位，不记 args。"""
        ToolAuditMiddleware()._audit_start(_make_request("internet_search", {"query": "测试"}))

        rec = _records(audit_records)[-1]
        assert rec["layer"] == "tool_call"
        assert rec["phase"] == "start"
        assert rec["tool"] == "internet_search"
        assert rec["thread_id"] == "s1"
        assert rec["decision"] == "audit"
        assert "args" not in rec, "非敏感工具不记参数"

    def test_sanitizes_sensitive_args(self, audit_records) -> None:
        """T6：敏感工具脱敏——code → code_len；超长值截断 300 字符。"""
        ToolAuditMiddleware()._audit_start(
            _make_request("run_code_in_sandbox", {"code": "print(1)" * 100, "filename": "a.py"})
        )
        rec = _records(audit_records)[-1]
        assert "code" not in rec["args"], "code 必须脱敏（密钥纪律）"
        assert rec["args"]["code_len"] == len("print(1)" * 100)
        assert rec["args"]["filename"] == "a.py"
        assert len(rec["args"]["filename"]) <= 300


class TestTwoLineAudit:
    """两行制（阶段 2.3.1，审计决策 D2）：事前 + 事后各一行。"""

    async def test_writes_start_then_end(self, audit_records) -> None:
        """一次调用写两行，且 start 在前、end 在后。"""
        middleware = ToolAuditMiddleware()
        result = await middleware.awrap_tool_call(
            _make_request("internet_search"), _fake_handler
        )

        assert result.content == "ok"
        phases = [r["phase"] for r in _records(audit_records)]
        assert phases == ["start", "end"]

    @pytest.mark.parametrize(
        ("status", "error_code"),
        [
            ("ok", ""),
            ("degraded", ""),
            ("error", "rate_limited"),
        ],
    )
    async def test_end_line_carries_envelope(
        self, audit_records, status: str, error_code: str
    ) -> None:
        """end 行带 artifact 的三态与错误码（`ToolMessage.status` 盖不住 degraded）。"""
        middleware = ToolAuditMiddleware()

        async def handler(request):
            return _tool_message(request.tool_call["name"], status, error_code)

        await middleware.awrap_tool_call(_make_request("fetch_url"), handler)

        end = _records(audit_records)[-1]
        assert end["phase"] == "end"
        assert end["status"] == status
        if error_code:
            assert end["error_code"] == error_code
        else:
            assert "error_code" not in end, "无错误码时不写空字段"

    async def test_end_line_has_duration(self, audit_records) -> None:
        """end 行带耗时（毫秒整数）——两行制的主要收益之一。"""
        middleware = ToolAuditMiddleware()
        await middleware.awrap_tool_call(_make_request("internet_search"), _fake_handler)

        end = _records(audit_records)[-1]
        assert isinstance(end["duration_ms"], int)
        assert end["duration_ms"] >= 0

    async def test_end_line_without_envelope_is_unknown(self, audit_records) -> None:
        """拿不到信封（HITL 中断等）→ status=unknown，**不拿 success 冒充三态**。"""
        middleware = ToolAuditMiddleware()

        async def handler(request):
            return ToolMessage(content="human answer", tool_call_id="tc1", name="ask_human")

        await middleware.awrap_tool_call(_make_request("ask_human"), handler)

        end = _records(audit_records)[-1]
        assert end["status"] == "unknown"
        assert "error_code" not in end


class TestFailurePaths:
    """失败与异常：留痕但不吞异常。"""

    async def test_exception_records_end_then_reraises(self, audit_records) -> None:
        """工具抛异常 → 先记 end（error + 归类错误码），再把异常原样抛出。"""
        middleware = ToolAuditMiddleware()

        async def boom(request):
            raise RuntimeError("工具炸了")

        with pytest.raises(RuntimeError, match="工具炸了"):
            await middleware.awrap_tool_call(_make_request("fetch_url"), boom)

        end = _records(audit_records)[-1]
        assert end["phase"] == "end"
        assert end["status"] == "error"
        assert end["error_code"] == "internal", "未识别异常归 internal（error_map 口径）"

    async def test_cancellation_is_recorded(self, audit_records) -> None:
        """取消（进程被杀场景）也算「开始了没结束」，必须留痕——D2 的核心动机。"""
        middleware = ToolAuditMiddleware()

        async def cancelled(request):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            await middleware.awrap_tool_call(_make_request("run_command_in_sandbox"), cancelled)

        assert _records(audit_records)[-1]["phase"] == "end"

    async def test_audit_failure_never_blocks(self, monkeypatch) -> None:
        """T6：审计 logger 打炸 → 工具仍正常执行（两行都炸也不阻断）。"""
        middleware = ToolAuditMiddleware()
        monkeypatch.setattr(
            "src.tools.audit.audit_logger.info",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit boom")),
        )

        result = await middleware.awrap_tool_call(
            _make_request("internet_search"), _fake_handler
        )
        assert result.content == "ok", "审计失败不得阻断工具执行"

    async def test_audit_failure_does_not_mask_tool_error(self, monkeypatch) -> None:
        """审计自身炸了，也不能把工具的真实异常盖掉（异常必须原样传出）。"""
        middleware = ToolAuditMiddleware()
        monkeypatch.setattr(
            "src.tools.audit.audit_logger.info",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit boom")),
        )

        async def boom(request):
            raise ValueError("工具真实故障")

        with pytest.raises(ValueError, match="工具真实故障"):
            await middleware.awrap_tool_call(_make_request("fetch_url"), boom)
