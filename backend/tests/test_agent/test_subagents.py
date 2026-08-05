"""子代理 loader 测试（深化方案 §7.1 T2 子代理权限 + T5 P2 隔离）。

覆盖：
- P1：YAML 显式 permissions 透传 / 模板兜底 / 无声明继承父级
- P2：SUBAGENT_ISOLATION=True 编译 CompiledSubAgent（独立 StateBackend + 权限）
- P2：隔离模式必须传入 model（fail fast）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.subagents import loader
from src.core.config import settings


def _write_yaml(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / f"{name}.yaml"
    f.write_text(body, encoding="utf-8")
    return f


_BASE = """name: {name}
description: 测试子代理
system_prompt: 测试提示词
tools: []
"""


def test_yaml_permissions_passthrough(tmp_path) -> None:
    """T2：YAML 显式 permissions 透传；模板兜底；无声明不注入键（继承父级）。"""
    explicit = _write_yaml(
        tmp_path, "explicit_agent",
        _BASE.format(name="explicit_agent")
        + "permissions:\n  - operations: [read]\n    paths: [\"/memories/**\"]\n    mode: deny\n",
    )
    templated = _write_yaml(tmp_path, "search_agent", _BASE.format(name="search_agent"))
    inherited = _write_yaml(tmp_path, "other_agent", _BASE.format(name="other_agent"))

    specs = loader.load_subagents(directory=tmp_path)

    by_name = {s["name"]: s for s in specs}
    # YAML 显式与模板注入的都是 FilesystemPermission 对象（deepagents 消费对象非 dict）
    assert by_name["explicit_agent"]["permissions"][0].paths == ["/memories/**"], "YAML 显式声明优先"
    assert by_name["search_agent"]["permissions"][0].mode == "deny", "模板兜底（search_agent 写拒绝）"
    assert "permissions" not in by_name["other_agent"], "无模板的子代理不注入键（继承父级）"


def test_subagent_isolation_requires_model(tmp_path, monkeypatch) -> None:
    """T5：SUBAGENT_ISOLATION=True 未传 model → RuntimeError（fail fast）。"""
    monkeypatch.setattr(settings, "subagent_isolation", True)
    _write_yaml(tmp_path, "search_agent", _BASE.format(name="search_agent"))

    with pytest.raises(RuntimeError, match="SUBAGENT_ISOLATION"):
        loader.load_subagents(directory=tmp_path)


def test_subagent_isolation_compiles_state_backend(tmp_path, monkeypatch, mocker) -> None:
    """T5：P2 编译——backend 为 StateBackend、permissions 含 write-deny、返回 runnable 形态。"""
    monkeypatch.setattr(settings, "subagent_isolation", True)
    _write_yaml(tmp_path, "search_agent", _BASE.format(name="search_agent"))
    captured: dict = {}
    mock_create = mocker.patch(
        "src.agent.subagents.loader.create_deep_agent",
        side_effect=lambda **kwargs: captured.update(kwargs) or object(),
    )

    results = loader.load_subagents(directory=tmp_path, model=object())

    assert mock_create.call_count == 1
    from deepagents.backends import StateBackend

    assert isinstance(captured["backend"], StateBackend), "P2 子代理应绑独立内存 backend"
    assert captured["permissions"][0].mode == "deny", "编译子代理应带写拒绝权限"
    assert captured["system_prompt"] == "测试提示词"
    assert captured["name"] == "search_agent"
    assert list(results[0]) == ["name", "description", "runnable"], "CompiledSubAgent 三字段（无 system_prompt）"
