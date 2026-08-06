"""解释器中间件构建（2026-08-05 解耦：main_agent 只做编排）。

interpreter 挂载逻辑独立成模块——main_agent._build_agent 仅调用
build_interpreter_middleware() 追加中间件，不再内嵌 import/参数/校验。

设计文档：docs/decisions/方案-EventStreaming与Interpreter引入-v1.md
"""

from __future__ import annotations

from src.core.config import settings

# PTC 可暴露的只读工具白名单（默认拒绝语义：名单外的工具一律拒绝——
# 新增工具天然安全，无需维护黑名单；新增只读工具时显式加入本集合）
_READONLY_PTC_TOOLS = {"internet_search"}


def _parse_ptc_whitelist(raw: str) -> list[str]:
    """PTC 白名单解析 + 校验（默认拒绝语义，fail fast）。

    PTC 调用不走正常工具路径（interrupt_on 审批不生效）——能暴露什么由
    _READONLY_PTC_TOOLS 白名单决定（不是黑名单兜底）：配置名单外工具
    （文件/沙箱/未知工具）→ 直接抛错，新增工具天然安全。

    Args:
        raw: 逗号分隔的工具名（settings.interpreter_ptc）

    Returns:
        校验通过的白名单工具名列表

    Raises:
        ValueError: 配置了只读白名单外的工具
    """
    names = [t.strip() for t in raw.split(",") if t.strip()]
    for name in names:
        if name not in _READONLY_PTC_TOOLS:
            raise ValueError(
                f"interpreter_ptc 只允许只读白名单工具：{name} 不在 "
                f"{sorted(_READONLY_PTC_TOOLS)}（PTC 调用绕过 interrupt_on 审批，"
                "文件/沙箱工具绝不可暴露；新增只读工具需显式加入 "
                "_READONLY_PTC_TOOLS）"
            )
    return names


def build_interpreter_middleware() -> list:
    """构建解释器中间件列表（interpreter_enabled 门控 + 惰性 import）。

    中间件顺序（评审问题 2.2 预案）：ToolAudit 在 CodeInterpreter 前
    （外层），eval 工具调用先经审计链——由调用方在 middleware 栈中
    保持 ToolAudit 在前、本函数返回追加在后。

    Returns:
        要追加到 middleware 栈的中间件列表（未启用 → 空列表）

    Raises:
        RuntimeError: enabled=True 但 langchain-quickjs 不可用
            （Python 3.14 无 bsdiff4 wheel 环境阻塞指引）
    """
    if not settings.interpreter_enabled:
        return []
    try:
        from langchain_quickjs import CodeInterpreterMiddleware
    except ImportError as exc:  # pragma: no cover - 环境阻塞路径
        raise RuntimeError(
            "interpreter_enabled=True 但 langchain-quickjs 不可用："
            f"{exc}。Python 3.14 无 bsdiff4 wheel 且源码构建失败——"
            "请换 Python 3.11/3.12 venv 或等待 bsdiff4 发布 py3.14 wheel。"
        ) from exc
    return [
        CodeInterpreterMiddleware(
            memory_limit=64 * 1024 * 1024,   # 官方默认 64MB
            timeout=5.0,                     # 单次 eval 5s
            max_result_chars=4000,
            # 🔴 PTC 只读白名单：绝不含文件/沙箱工具（PTC 绕 interrupt_on 审批）
            ptc=_parse_ptc_whitelist(settings.interpreter_ptc),
            mode="turn",                     # 轮内持久（学习：turn/call 对比）
        )
    ]
