"""工具调用审计中间件（P1）：记录每次工具调用的 name + 敏感参数（脱敏）。

覆盖边界（深化方案 §3.3）：MCP 自定义工具、沙箱 run_code_in_sandbox 等不经
backend 的文件 IO——backend 层物理不可达，统一在此记审计（只审计不拦截，
与 PolicyBackend 的 policy_backend 审计互补成完整链路）。

钩子：awrap_tool_call（langchain AgentMiddleware，types.py:744）——项目全走
astream 异步上下文，只实现 async 版（与 _configurable_model 同款约定，
sync 钩子在异步上下文不触发）。

设计文档：docs/decisions/方案-CompositeBackend深化改造-v1.md §3.4 / §6.4
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

# 需要记录参数的工具（写操作/执行类）；其余工具只记名（防上下文膨胀）
# P1 扩充：run_command_in_sandbox（命令本身）、upload/download（文件同步）
_SENSITIVE_TOOLS = {
    "run_code_in_sandbox", "write_file", "edit_file", "delete", "upload_files",
    "run_command_in_sandbox", "upload_workspace_file", "download_sandbox_file",
    "run_skill_script",  # 技能脚本执行（记 skill_name/script_name 参数）
}
# 参数截断上限（防审计行无限膨胀；密钥纪律：超长即截断）
_MAX_ARGS_LEN = 300


class ToolAuditMiddleware(AgentMiddleware):
    """工具调用审计：只审计不拦截（旁路能力，失败绝不影响工具执行）。

    记录字段（扁平 JSON 顶层，与 policy_backend 审计同构）：
    ts / thread_id（取自 runtime.context，同 TokenUsageMiddleware 约定）/
    layer=tool_call / tool / decision=audit / args（敏感工具脱敏截断）
    """

    async def awrap_tool_call(self, request, handler):
        """工具执行前记审计，然后放行；审计异常只降级 debug，不阻断工具。"""
        try:
            self._safe_audit(request)
        except Exception:  # noqa: BLE001 —— 审计是旁路能力，失败不影响工具执行
            logger.debug("工具审计失败（不影响执行）", exc_info=True)
        return await handler(request)

    def _safe_audit(self, request) -> None:
        tool_call = getattr(request, "tool_call", None) or {}
        name = tool_call.get("name", "")
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "thread_id": self._thread_id_from(request),
            "layer": "tool_call",
            "tool": name,
            "decision": "audit",
        }
        if name in _SENSITIVE_TOOLS:
            record["args"] = self._sanitize_args(name, tool_call.get("args", {}) or {})
        audit_logger.info(json.dumps(record, ensure_ascii=False, default=str))

    def _audit_blocked(self, tool: str, reason: str) -> None:
        """安全拦截事件（安全机制 D5）：校验拦截计数，审计留痕。"""
        audit_logger.info(json.dumps({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "layer": "security",
            "event": "blocked",
            "tool": tool,
            "reason": reason,
        }, ensure_ascii=False, default=str))

    @staticmethod
    def _thread_id_from(request) -> str:
        """会话定位：runtime.context.session_id（中间件是编译时单例，会话经请求级 context）。"""
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None) if runtime is not None else None
        return getattr(context, "session_id", "") if context is not None else ""

    @staticmethod
    def _sanitize_args(name: str, args: dict) -> dict:
        """脱敏：run_code_in_sandbox 的 code 替换为 code_len；超长字符串截断 300 字符。

        非字符串值（int/bool/list 等）原样保留——统一由外层 json.dumps(default=str)
        序列化，避免误转类型（如 code_len 变字符串）。
        """
        safe = dict(args)
        if name == "run_code_in_sandbox" and isinstance(safe.get("code"), str):
            safe["code_len"] = len(safe.pop("code"))
        for key, value in list(safe.items()):
            if isinstance(value, str) and len(value) > _MAX_ARGS_LEN:
                safe[key] = value[:_MAX_ARGS_LEN] + "…"
        return safe
