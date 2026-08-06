"""HITL 审批配置 + Rubric 模板库/门控单测（设计文档 §8 用例 1/2/7/8）。

覆盖：
- hitl.py：enabled=False → None（不配 interrupt_on）；enabled=True → 按风险分级配置
- rubrics.py：模板库三预置为换行 checklist；rubric_enabled=False → 不挂载
"""

from __future__ import annotations

import pytest

from src.agent.hitl import HITL_INTERRUPT_ON, build_hitl_interrupt_on
from src.agent.rubrics import RUBRIC_TEMPLATES, build_rubric_middleware


class TestHitlConfig:
    """HITL 审批分级配置（设计 §5.1 / §8 用例 1-2；纯函数，enabled 显式传参）。"""

    def test_disabled_returns_none(self) -> None:
        """enabled=False → None（create_deep_agent 不配 interrupt_on）。"""
        assert build_hitl_interrupt_on(False) is None

    def test_enabled_returns_risk_graded_config(self) -> None:
        """enabled=True → interrupt_on 含沙箱工具且按风险分级。"""
        config = build_hitl_interrupt_on(True)

        assert config is not None
        # InterruptOnConfig 是 TypedDict（dict 形态），按键访问
        # 高危：任意代码执行 → approve + edit + reject
        assert config["run_code_in_sandbox"]["allowed_decisions"] == ["approve", "edit", "reject"]
        # 中危：命令执行/文件/技能 → approve + reject（不许 edit）
        assert config["run_command_in_sandbox"]["allowed_decisions"] == ["approve", "reject"]
        assert config["upload_workspace_file"]["allowed_decisions"] == ["approve", "reject"]
        assert config["download_sandbox_file"]["allowed_decisions"] == ["approve", "reject"]
        assert config["run_skill_script"]["allowed_decisions"] == ["approve", "reject"]
        # 只读：不审批
        assert config["internet_search"] is False


class TestRubricTemplates:
    """Rubric 预置模板库（设计 §5.5 / §8 用例 8）。"""

    def test_three_templates_exist(self) -> None:
        """三个预置模板：code_review / report_completeness / source_veracity。"""
        assert set(RUBRIC_TEMPLATES) == {
            "code_review",
            "report_completeness",
            "source_veracity",
        }

    @pytest.mark.parametrize("name", ["code_review", "report_completeness", "source_veracity"])
    def test_template_is_checklist(self, name: str) -> None:
        """模板为换行 checklist（官方 rubric 字符串形态，每行一个标准）。"""
        text = RUBRIC_TEMPLATES[name]
        lines = [l for l in text.splitlines() if l.strip()]
        assert len(lines) >= 3, f"{name} 至少 3 条标准"
        assert all(l.startswith("- ") for l in lines), f"{name} 每行以 '- ' 开头"


class TestRubricMiddlewareBuild:
    """Rubric 挂载门控（设计 §5.4 / §8 用例 7）。"""

    def test_disabled_returns_empty(self, monkeypatch) -> None:
        """rubric_enabled=False → 空列表（不挂载 RubricMiddleware）。"""
        monkeypatch.setattr("src.agent.rubrics.settings.rubric_enabled", False)
        assert build_rubric_middleware() == []

    def test_enabled_returns_middleware(self, monkeypatch, mocker) -> None:
        """rubric_enabled=True → [RubricMiddleware]，grader 传实例（不实调 API）。"""
        monkeypatch.setattr("src.agent.rubrics.settings.rubric_enabled", True)
        fake_model = object()
        # rubrics.py 函数内延迟 import（防循环依赖）→ patch 源头模块
        mocker.patch("src.llm.adapter.get_chat_model", return_value=fake_model)
        mock_mw = mocker.patch("deepagents.RubricMiddleware")

        result = build_rubric_middleware()

        assert len(result) == 1
        mock_mw.assert_called_once()
        _, kwargs = mock_mw.call_args
        assert kwargs["model"] is fake_model, "grader 必须传实例（国产 base_url）"
        assert kwargs["max_iterations"] == 3
