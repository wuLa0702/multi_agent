"""沙箱域工具：OpenSandbox 隔离沙箱执行（会话级池化，能力计划 §3/§7）。

- run_code_in_sandbox：池化执行——同会话复用沙箱 + renew 续期；非池化模式
  工具自管生命周期（try/finally destroy，防泄漏——评审问题 1）
- run_command_in_sandbox：shell 命令（危险前缀校验 + 命令级超时）
- upload_workspace_file / download_sandbox_file：workspace ↔ 沙箱文件同步
  （sandbox:/workspace/ 约定 + 路径校验防逃逸）
- 会话定位：RunnableConfig 参数由框架注入，取 thread_id（stream_agent_tokens 封装）
- 注册进 tools.registry；本地 dev 连 docker（8080），prod 连云端
"""

from __future__ import annotations

from datetime import timedelta

from langchain_core.runnables import RunnableConfig

from src.core.config import settings
from src.sandbox.adapter import OpenSandboxAdapter
from src.sandbox.pool import SandboxFullError, sandbox_pool
from src.tools.validators import validate_command, validate_sandbox_path

# 沙箱适配器（惰性：import 不创建沙箱，调用时才连本地 docker / 云端）
sandbox_adapter = OpenSandboxAdapter()


def _thread_id_from(config: RunnableConfig | None) -> str:
    """工具执行 config → 会话 ID（沙箱池维度）。

    langchain 工具函数声明 RunnableConfig 参数即由框架自动注入执行 config；
    thread_id 由 stream_agent_tokens 封装传入。config 缺失（单测/无会话场景）
    回落 "default" 池——不抛错（§6.2 风险项）。

    Args:
        config: 工具执行配置（框架注入）

    Returns:
        会话 ID（缺省 "default"）
    """
    if config:
        return str(config.get("configurable", {}).get("thread_id") or "default")
    return "default"


def _truncate_output(text: str) -> str:
    """输出截断（§3.2 输出上限）：超过 sandbox_output_limit 截断并提示取回方式。"""
    limit = settings.sandbox_output_limit
    if len(text) > limit:
        return (
            text[:limit]
            + f"\n…（输出已截断，上限 {limit} 字符，完整结果请用 download_sandbox_file 取回）"
        )
    return text


def run_code_in_sandbox(
    code: str, filename: str = "script.py", config: RunnableConfig | None = None
) -> str:
    """在会话级沙箱中执行 Python 代码并返回输出（池化：复用 + 续期）。

    适用：运行不可信/隔离代码、跑测试、验证脚本——沙箱内执行，不影响本地环境。
    失败时返回错误信息给 agent（不抛异常）——工具失败不应中断整个 run。

    Args:
        code: Python 源码
        filename: 沙箱内文件名（默认 script.py）
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        执行 stdout（截断）；失败/资源已满时返回错误提示字符串
    """
    # 补漏（阶段 1.2）：此前 filename 完全未校验（违反 CLAUDE.md 核心约束 #5）
    blocked = validate_sandbox_path(filename)
    if blocked:
        return blocked  # 审计由 @security_audit 统一记
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
    if not settings.sandbox_pool_enabled:
        # 非池化兼容（评审问题 1）：工具自管生命周期——try/finally 保证
        # destroy，恢复旧 run_code 防泄漏语义（不依赖服务端 TTL 兜底）
        sandbox = None
        try:
            sandbox = sandbox_adapter.create_sandbox()
            return _truncate_output(
                sandbox_adapter.run_script(sandbox, {filename: code}, filename)
            )
        except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
            return (
                f"沙箱执行失败（{type(e).__name__}）：{e}。"
                "请勿重试沙箱，直接基于已有知识回答。"
            )
        finally:
            if sandbox is not None:
                sandbox_adapter.destroy(sandbox)
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        return _truncate_output(
            sandbox_adapter.run_script(sandbox, {filename: code}, filename)
        )
    except SandboxFullError as e:  # 池上限：友好提示，agent 可换方案
        return str(e)
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return (
            f"沙箱执行失败（{type(e).__name__}）：{e}。"
            "请勿重试沙箱，直接基于已有知识回答。"
        )


def run_command_in_sandbox(
    command: str, *, timeout: int = 60, config: RunnableConfig | None = None
) -> str:
    """在会话级沙箱中执行 shell 命令（能力计划 §3.2/§3.4）。

    危险前缀（rm -rf /、mkfs、shutdown 等）先拒；命令级超时防挂起。

    Args:
        command: shell 命令（如 "pip install pandas"）
        timeout: 命令超时秒数（默认 60，防长命令挂起）
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        命令 stdout（截断）；拒绝/失败/资源已满时返回错误提示字符串
    """
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
    blocked = validate_command(command)
    if blocked:
        return blocked  # 审计由 @security_audit 统一记（不再调用点手写，防散落漏记）
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        out = sandbox_adapter.run_command(
            sandbox, command, timeout=timedelta(seconds=timeout)
        )
        return _truncate_output(out)
    except SandboxFullError as e:  # 池上限：友好提示，agent 可换方案
        return str(e)
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return f"沙箱命令执行失败（{type(e).__name__}）：{e}。请勿重试沙箱。"


def upload_workspace_file(
    filename: str, content: str, config: RunnableConfig | None = None
) -> str:
    """上传（能力计划 §3.3）：内容写入沙箱内 /workspace/{filename}。

    与 backend 持久层的关系：本工具只写沙箱内（执行层临时），持久文件走
    backend 文件工具（write_file /workspace/...）。

    Args:
        filename: workspace 相对文件名（禁 ../ 与绝对路径）
        content: 文件内容
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        成功提示；校验失败/资源已满时返回错误提示字符串
    """
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
    blocked = validate_sandbox_path(filename)
    if blocked:
        return blocked  # 审计由 @security_audit 统一记
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        sandbox_adapter.upload_file(sandbox, f"workspace/{filename}", content)
        return f"已上传至沙箱 workspace/{filename}（执行层临时，持久化请用文件工具写入 backend）。"
    except SandboxFullError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"沙箱上传失败（{type(e).__name__}）：{e}。请勿重试沙箱。"


def download_sandbox_file(
    filename: str, config: RunnableConfig | None = None
) -> str:
    """取回（能力计划 §3.3）：读取沙箱内 /workspace/{filename} 内容。

    Args:
        filename: workspace 相对文件名（禁 ../ 与绝对路径）
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        文件内容（截断）；校验失败/资源已满时返回错误提示字符串
    """
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
    blocked = validate_sandbox_path(filename)
    if blocked:
        return blocked  # 审计由 @security_audit 统一记
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        return _truncate_output(
            sandbox_adapter.download_file(sandbox, f"workspace/{filename}")
        )
    except SandboxFullError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"沙箱下载失败（{type(e).__name__}）：{e}。请勿重试沙箱。"
