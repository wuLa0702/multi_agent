"""run_code_in_sandbox 池化工具测试（能力计划 §5 + 评审 1 修复用例）。

覆盖（全 mock，不连 docker）：
- 池化路径：get_sandbox + run_script 调用链
- 非池化：try/finally destroy 必被调（含执行异常路径——评审问题 1）
- SandboxFullError → 友好错误返回；sandbox_url 空 → 降级提示
- _thread_id_from：config 注入 / 回落 default
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.config import settings
from src.mcp.tools import sandbox_tool
from src.sandbox.pool import SandboxFullError


@pytest.fixture
def fake_env(monkeypatch):
    """沙箱工具测试环境：mock adapter + pool + sandbox_url。"""
    monkeypatch.setattr(settings, "sandbox_url", "http://localhost:8080")
    monkeypatch.setattr(settings, "sandbox_pool_enabled", True)
    calls = {"run_script": 0, "destroy": 0, "create": 0}

    class _FakeAdapter:
        def run_script(self, sandbox, files, entry):
            calls["run_script"] += 1
            return f"ok:{entry}"

        def create_sandbox(self, *a, **k):
            calls["create"] += 1
            return SimpleNamespace(id="sb-x")

        def destroy(self, sandbox) -> None:
            calls["destroy"] += 1

    monkeypatch.setattr(sandbox_tool, "sandbox_adapter", _FakeAdapter())
    return calls


def test_tool_pooled_path(fake_env, monkeypatch) -> None:
    """池化路径：get_sandbox 命中 → run_script 执行；沙箱不被 destroy（池托管）。"""
    pool_sb = SimpleNamespace(id="sb-pooled")
    monkeypatch.setattr(
        sandbox_tool.sandbox_pool, "get_sandbox", lambda tid: pool_sb
    )

    result = sandbox_tool.run_code_in_sandbox("print(1)", filename="a.py")

    assert result == "ok:a.py"
    assert fake_env["run_script"] == 1
    assert fake_env["destroy"] == 0, "池化模式沙箱由池托管，工具不销毁"


def test_tool_pooled_uses_thread_id(fake_env, monkeypatch) -> None:
    """会话定位：config 携带 thread_id → 池按会话取沙箱。"""
    got: list[str] = []
    monkeypatch.setattr(
        sandbox_tool.sandbox_pool, "get_sandbox", lambda tid: got.append(tid) or SimpleNamespace(id="sb")
    )

    sandbox_tool.run_code_in_sandbox(
        "x", config={"configurable": {"thread_id": "sess-1"}}
    )

    assert got == ["sess-1"], "thread_id 应从执行 config 提取"


def test_tool_non_pooled_destroys_on_success(fake_env, monkeypatch) -> None:
    """评审 1：非池化 + 执行成功 → destroy 仍被调（防泄漏，不依赖 TTL）。"""
    monkeypatch.setattr(settings, "sandbox_pool_enabled", False)

    result = sandbox_tool.run_code_in_sandbox("print(1)")

    assert result == "ok:script.py"
    assert fake_env["create"] == 1
    assert fake_env["destroy"] == 1, "非池化模式必须销毁（评审问题 1）"


def test_tool_non_pooled_destroys_on_error(fake_env, monkeypatch) -> None:
    """评审 1：非池化 + 执行异常 → finally 仍销毁。"""
    monkeypatch.setattr(settings, "sandbox_pool_enabled", False)
    monkeypatch.setattr(
        sandbox_tool.sandbox_adapter, "run_script",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("exec boom")),
    )

    result = sandbox_tool.run_code_in_sandbox("raise")

    assert "沙箱执行失败" in result
    assert fake_env["destroy"] == 1, "异常路径也必须销毁（finally 保证）"


def test_tool_sandbox_full_friendly(fake_env, monkeypatch) -> None:
    """池上限：SandboxFullError → 友好错误字符串（agent 可换方案，不中断 run）。"""
    monkeypatch.setattr(
        sandbox_tool.sandbox_pool, "get_sandbox",
        lambda tid: (_ for _ in ()).throw(SandboxFullError("沙箱资源已满（上限 6 个并发会话）")),
    )

    result = sandbox_tool.run_code_in_sandbox("x")

    assert "沙箱资源已满" in result


def test_tool_no_url_degraded(monkeypatch) -> None:
    """兼容：sandbox_url 空 → 降级提示（不连沙箱）。"""
    monkeypatch.setattr(settings, "sandbox_url", "")

    assert "沙箱不可用" in sandbox_tool.run_code_in_sandbox("x")


def test_thread_id_from_config() -> None:
    """会话定位：config 有 thread_id → 取出；无 config → 回落 default。"""
    assert sandbox_tool._thread_id_from({"configurable": {"thread_id": "s1"}}) == "s1"
    assert sandbox_tool._thread_id_from({"configurable": {}}) == "default"
    assert sandbox_tool._thread_id_from(None) == "default"
