"""声明式子 Agent YAML 加载器（蓝图决策 1/2：subagents/*.yaml）。

将 agent/subagents/*.yaml 解析为 deepagents SubAgent 声明（TypedDict）：
- tools 字段：名字符串 → 经 mcp.registry 查表映射为实际函数
- 非法 YAML / 缺必填字段 / 未知工具名：fail fast 抛异常
  （配置错误尽早暴露，不让 agent 带病启动）
"""

from __future__ import annotations

from pathlib import Path

import yaml
from deepagents.middleware.subagents import SubAgent

from src.mcp.registry import get_tool

SUBAGENTS_DIR = Path(__file__).resolve().parent


def load_subagents(directory: Path = SUBAGENTS_DIR) -> list[SubAgent]:
    """加载目录下全部子代理 YAML（按文件名排序，顺序稳定）。

    Args:
        directory: 子代理 YAML 目录（默认本包目录）

    Returns:
        SubAgent 声明列表（deepagents 可直接消费）

    Raises:
        yaml.YAMLError: YAML 语法非法
        KeyError: 缺少必填字段（name/description/system_prompt）或 tools 未注册
    """
    subagents: list[SubAgent] = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        subagents.append(_parse_subagent_yaml(yaml_file))
    return subagents


def _parse_subagent_yaml(yaml_file: Path) -> SubAgent:
    """解析单个 YAML 文件为 SubAgent 声明。

    Raises:
        yaml.YAMLError / KeyError: 同 load_subagents
    """
    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"子代理 YAML 顶层必须是映射：{yaml_file.name}")
    spec: SubAgent = {
        "name": data["name"],
        "description": data["description"],
        "system_prompt": data["system_prompt"],
        "tools": [get_tool(name) for name in data.get("tools", [])],
    }
    return spec
