"""工具集挂载验收测试（阶段 0.1）：唯一真相源派生结果与重构前手写清单一致。

这是"零行为变更"的锁：`tools_for_main()` 返回的主 Agent 工具集合，必须与
重构前 `_build_agent` 里的硬编码清单**逐一相同**；`hitl_tools()` 亦然。
"""

from __future__ import annotations

from src.tools import registry


def test_tools_for_main_matches_legacy_manifest() -> None:
    """主 Agent 工具集合与重构前硬编码清单一致（含顺序）。"""
    expected = [
        "run_code_in_sandbox",
        "run_command_in_sandbox",
        "upload_workspace_file",
        "download_sandbox_file",
        "run_skill_script",
        "write_wiki",
        "generate_report",
        # 2026-10-16 新增：通用工具域（门面 + 模板，无副作用、无需审批）
        "calculate",
        "current_time",
        "json_extract",
    ]
    assert [t.name for t in registry.tools_for_main()] == expected


def test_hitl_tools_matches_legacy_manifest() -> None:
    """HITL 域工具与重构前门控追加清单一致。"""
    assert [t.name for t in registry.hitl_tools()] == ["ask_human", "publish_report"]


def test_hitl_tools_excluded_from_main() -> None:
    """HITL 工具不出现在主清单里（门控由编排层追加，注册表不重复给）。"""
    main_names = {t.name for t in registry.tools_for_main()}
    assert main_names.isdisjoint({"ask_human", "publish_report"})


def test_search_tools_not_mounted_on_main() -> None:
    """搜索域工具不挂主 Agent（仅子代理按 YAML 取用），但仍可从注册表取到。"""
    main_names = {t.name for t in registry.tools_for_main()}
    assert main_names.isdisjoint({"internet_search", "fetch_url"})
    assert registry.get_tool("internet_search").name == "internet_search"


def test_spec_name_matches_registry_key() -> None:
    """元数据自洽：ToolSpec.name 必须与字典键一致（防复制粘贴手滑）。"""
    for key, spec in registry.TOOL_REGISTRY.items():
        assert spec.name == key


def test_fallback_target_is_registered() -> None:
    """fallback_to 指向的备选工具必须在注册表内（防写了不存在的工具名）。"""
    for spec in registry.TOOL_REGISTRY.values():
        if spec.fallback_to:
            assert spec.fallback_to in registry.TOOL_REGISTRY


def test_approval_flag_matches_decisions() -> None:
    """不变量：`requires_approval=True` ⟺ `allowed_decisions` 已声明。

    防"声明要审批却没写按钮"——那种配置会让审批配置构建失败（fail fast），
    或（更早的形态）静默不审批。阶段 4 审批接线的配套防线。
    """
    for name, spec in registry.TOOL_REGISTRY.items():
        assert spec.requires_approval == bool(spec.allowed_decisions), (
            f"{name}：requires_approval={spec.requires_approval} 与 "
            f"allowed_decisions={spec.allowed_decisions} 不一致"
        )
