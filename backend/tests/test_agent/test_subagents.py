"""子代理 loader 测试（2026-08-20 容错落地：统一预编译 + 容错包装）。

覆盖：
- P1：YAML 显式 permissions 透传 / 模板兜底 / 无声明继承父级（_parse_subagent_yaml）
- 统一编译：load_subagents 返回 CompiledSubAgent，StateBackend + 权限 + GuardedSubAgent
"""

from __future__ import annotations

from pathlib import Path

from src.agent.subagents import loader
from src.agent.subagents.guard import GuardedSubAgent


def _write_yaml(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / f"{name}.yaml"
    f.write_text(body, encoding="utf-8")
    return f


_BASE = """name: {name}
description: 测试子代理
system_prompt: 测试提示词
tools: []
"""


def test_parse_permissions_passthrough(tmp_path) -> None:
    """P1：YAML 显式 permissions 透传；模板兜底；无声明不注入键（继承父级）。"""
    explicit = _write_yaml(
        tmp_path, "explicit_agent",
        _BASE.format(name="explicit_agent")
        + "permissions:\n  - operations: [read]\n    paths: [\"/memories/**\"]\n    mode: deny\n",
    )
    templated = _write_yaml(tmp_path, "search_agent", _BASE.format(name="search_agent"))
    inherited = _write_yaml(tmp_path, "other_agent", _BASE.format(name="other_agent"))

    specs = {loader._parse_subagent_yaml(f)["name"]: loader._parse_subagent_yaml(f) for f in [explicit, templated, inherited]}
    # YAML 显式与模板注入的都是 FilesystemPermission 对象（deepagents 消费对象非 dict）
    assert specs["explicit_agent"]["permissions"][0].paths == ["/memories/**"], "YAML 显式声明优先"
    assert specs["search_agent"]["permissions"][0].mode == "deny", "模板兜底（search_agent 写拒绝）"
    assert "permissions" not in specs["other_agent"], "无模板的子代理不注入键（继承父级）"


def test_compile_guarded_state_backend(tmp_path, mocker) -> None:
    """统一编译：StateBackend + 写拒绝权限 + runnable 为 GuardedSubAgent。"""
    _write_yaml(tmp_path, "search_agent", _BASE.format(name="search_agent"))
    captured: dict = {}
    mock_create = mocker.patch(
        "src.agent.subagents.loader.create_deep_agent",
        side_effect=lambda **kwargs: captured.update(kwargs) or object(),
    )

    results = loader.load_subagents(directory=tmp_path, model=object())

    assert mock_create.call_count == 1
    from deepagents.backends import StateBackend

    assert isinstance(captured["backend"], StateBackend), "子代理应绑独立内存 backend"
    assert captured["permissions"][0].mode == "deny", "编译子代理应带写拒绝权限"
    assert captured["system_prompt"] == "测试提示词"
    assert captured["name"] == "search_agent"
    assert list(results[0]) == ["name", "description", "runnable"], "CompiledSubAgent 三字段（无 system_prompt）"
    assert isinstance(results[0]["runnable"], GuardedSubAgent), "子代理 runnable 应挂容错包装"
