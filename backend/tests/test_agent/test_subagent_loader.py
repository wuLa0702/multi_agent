"""子代理 YAML 加载器单测：agent/subagents/loader.py。

覆盖：正常解析（含 tools 查表映射）、缺必填字段、未知工具名、
非法 YAML、目录加载顺序稳定。
"""

from __future__ import annotations

from pathlib import Path

import pytest

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

    def test_load_project_subagents(self) -> None:
        """真实项目目录：search_agent.yaml 加载成功（tools 映射到 internet_search）。"""
        specs = load_subagents()
        assert [s["name"] for s in specs] == ["search_agent"]
        assert specs[0]["tools"][0].__name__ == "internet_search"
