"""审核子代理单测（P0-2，计划-审核子代理-v1 §5.1 P0-2b）。

覆盖：review_agent.yaml 加载（tools 空 / model 解析 / 权限全拒绝）、
主 prompt 装配含审核指引（REVIEW_GUIDANCE 回路语义）。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from src.agent.prompts import REVIEW_GUIDANCE, build_system_prompt
from src.agent.subagents import loader
from src.agent.subagents.loader import load_subagents


class TestReviewAgentLoaded:
    async def test_review_agent_in_project(self, monkeypatch, seeded_registry, mocker) -> None:
        """真实项目目录：review_agent.yaml 加载成功（P0-2 挂载，统一编译）。

        2026-08-20 容错落地：返回 CompiledSubAgent，tools/model/permissions 断言
        改在 create_deep_agent 入参上（编译期绑定）。
        """
        from langchain_openai import ChatOpenAI

        from src.agent.subagents.guard import GuardedSubAgent

        monkeypatch.setattr(
            loader,
            "get_chat_model",
            lambda model_id: ChatOpenAI(model="deepseek-v4-flash", api_key="x", base_url="https://x"),
        )
        captured: list[dict] = []
        mocker.patch(
            "src.agent.subagents.loader.create_deep_agent",
            side_effect=lambda **kwargs: captured.append(kwargs) or object(),
        )
        specs = load_subagents()
        names = [s["name"] for s in specs]
        assert "review_agent" in names
        assert names == ["review_agent", "search_agent"]  # 文件名排序稳定

        rv = [s for s in specs if s["name"] == "review_agent"][0]
        assert isinstance(rv["runnable"], GuardedSubAgent), "子代理 runnable 应挂容错包装"
        rv_kwargs = next(k for k in captured if k["name"] == "review_agent")
        assert rv_kwargs["tools"] == []  # 审核纯 LLM 判断，无工具（计划 §2.2）
        assert rv_kwargs["model"].model == "deepseek-v4-flash"  # P1-1 model 字段解析
        perms = rv_kwargs["permissions"]
        assert "deny" in str(perms[0].mode)  # 只读产出，write 全拒绝（FilesystemPermission 对象）

    def test_review_prompt_has_revision_loop(self) -> None:
        """REVIEW_GUIDANCE 含审核回路语义：委派审核 + 修订重审 + 2 轮封顶。"""
        assert "review_agent" in REVIEW_GUIDANCE  # 委派审核
        assert "第 2 轮" in REVIEW_GUIDANCE  # 修订重审（≤2 轮）
        assert "不要无休止修订" in REVIEW_GUIDANCE  # 不收敛防死循环


class TestPromptAssembly:
    def test_build_system_prompt_contains_review_guidance(self) -> None:
        """build_system_prompt 装配含审核指引（P0-2 接入分层组装）。"""
        sp = build_system_prompt()
        assert "研报质量审核" in sp
        assert "review_agent" in sp

    def test_prompt_layers_registered(self) -> None:
        """REVIEW_GUIDANCE 已注册进可选层（PROMPT_LAYERS，裁剪优先级可追踪）。"""
        from src.agent.prompts import PROMPT_LAYERS

        assert "REVIEW_GUIDANCE" in PROMPT_LAYERS["optional"]
