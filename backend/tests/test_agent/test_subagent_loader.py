"""子代理 YAML 加载器单测：agent/subagents/loader.py。

覆盖：正常解析（含 tools 查表映射）、缺必填字段、未知工具名、
非法 YAML、目录加载顺序稳定。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.subagents import loader
from src.agent.subagents.loader import _parse_subagent_yaml, load_subagents


def _write_yaml(tmp_path: Path, content: str, name: str = "agent.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestParseSubagentYaml:
    """单个 YAML 解析。"""

    def test_parse_valid_yaml(self, tmp_path: Path) -> None:
        """合法 YAML：tools 名字符串映射为注册表函数。"""
        yaml_file = _write_yaml(
            tmp_path,
            """name: test_agent
description: 测试子代理
system_prompt: 你是测试代理。
tools:
  - internet_search
""",
        )
        spec = _parse_subagent_yaml(yaml_file)

        assert spec["name"] == "test_agent"
        assert spec["tools"] == [spec["tools"][0]]  # 单工具
        assert spec["tools"][0].__name__ == "internet_search"

    def test_missing_required_field_fails_fast(self, tmp_path: Path) -> None:
        """缺 description 字段：KeyError（fail fast）。"""
        yaml_file = _write_yaml(
            tmp_path,
            """name: test_agent
system_prompt: 你是测试代理。
""",
        )
        with pytest.raises(KeyError):
            _parse_subagent_yaml(yaml_file)

    def test_unknown_tool_name_fails_fast(self, tmp_path: Path) -> None:
        """tools 引用未注册工具：KeyError（查 registry 表）。"""
        yaml_file = _write_yaml(
            tmp_path,
            """name: test_agent
description: 测试子代理
system_prompt: 你是测试代理。
tools:
  - no_such_tool
""",
        )
        with pytest.raises(KeyError, match="no_such_tool"):
            _parse_subagent_yaml(yaml_file)

    def test_invalid_yaml_fails_fast(self, tmp_path: Path) -> None:
        """语法非法 YAML：yaml.YAMLError。"""
        yaml_file = _write_yaml(tmp_path, "name: [unclosed\n")
        with pytest.raises(Exception):
            _parse_subagent_yaml(yaml_file)

    def test_empty_tools_defaults(self, tmp_path: Path) -> None:
        """tools 缺省为空列表（纯对话子代理合法）。"""
        yaml_file = _write_yaml(
            tmp_path,
            """name: talker
description: 纯对话
system_prompt: 你好。
""",
        )
        spec = _parse_subagent_yaml(yaml_file)
        assert spec["tools"] == []


class TestLoadSubagents:
    """目录批量加载。"""

    def test_load_skips_non_yaml_files(self, tmp_path: Path) -> None:
        """只加载 *.yaml，忽略其他文件。"""
        _write_yaml(
            tmp_path,
            """name: a
description: A
system_prompt: A 代理。
""",
            name="a.yaml",
        )
        _write_yaml(
            tmp_path,
            """name: b
description: B
system_prompt: B 代理。
""",
            name="b.yaml",
        )
        (tmp_path / "notes.txt").write_text("not a subagent", encoding="utf-8")

        specs = load_subagents(tmp_path)
        assert [s["name"] for s in specs] == ["a", "b"]  # 文件名排序，顺序稳定

    async def test_load_project_subagents(self, monkeypatch, seeded_registry) -> None:
        """真实项目目录：子代理 YAML 全部加载（tools 映射 + model 字段经 DB 解析）。

        2026-08-10 P0-2：新增 review_agent.yaml——断言更新为双子代理
        （文件名排序：review_agent < search_agent），审核子代理单测见
        tests/test_agent/test_review_agent.py。
        """
        from langchain_openai import ChatOpenAI

        monkeypatch.setattr(
            loader,
            "get_chat_model",
            lambda model_id: ChatOpenAI(model="deepseek-v4-flash", api_key="x", base_url="https://x"),
        )
        specs = load_subagents()
        assert [s["name"] for s in specs] == ["review_agent", "search_agent"]
        assert specs[1]["tools"][0].__name__ == "internet_search"
        assert specs[1]["model"].model == "deepseek-v4-flash"


class TestSubagentModelField:
    """P1-1：YAML model 字段（按任务选模型，构建期绑定）。"""

    async def test_model_field_resolves_via_db(
        self, monkeypatch, seeded_registry, tmp_path: Path
    ) -> None:
        """声明 model → 按 model_name 反查 DB → get_chat_model(model_id) 构造实例。"""
        from langchain_openai import ChatOpenAI

        captured: dict[str, int | None] = {"model_id": None}
        monkeypatch.setattr(
            loader,
            "get_chat_model",
            lambda model_id: captured.__setitem__("model_id", model_id)
            or ChatOpenAI(model="deepseek-v4-flash", api_key="x", base_url="https://x"),
        )
        yaml_file = _write_yaml(
            tmp_path,
            """name: searcher
description: 搜索子代理
system_prompt: 你负责搜索。
model: deepseek-v4-flash
""",
        )
        spec = _parse_subagent_yaml(yaml_file)

        # 经 DB 反查得到 deepseek-v4-flash 的模型配置
        assert captured["model_id"] is not None
        cfg = seeded_registry.get_model(captured["model_id"])
        assert cfg is not None and cfg.model_name == "deepseek-v4-flash"
        # spec 携带构造好的模型实例
        assert isinstance(spec["model"], ChatOpenAI)
        assert spec["model"].model == "deepseek-v4-flash"

    async def test_unknown_model_name_fails_fast(
        self, monkeypatch, seeded_registry, tmp_path: Path
    ) -> None:
        """声明 DB 中不存在的 model_name → ValueError（fail fast，不构造模型）。"""
        calls: list = []
        monkeypatch.setattr(loader, "get_chat_model", lambda model_id: calls.append(model_id))
        yaml_file = _write_yaml(
            tmp_path,
            """name: searcher
description: 搜索子代理
system_prompt: 你负责搜索。
model: ghost-model
""",
        )
        with pytest.raises(ValueError, match="ghost-model"):
            _parse_subagent_yaml(yaml_file)
        assert calls == []  # 未到达构造步骤

    async def test_no_model_field_inherits_main(
        self, monkeypatch, seeded_registry, tmp_path: Path
    ) -> None:
        """未声明 model → spec 不含 model 键（继承主 agent 模型）。"""
        monkeypatch.setattr(loader, "get_chat_model", lambda model_id: None)
        yaml_file = _write_yaml(
            tmp_path,
            """name: talker
description: 纯对话
system_prompt: 你好。
""",
        )
        spec = _parse_subagent_yaml(yaml_file)
        assert "model" not in spec
