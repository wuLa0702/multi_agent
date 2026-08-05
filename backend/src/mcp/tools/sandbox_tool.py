"""沙箱域工具：OpenSandbox 隔离沙箱执行（会话级池化，能力计划 §3.1/§7.4）。

- run_code_in_sandbox：池化执行——同会话复用沙箱 + renew 续期（消除每次
  create+30s ready 开销）；非池化模式（sandbox_pool_enabled=False）工具
  自管生命周期（try/finally destroy，防泄漏——评审问题 1）
- 会话定位：工具函数声明 RunnableConfig 参数，由框架自动注入执行 config，
  从 config["configurable"]["thread_id"] 取会话 ID（stream_agent_tokens 封装传入）
- 注册进 mcp.registry；本地 dev 连 docker（8080），prod 连云端
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from src.core.config import settings
from src.sandbox.adapter import OpenSandboxAdapter
from src.sandbox.pool import SandboxFullError, SandboxPool

# 沙箱适配器与池（惰性：import 不创建沙箱，调用时才连本地 docker / 云端）
sandbox_adapter = OpenSandboxAdapter()
sandbox_pool = SandboxPool()


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
        执行 stdout；失败/资源已满时返回错误提示字符串
    """
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
    if not settings.sandbox_pool_enabled:
        # 非池化兼容（评审问题 1）：工具自管生命周期——try/finally 保证
        # destroy，恢复旧 run_code 防泄漏语义（不依赖服务端 TTL 兜底）
        sandbox = None
        try:
            sandbox = sandbox_adapter.create_sandbox()
            return sandbox_adapter.run_script(sandbox, {filename: code}, filename)
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
        return sandbox_adapter.run_script(sandbox, {filename: code}, filename)
    except SandboxFullError as e:  # 池上限：友好提示，agent 可换方案
        return str(e)
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return (
            f"沙箱执行失败（{type(e).__name__}）：{e}。"
            "请勿重试沙箱，直接基于已有知识回答。"
        )
