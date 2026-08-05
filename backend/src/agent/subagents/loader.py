"""声明式子 Agent YAML 加载器（蓝图决策 1/2：subagents/*.yaml）。

将 agent/subagents/*.yaml 解析为 deepagents SubAgent 声明（TypedDict）：
- tools 字段：名字符串 → 经 mcp.registry 查表映射为实际函数
- permissions 字段（P1）：YAML 显式声明优先；缺省走 core.permissions 模板；
  模板无 → 不注入键（继承父级规则，graph.py:663 spec.get("permissions", permissions)）
- P2（SUBAGENT_ISOLATION=True）：预编译 CompiledSubAgent——每个子代理独立
  StateBackend（内存临时），文件永不落主会话工作区；编译需 model 参数
- 非法 YAML / 缺必填字段 / 未知工具名：fail fast 抛异常
  （配置错误尽早暴露，不让 agent 带病启动）

设计文档：docs/decisions/方案-CompositeBackend深化改造-v1.md §3.5 / §4.2 / §6.5
"""

from __future__ import annotations

from pathlib import Path

import yaml
from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from langchain_core.language_models import BaseChatModel

from src.core.config import settings
from src.core.permissions import build_subagent_permissions
from src.mcp.registry import get_tool

SUBAGENTS_DIR = Path(__file__).resolve().parent


def load_subagents(
    directory: Path = SUBAGENTS_DIR, *, model: BaseChatModel | None = None
) -> list[SubAgent | CompiledSubAgent]:
    """加载目录下全部子代理 YAML（按文件名排序，顺序稳定）。

    P2 隔离模式（settings.subagent_isolation）下每个子代理预编译为
    CompiledSubAgent（独立 StateBackend）；默认模式原样返回 SubAgent 声明。

    Args:
        directory: 子代理 YAML 目录（默认本包目录）
        model: P2 编译子代理用的模型（SUBAGENT_ISOLATION=True 时必须传入）

    Returns:
        SubAgent / CompiledSubAgent 声明列表（deepagents 可直接消费）

    Raises:
        yaml.YAMLError: YAML 语法非法
        KeyError: 缺少必填字段（name/description/system_prompt）或 tools 未注册
        RuntimeError: SUBAGENT_ISOLATION=True 但 model 未传入
    """
    specs = [_parse_subagent_yaml(f) for f in sorted(directory.glob("*.yaml"))]
    if not settings.subagent_isolation:
        return specs
    if model is None:
        raise RuntimeError("SUBAGENT_ISOLATION=True 需要传入 model 以编译子代理")
    return [_compile_isolated(spec, model) for spec in specs]


def _parse_subagent_yaml(yaml_file: Path) -> SubAgent:
    """解析单个 YAML 文件为 SubAgent 声明（含 permissions 透传）。

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
    # P1 子代理权限（整体替换父级，graph.py:663 语义）：
    # YAML 显式声明优先；缺省走模板；模板无 → 不注入键（继承父级）
    if "permissions" in data:
        spec["permissions"] = _parse_permissions(data["permissions"])
    else:
        perms = build_subagent_permissions(spec["name"])
        if perms:
            spec["permissions"] = perms
    return spec


def _parse_permissions(data: list) -> list[FilesystemPermission]:
    """YAML permissions 声明 → FilesystemPermission 对象列表。

    deepagents 消费对象而非 dict（graph.py 直接透传 spec["permissions"] 给
    FilesystemMiddleware，无 dict→对象转换）——YAML 里 operations/paths/mode
    与 dataclass 字段一一对应，kwargs 展开即可。
    """
    return [FilesystemPermission(**rule) for rule in data]


def _compile_isolated(spec: SubAgent, model: BaseChatModel) -> CompiledSubAgent:
    """P2：预编译子代理——独立 StateBackend（内存临时）+ 独立权限。

    CompiledSubAgent 只有 name/description/runnable 三字段（无 system_prompt，
    deepagents 0.7.1 核实）——提示词与 backend/权限全部编译进 runnable。
    子代理文件存自身 graph state，主会话工作区零污染；断点 resume 随主 state 恢复。

    Args:
        spec: 解析后的 SubAgent 声明
        model: 编译用模型（编译时绑定；子代理不随 _configurable_model 运行时切换）

    Returns:
        CompiledSubAgent 声明（deepagents "runnable" 分支按原样使用）
    """
    runnable = create_deep_agent(
        model=model,
        name=spec["name"],
        system_prompt=spec["system_prompt"],
        tools=spec["tools"],
        backend=StateBackend(),  # 子代理专属临时内存 backend（每个子代理独立实例）
        permissions=spec.get("permissions") or [],
    )
    return {
        "name": spec["name"],
        "description": spec["description"],
        "runnable": runnable,
    }
