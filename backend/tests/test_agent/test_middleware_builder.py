"""中间件装配单测（阶段 3 收口）：`build_middlewares()` 的**顺序不变量**。

为什么单独锁顺序：改造前顺序靠 `main_agent` 里的注释维持（"审计在外层，网关在内层"），
重排一次就得人肉复核。收口后顺序是**程序化约束**——本文件把它钉住。

顺带锁住装配点的价值主张：**新增横切能力只改 builder**（main_agent 不再动）。
"""

from __future__ import annotations

from src.agent.middlewares.builder import build_middlewares
from src.agent.middlewares.token_usage import TokenUsageMiddleware
from src.llm.redact import RedactMiddleware
from src.tools.guardrails.audit import ToolAuditMiddleware
from src.tools.guardrails.gateway import ToolGatewayMiddleware


def _model_mw() -> object:
    """模型选择中间件替身（真实那个由编排层注入，这里只需能定位）。"""
    return object()


def _types() -> list[type]:
    return [type(m) for m in build_middlewares(_model_mw())]


def test_model_middleware_is_outermost() -> None:
    """模型选择必须在最外层：先定模型，后续环节才有一致的模型上下文。"""
    middlewares = build_middlewares(_model_mw())
    assert type(middlewares[0]) is object, "第 0 位应是注入的模型中间件"


def test_redact_is_right_after_model() -> None:
    """出站脱敏紧随模型选择：模型已定 → 脱敏本次入站消息 → 再交下游。"""
    types = _types()
    assert types[1] is RedactMiddleware
    assert types[2] is TokenUsageMiddleware


def test_audit_is_outer_than_gateway() -> None:
    """工具审计在网关**外层**：被网关拦（短路）时审计也已先留痕。"""
    types = _types()
    assert types.index(ToolAuditMiddleware) < types.index(ToolGatewayMiddleware)


def test_no_none_entries() -> None:
    """不变量：链里不能有 None（门控型构建函数可能返回空列表，但不能返回 None）。"""
    assert all(m is not None for m in build_middlewares(_model_mw()))


def test_order_is_stable_across_calls() -> None:
    """幂等：多次装配顺序一致（避免"每次编译图顺序不同"的隐患）。"""
    assert _types() == _types()
