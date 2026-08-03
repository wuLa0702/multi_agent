"""沙箱域工具：OpenSandbox 隔离沙箱执行（薄壳，实现下沉 src/sandbox/ 层）。

定义工具（run_code_in_sandbox）供 agent 挂载；注册进 mcp.registry。
本地 dev 连 docker（8080），prod 连云端——连接配置在 src.sandbox.adapter。
"""

from __future__ import annotations

from src.core.config import settings
from src.sandbox.adapter import OpenSandboxAdapter

# 沙箱适配器（惰性：import 不创建沙箱，调用时才连本地 docker / 云端）
sandbox_adapter = OpenSandboxAdapter()


def run_code_in_sandbox(code: str, filename: str = "script.py") -> str:
    """在 OpenSandbox 隔离沙箱中执行 Python 代码并返回输出。

    适用：运行不可信/隔离代码、跑测试、验证脚本——沙箱内执行，不影响本地环境。
    失败时返回错误信息给 agent（不抛异常）——工具失败不应中断整个 run。
    """
    if not settings.sandbox_url:
        return "沙箱不可用：SANDBOX_URL 未配置（.env.dev），请直接基于已有知识回答。"
    try:
        return sandbox_adapter.run_code(code, filename)
    except Exception as e:  # noqa: BLE001 —— 工具失败降级为错误信息，不冒泡中断 run
        return (
            f"沙箱执行失败（{type(e).__name__}）：{e}。"
            "请勿重试沙箱，直接基于已有知识回答。"
        )
