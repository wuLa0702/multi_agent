"""沙箱域工具：OpenSandbox 隔离沙箱执行（会话级池化，能力计划 §3/§7）。

- run_code_in_sandbox：池化执行——同会话复用沙箱 + renew 续期；非池化模式
  工具自管生命周期（try/finally destroy，防泄漏——评审问题 1）
- run_command_in_sandbox：shell 命令（危险前缀校验 + 命令级超时）
- upload_workspace_file / download_sandbox_file：workspace ↔ 沙箱文件同步
  （sandbox:/workspace/ 约定 + 路径校验防逃逸）
- 会话定位：RunnableConfig 参数由框架注入，取 thread_id（stream_agent_tokens 封装）
- 注册进 tools.registry；本地 dev 连 docker（8080），prod 连云端

**输出（阶段 2.2.3–2.2.6）**：返回 `ToolResult` 信封。输出超限截断 → `degraded`
（拿到了但不完整）；未配置 / 越权 / 池满 / 执行异常 → `error` + 归一错误码。
"""

from __future__ import annotations

from datetime import timedelta

from langchain_core.runnables import RunnableConfig

from src.core.config import settings
from src.core.errors import ToolErrorCode
from src.sandbox.adapter import OpenSandboxAdapter
from src.sandbox.pool import SandboxFullError, sandbox_pool
from src.tools.result import ToolResult
from src.tools.validators import validate_command, validate_sandbox_path

# 沙箱适配器（惰性：import 不创建沙箱，调用时才连本地 docker / 云端）
sandbox_adapter = OpenSandboxAdapter()

# 工具名（审计与事件定位用）
_TOOL_CODE = "run_code_in_sandbox"
_TOOL_COMMAND = "run_command_in_sandbox"
_TOOL_UPLOAD = "upload_workspace_file"
_TOOL_DOWNLOAD = "download_sandbox_file"

# 未配置提示（4 个工具共用，文案一致）
_NOT_CONFIGURED_MESSAGE = (
    "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
)


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


def _truncate_output(text: str) -> tuple[str, bool]:
    """输出截断（§3.2 输出上限）：超过 sandbox_output_limit 截断并提示取回方式。

    Args:
        text: 原始输出

    Returns:
        `(文本, 是否被截断)`——`degraded` 态据此判定，故必须显式回传而不是
        切完就算（切完再问"切没切过"就晚了）
    """
    limit = settings.sandbox_output_limit
    if len(text) > limit:
        return (
            text[:limit]
            + f"\n…（输出已截断，上限 {limit} 字符，完整结果请用 download_sandbox_file 取回）",
            True,
        )
    return text, False


def _not_configured(tool: str) -> ToolResult:
    """沙箱未配置 → `error` 信封（不可重试：重试也变不出配置）。"""
    return ToolResult(
        status="error",
        message=_NOT_CONFIGURED_MESSAGE,
        error_code=ToolErrorCode.NOT_CONFIGURED,
        tool=tool,
    )


def _pool_full(exc: SandboxFullError, tool: str) -> ToolResult:
    """池上限 → `error` 信封（资源占用类，可重试：稍后腾出即可）。"""
    return ToolResult(
        status="error",
        message=str(exc),
        error_code=ToolErrorCode.RATE_LIMITED,
        retryable=True,
        tool=tool,
    )


def _blocked(blocked_reason: str, tool: str) -> ToolResult:
    """校验拦截 → `error` 信封（`invalid_arg`，不可重试：参数没变重试必然再拦）。"""
    return ToolResult(
        status="error",
        message=blocked_reason,
        error_code=ToolErrorCode.INVALID_ARG,
        tool=tool,
    )


def _output_result(raw: str, *, tool: str, data_key: str) -> ToolResult:
    """沙箱输出 → `ok` / `degraded` 信封（超限截断即 `degraded`）。

    Args:
        raw: 原始输出
        tool: 工具名
        data_key: 结构化载荷的键（`stdout` / `text`）

    Returns:
        未截断 → `ok`；被截断 → `degraded`（拿到结果但不完整）
    """
    text, truncated = _truncate_output(raw)
    return ToolResult(
        status="degraded" if truncated else "ok",
        message=text,
        data={data_key: text, "truncated": truncated},
        tool=tool,
    )


def run_code_in_sandbox(
    code: str, filename: str = "script.py", config: RunnableConfig | None = None
) -> ToolResult:
    """在会话级沙箱中执行 Python 代码并返回输出（池化：复用 + 续期）。

    适用：运行不可信/隔离代码、跑测试、验证脚本——沙箱内执行，不影响本地环境。
    失败时返回错误信息给 agent（不抛异常）——工具失败不应中断整个 run。

    Args:
        code: Python 源码
        filename: 沙箱内文件名（默认 script.py）
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        `ok`/`degraded` 信封（stdout，超限截断）；失败返回 `error` 信封
    """
    # 补漏（阶段 1.2）：此前 filename 完全未校验（违反 CLAUDE.md 核心约束 #5）
    blocked = validate_sandbox_path(filename)
    if blocked:
        return _blocked(blocked, _TOOL_CODE)  # 审计由 @security_audit 统一记
    if not settings.sandbox_url:
        return _not_configured(_TOOL_CODE)
    if not settings.sandbox_pool_enabled:
        # 非池化兼容（评审问题 1）：工具自管生命周期——try/finally 保证
        # destroy，恢复旧 run_code 防泄漏语义（不依赖服务端 TTL 兜底）
        sandbox = None
        try:
            sandbox = sandbox_adapter.create_sandbox()
            return _output_result(
                sandbox_adapter.run_script(sandbox, {filename: code}, filename),
                tool=_TOOL_CODE,
                data_key="stdout",
            )
        except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
            return ToolResult(
                status="error",
                message=(
                    f"沙箱执行失败（{type(e).__name__}）：{e}。"
                    "请勿重试沙箱，直接基于已有知识回答。"
                ),
                error_code=ToolErrorCode.INTERNAL,
                tool=_TOOL_CODE,
            )
        finally:
            if sandbox is not None:
                sandbox_adapter.destroy(sandbox)
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        return _output_result(
            sandbox_adapter.run_script(sandbox, {filename: code}, filename),
            tool=_TOOL_CODE,
            data_key="stdout",
        )
    except SandboxFullError as e:  # 池上限：友好提示，agent 可换方案
        return _pool_full(e, _TOOL_CODE)
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return ToolResult(
            status="error",
            message=(
                f"沙箱执行失败（{type(e).__name__}）：{e}。"
                "请勿重试沙箱，直接基于已有知识回答。"
            ),
            error_code=ToolErrorCode.INTERNAL,
            tool=_TOOL_CODE,
        )


def run_command_in_sandbox(
    command: str, *, timeout: int = 60, config: RunnableConfig | None = None
) -> ToolResult:
    """在会话级沙箱中执行 shell 命令（能力计划 §3.2/§3.4）。

    危险前缀（rm -rf /、mkfs、shutdown 等）先拒；命令级超时防挂起。

    Args:
        command: shell 命令（如 "pip install pandas"）
        timeout: 命令超时秒数（默认 60，防长命令挂起）
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        `ok`/`degraded` 信封（stdout，超限截断）；拒绝/失败返回 `error` 信封
    """
    if not settings.sandbox_url:
        return _not_configured(_TOOL_COMMAND)
    blocked = validate_command(command)
    if blocked:
        return _blocked(blocked, _TOOL_COMMAND)  # 审计由 @security_audit 统一记
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        out = sandbox_adapter.run_command(
            sandbox, command, timeout=timedelta(seconds=timeout)
        )
        return _output_result(out, tool=_TOOL_COMMAND, data_key="stdout")
    except SandboxFullError as e:  # 池上限：友好提示，agent 可换方案
        return _pool_full(e, _TOOL_COMMAND)
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return ToolResult(
            status="error",
            message=f"沙箱命令执行失败（{type(e).__name__}）：{e}。请勿重试沙箱。",
            error_code=ToolErrorCode.INTERNAL,
            tool=_TOOL_COMMAND,
        )


def upload_workspace_file(
    filename: str, content: str, config: RunnableConfig | None = None
) -> ToolResult:
    """上传（能力计划 §3.3）：内容写入沙箱内 /workspace/{filename}。

    与 backend 持久层的关系：本工具只写沙箱内（执行层临时），持久文件走
    backend 文件工具（write_file /workspace/...）。

    Args:
        filename: workspace 相对文件名（禁 ../ 与绝对路径）
        content: 文件内容
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        `ok` 信封（`data` 带 filename / bytes）；校验失败/资源已满返回 `error` 信封
    """
    if not settings.sandbox_url:
        return _not_configured(_TOOL_UPLOAD)
    blocked = validate_sandbox_path(filename)
    if blocked:
        return _blocked(blocked, _TOOL_UPLOAD)  # 审计由 @security_audit 统一记
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        sandbox_adapter.upload_file(sandbox, f"workspace/{filename}", content)
        return ToolResult(
            status="ok",
            message=(
                f"已上传至沙箱 workspace/{filename}"
                "（执行层临时，持久化请用文件工具写入 backend）。"
            ),
            data={"filename": filename, "bytes": len(content.encode("utf-8"))},
            tool=_TOOL_UPLOAD,
        )
    except SandboxFullError as e:
        return _pool_full(e, _TOOL_UPLOAD)
    except Exception as e:  # noqa: BLE001
        return ToolResult(
            status="error",
            message=f"沙箱上传失败（{type(e).__name__}）：{e}。请勿重试沙箱。",
            error_code=ToolErrorCode.INTERNAL,
            tool=_TOOL_UPLOAD,
        )


def download_sandbox_file(
    filename: str, config: RunnableConfig | None = None
) -> ToolResult:
    """取回（能力计划 §3.3）：读取沙箱内 /workspace/{filename} 内容。

    Args:
        filename: workspace 相对文件名（禁 ../ 与绝对路径）
        config: 执行配置（框架自动注入，取 thread_id 定位会话沙箱）

    Returns:
        `ok`/`degraded` 信封（文件内容，超限截断）；校验失败/资源已满返回 `error` 信封
    """
    if not settings.sandbox_url:
        return _not_configured(_TOOL_DOWNLOAD)
    blocked = validate_sandbox_path(filename)
    if blocked:
        return _blocked(blocked, _TOOL_DOWNLOAD)  # 审计由 @security_audit 统一记
    try:
        sandbox = sandbox_pool.get_sandbox(_thread_id_from(config))
        return _output_result(
            sandbox_adapter.download_file(sandbox, f"workspace/{filename}"),
            tool=_TOOL_DOWNLOAD,
            data_key="text",
        )
    except SandboxFullError as e:
        return _pool_full(e, _TOOL_DOWNLOAD)
    except Exception as e:  # noqa: BLE001
        return ToolResult(
            status="error",
            message=f"沙箱下载失败（{type(e).__name__}）：{e}。请勿重试沙箱。",
            error_code=ToolErrorCode.INTERNAL,
            tool=_TOOL_DOWNLOAD,
        )
