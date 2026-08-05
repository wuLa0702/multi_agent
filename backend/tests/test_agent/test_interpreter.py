"""解释器挂载逻辑测试（测试计划 §3.2：P2 逻辑组 T07-T11）。

⚠️ 环境阻塞（2026-08-05 实测）：Python 3.14 无 bsdiff4 wheel——真 QuickJS
执行不可测（T12-T14 保留待环境）；本文件全部 mock 路径（惰性 import 逻辑）。
"""

from __future__ import annotations

import types

import pytest

from src.agent.main_agent import _parse_ptc_whitelist
from src.core.config import settings


# ── T07/T08：PTC 白名单解析与校验 ──

def test_ptc_whitelist_parses_normal() -> None:
    """T07：白名单内工具解析通过（空白容忍）；空配置 → 空列表。"""
    assert _parse_ptc_whitelist("internet_search") == ["internet_search"]
    assert _parse_ptc_whitelist(" internet_search ,internet_search ") == [
        "internet_search", "internet_search",
    ]
    assert _parse_ptc_whitelist("") == []


@pytest.mark.parametrize(
    "bad",
    ["write_file", "run_code_in_sandbox", "run_command_in_sandbox",
     "upload_workspace_file", "download_sandbox_file", "edit_file", "delete",
     "a", "b", "unknown_tool"],
)
def test_ptc_whitelist_rejects_non_readonly(bad: str) -> None:
    """T08：白名单外工具（文件/沙箱/未知）→ ValueError（默认拒绝语义）。

    白名单语义（2026-08-05 反转）：不是黑名单兜底——名单外一律拒绝，
    新增工具天然安全，无需维护黑名单。
    """
    with pytest.raises(ValueError, match="interpreter_ptc 只允许只读白名单工具"):
        _parse_ptc_whitelist(bad)


def test_ptc_whitelist_keeps_search_when_mixed() -> None:
    """T08 边界：只读 + 名单外混合 → 仍拒绝（不是部分放行）。"""
    with pytest.raises(ValueError):
        _parse_ptc_whitelist("internet_search, run_code_in_sandbox")


# ── T09/T10：解释器挂载开关与惰性降级 ──

def test_interpreter_disabled_middleware_stack_unchanged(mocker) -> None:
    """T09：interpreter_enabled=False → middleware 栈无解释器（现状不变）。"""
    from src.agent import main_agent

    mocker.patch("src.agent.main_agent.get_chat_model", return_value=object())
    mock_create = mocker.patch(
        "src.agent.main_agent.create_deep_agent", side_effect=lambda *a, **k: object()
    )

    main_agent._build_agent("t1")

    _, kwargs = mock_create.call_args
    middleware_types = [type(m) for m in kwargs["middleware"]]
    assert main_agent.ToolAuditMiddleware in middleware_types
    assert all("CodeInterpreter" not in type(m).__name__ for m in kwargs["middleware"])


def test_interpreter_enabled_without_quickjs_raises_clear_error(
    mocker, monkeypatch
) -> None:
    """T10：enabled=True + quickjs 缺失 → 明确错误提示（环境阻塞指引，非静默炸）。"""
    from src.agent import main_agent

    monkeypatch.setattr(settings, "interpreter_enabled", True)
    mocker.patch(
        "src.agent.main_agent.get_chat_model", return_value=object()
    )
    mocker.patch(
        "src.agent.main_agent.load_subagents", return_value=[]
    )
    # 模拟 quickjs 未安装（import 抛 ImportError）
    mocker.patch(
        "builtins.__import__",
        side_effect=ImportError("No module named 'langchain_quickjs'"),
    )

    with pytest.raises(RuntimeError, match="bsdiff4"):
        main_agent._build_agent("t1")


def test_interpreter_enabled_passes_ptc_and_order(mocker, monkeypatch) -> None:
    """T11：enabled=True + quickjs 可用 → CodeInterpreter 挂载在 ToolAudit 后（外层先审计）。"""
    from src.agent import main_agent

    monkeypatch.setattr(settings, "interpreter_enabled", True)
    monkeypatch.setattr(settings, "interpreter_ptc", "internet_search")

    class _FakeInterpreter:
        """模拟 CodeInterpreterMiddleware（不 import 真包）。"""

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    mocker.patch(
        "src.agent.main_agent.get_chat_model", return_value=object()
    )
    mocker.patch(
        "src.agent.main_agent.load_subagents", return_value=[]
    )
    fake_module = types.ModuleType("langchain_quickjs")
    fake_module.CodeInterpreterMiddleware = _FakeInterpreter
    mocker.patch.dict("sys.modules", {"langchain_quickjs": fake_module})
    mock_create = mocker.patch(
        "src.agent.main_agent.create_deep_agent", side_effect=lambda *a, **k: object()
    )

    main_agent._build_agent("t1")

    _, kwargs = mock_create.call_args
    middleware = kwargs["middleware"]
    interpreter = [m for m in middleware if isinstance(m, _FakeInterpreter)]
    assert len(interpreter) == 1, "解释器应挂载"
    assert interpreter[0].kwargs["ptc"] == ["internet_search"]
    assert interpreter[0].kwargs["mode"] == "turn"
    # 顺序断言（评审问题 2.2 预案）：ToolAudit 在 CodeInterpreter 之前（外层先审计）
    audit_idx = next(i for i, m in enumerate(middleware)
                     if isinstance(m, main_agent.ToolAuditMiddleware))
    interp_idx = next(i for i, m in enumerate(middleware) if isinstance(m, _FakeInterpreter))
    assert audit_idx < interp_idx, "ToolAudit 应在 CodeInterpreter 前（外层包裹，eval 先审计）"
