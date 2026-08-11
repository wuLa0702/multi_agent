"""Permissions 权限模板测试（深化方案 §7.1 T2 上层规则）。

覆盖：主 Agent deny 模板 / interrupt 开关门控（默认不激活）/ 子代理整体替换父级。
"""

from __future__ import annotations

from src.core.permissions import build_main_permissions, build_subagent_permissions


def test_main_permissions_deny_skills_write() -> None:
    """T2：主 Agent 模板——/skills/** 写 deny（规则序：deny 在最前）。"""
    perms = build_main_permissions()
    assert perms[0].mode == "deny"
    assert perms[0].operations == ["write"]
    assert perms[0].paths == ["/skills/**"]


def test_main_permissions_interrupt_dormant_by_default(monkeypatch) -> None:
    """T2：interrupt 规则默认不激活；hitl_enabled 翻转后出现（P0 HITL 设计 §5.6：删常量统一门控）。"""
    from src.core.config import settings

    perms = build_main_permissions()
    assert len(perms) == 1, "默认仅 deny 规则，interrupt 不得进入返回列表"
    assert all(p.mode != "interrupt" for p in perms)

    monkeypatch.setattr(settings, "hitl_enabled", True)
    perms_on = build_main_permissions()
    assert any(p.mode == "interrupt" for p in perms_on)
    interrupt = [p for p in perms_on if p.mode == "interrupt"][0]
    assert interrupt.paths == ["/memories/private/**", "/memories/secrets/**"]


def test_subagent_permissions_replace_parent() -> None:
    """T2：子代理权限整体替换父级（graph.py:663 语义）——search_agent 写拒绝，未知继承。"""
    search = build_subagent_permissions("search_agent")
    assert len(search) == 1
    assert search[0].mode == "deny"
    assert search[0].paths == ["/**"]
    assert build_subagent_permissions("unknown_agent") == []


def test_deny_paths_scoped_to_routes() -> None:
    """T2：deny 规则路径限定在路由前缀内（_all_paths_scoped_to_routes 兼容）。

    主 Agent 的 deny 规则必须挂在 CompositeBackend 路由前缀下——路径前缀与
    backend 虚拟路由一一对应，权限才落到实际文件系统根。
    """
    routes = ("/skills/", "/memories/", "/exports/")
    for rule in build_main_permissions():
        for p in rule.paths:
            assert any(p.startswith(r) for r in routes), f"权限路径未限定在路由前缀内：{p}"
