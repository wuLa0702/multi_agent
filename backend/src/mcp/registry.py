"""工具分类注册表（蓝图 §4：mcp/registry.py）。

业务工具定义在 agent/tools/ 按域分包；本模块提供 工具名 → 实现函数
的映射，两个消费方：
- agent 层挂载（build_agent 的 tools）
- 子代理 YAML 加载器查表（subagents/*.yaml 的 tools 字段）
未来 MCP 协议化（FastMCP server）时，同一注册表即暴露清单。
"""

from __future__ import annotations

from collections.abc import Callable

from src.agent.tools.fetch_tool import fetch_url
from src.agent.tools.sandbox_tool import (
    download_sandbox_file,
    run_code_in_sandbox,
    run_command_in_sandbox,
    upload_workspace_file,
)
from src.agent.tools.search import internet_search
from src.agent.tools.skill_tool import run_skill_script

TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "internet_search": internet_search,
    "fetch_url": fetch_url,  # 受控抓取（决策 2026-08-11：搜索发现 + 抓取获取 双工具分工）
    "run_code_in_sandbox": run_code_in_sandbox,
    "run_command_in_sandbox": run_command_in_sandbox,
    "upload_workspace_file": upload_workspace_file,
    "download_sandbox_file": download_sandbox_file,
    "run_skill_script": run_skill_script,
}


def get_tool(name: str) -> Callable[..., str]:
    """按名称取工具实现。

    Args:
        name: 注册表内的工具名（YAML tools 字段 / agent 挂载清单）

    Returns:
        工具实现函数

    Raises:
        KeyError: 未知工具名（配置错误，fail fast——不让 agent 带病启动）
    """
    if name not in TOOL_REGISTRY:
        raise KeyError(f"未注册工具：{name}，可选：{sorted(TOOL_REGISTRY)}")
    return TOOL_REGISTRY[name]
