"""技能域工具：run_skill_script——技能脚本执行闭环（方案 Skill 体系 §8.4）。

评审问题 2 修复（v1.1）：scripts/ 执行闭环不能只靠 SKILL.md 文字指引 agent
自觉——封装 run_skill_script 工具，把「读技能脚本 → 送沙箱 → 执行」打包成
一步，agent 直接调用，减少出错概率（工具层强制闭环）。

读取源：data/skills/skill_md/<skill_name>/scripts/<script_name>（市场技能，
磁盘直读 + 路径校验）；执行：沙箱池（隔离，内容拷入容器不执行磁盘文件）。

**输出（阶段 2.2.7）**：返回 `ToolResult` 信封。路径穿越 / 脚本不存在 /
沙箱未配置 / 执行异常 → `error` + 归一错误码。

⚠️ 已知不一致（记在分支笔记 P12）：本工具**不截断**脚本输出，而沙箱 4 个
工具都经 `_truncate_output`——本次「最简短迁移」不夹带行为变更，留待后续拍板。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.runnables import RunnableConfig

from src.core.config import settings
from src.core.errors import ToolErrorCode
from src.core.paths import get_skill_md_dir
from src.tools.impl.sandbox import (
    _NOT_CONFIGURED_MESSAGE,
    _thread_id_from,
    sandbox_adapter,
    sandbox_pool,
)
from src.tools.contract.result import ToolResult

_TOOL_NAME = "run_skill_script"

# 技能内可执行目录（防执行 assets/ 模板等非脚本文件）
_SCRIPTS_SUBDIR = "scripts"


def _invalid_script_path(script_name: str) -> str:
    """路径穿越 → 审计 + 返回拒绝文案（审计由 security 模块统一记）。"""
    from src.tools.guardrails.audit import log_security_blocked

    log_security_blocked(_TOOL_NAME, f"路径穿越：{script_name}")
    return "技能脚本路径不合法：仅允许 scripts/ 内相对文件名。"


def run_skill_script(
    skill_name: str,
    script_name: str,
    *,
    script_args: str = "",
    config: RunnableConfig | None = None,
) -> ToolResult:
    """执行技能脚本（读文件 → 沙箱执行，一步封装）。

    Args:
        skill_name: 技能名（data/skills/skill_md/<skill_name>/）
        script_name: scripts/ 下的脚本文件名（禁 ../ 与绝对路径）
        script_args: 脚本命令行参数（如 "sample_data.json"）
        config: 执行配置（框架注入，取 thread_id 定位会话沙箱）

    Returns:
        `ok` 信封（脚本输出）；校验失败/脚本不存在/沙箱故障返回 `error` 信封
    """
    if not settings.sandbox_url:
        return ToolResult(
            status="error",
            message=_NOT_CONFIGURED_MESSAGE,
            error_code=ToolErrorCode.NOT_CONFIGURED,
            tool=_TOOL_NAME,
        )
    # 路径校验（00-security）：禁 ../ 与绝对路径
    parts = script_name.replace("\\", "/").split("/")
    if script_name.startswith("/") or any(p == ".." for p in parts):
        return ToolResult(
            status="error",
            message=_invalid_script_path(script_name),
            error_code=ToolErrorCode.INVALID_ARG,
            tool=_TOOL_NAME,
        )
    script_file = get_skill_md_dir() / skill_name / _SCRIPTS_SUBDIR / script_name
    if not script_file.is_file():
        return ToolResult(
            status="error",
            message=(
                f"技能脚本不存在：{skill_name}/scripts/{script_name}"
                "（可用 ls /skills/market/ 查看技能目录）。"
            ),
            error_code=ToolErrorCode.NOT_FOUND,
            tool=_TOOL_NAME,
        )
    try:
        content = script_file.read_text(encoding="utf-8")
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        # entry 不拼 python 前缀——adapter.run_script 内部已拼 "python {entry}"
        output = sandbox_adapter.run_script(
            sandbox, {script_name: content}, f"{script_name} {script_args}".strip()
        )
        return ToolResult(
            status="ok",
            message=output,
            data={"skill": skill_name, "script": script_name, "output": output},
            tool=_TOOL_NAME,
        )
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return ToolResult(
            status="error",
            message=f"技能脚本执行失败（{type(e).__name__}）：{e}。请勿重试沙箱。",
            error_code=ToolErrorCode.INTERNAL,
            tool=_TOOL_NAME,
        )
