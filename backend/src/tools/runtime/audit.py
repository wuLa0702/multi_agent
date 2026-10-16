"""工具调用审计中间件（P1）：记录每次工具调用的 name + 敏感参数（脱敏）。

阶段 2.3.1（2026-10-15）：改造为**两行制**（事前 / 事后），
事后行补上工具输出的**三态 `status` + 归一 `error_code` + `duration_ms`**——
数据源是阶段 2 落地的 artifact 结构化通道。详见 `ToolAuditMiddleware` 类 docstring。

审计落地批次 1（2026-10-16）：本模块三处写入统一改经 `core.audit.emit()`
——事件名点分化（`tool_call.start` / `tool_call.end` / `security.blocked`），
`thread_id` → `session_id`，删掉固定值 `decision="audit"`（无信息）。
**本模块不再直接调用 `audit_logger`**（由反绕过锁测试守护）。

覆盖边界（深化方案 §3.3）：MCP 自定义工具、沙箱 run_code_in_sandbox 等不经
backend 的文件 IO——backend 层物理不可达，统一在此记审计（只审计不拦截，
与 PolicyBackend 的 policy_backend 审计互补成完整链路）。

钩子：awrap_tool_call（langchain AgentMiddleware，types.py:744）——项目全走
astream 异步上下文，只实现 async 版（与 _configurable_model 同款约定，
sync 钩子在异步上下文不触发）。

设计文档：docs/decisions/方案-CompositeBackend深化改造-v1.md §3.4 / §6.4
"""

from __future__ import annotations

import logging
import time

from langchain.agents.middleware import AgentMiddleware

from src.core.audit import emit
from src.core.errors import is_retryable_tool_error
from src.tools.contract.error_map import classify_exception

logger = logging.getLogger(__name__)

# 需要记录参数的工具（写操作/执行类）；其余工具只记名（防上下文膨胀）
# P1 扩充：run_command_in_sandbox（命令本身）、upload/download（文件同步）
_SENSITIVE_TOOLS = {
    "run_code_in_sandbox", "write_file", "edit_file", "delete", "upload_files",
    "run_command_in_sandbox", "upload_workspace_file", "download_sandbox_file",
    "run_skill_script",  # 技能脚本执行（记 skill_name/script_name 参数）
}
# 参数截断上限（防审计行无限膨胀；密钥纪律：超长即截断）
_MAX_ARGS_LEN = 300


def _fallback_for(tool: str) -> str:
    """查工具的降级备选（登记表 `fallback_to` 声明）。

    **惰性导入**：`registry → impl/*.py → audit`（impl 用本模块的 `security_audit`），
    模块级导入会成环。

    Args:
        tool: 工具名

    Returns:
        备选工具名；无声明/未注册 → 空串
    """
    from src.tools.registry import fallback_for

    return fallback_for(tool)


def log_security_blocked(tool: str, reason: str) -> None:
    """安全拦截审计（模块级，工具实现也可调；安全机制 D5）。"""
    emit("security", "security.blocked", tool=tool, reason=reason)


def security_audit(tool: str):
    """安全校验审计装饰器（2026-08-12 安全评审 2.5：收口不散落）。

    包装校验函数：返回非空（错误提示）→ 自动审计 security/blocked。
    工具实现只需"校验失败返回提示字符串"，审计由装饰器统一做——不散落易漏。

    用法：
        @security_audit(tool="fetch_url")
        def _validate_url(url: str) -> bool | None: ...   # 返回 None=通过，str=拦截

    Args:
        tool: 审计日志中的工具名

    Returns:
        装饰器
    """

    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if result:
                reason = str(result) if isinstance(result, str) else "校验拦截"
                log_security_blocked(tool, reason)
            return result

        return wrapper

    return decorator


class ToolAuditMiddleware(AgentMiddleware):
    """工具调用审计：只审计不拦截（旁路能力，失败绝不影响工具执行）。

    **两行制**（阶段 2.3.1，对齐审计决策 D2 —— `决策-审计与可观测-方向-v1` §4）：
    每次调用写**两行**——`tool_call.start`（执行前）+ `tool_call.end`（执行后）。
    两行才留得下「操作开始了但没结束」这个信号：进程被杀 / 沙箱挂死时，
    单行合并方案什么都留不下，而那恰是审计最需要留的情形。

    记录字段（扁平 JSON 顶层，经 `core.audit.emit()` 统一出口）：
    核心 7 字段（ts 毫秒 / trace_id / seq / layer=tool_call / event / status /
    session_id——取自 runtime.context，同 TokenUsageMiddleware 约定）＋
    start 行：tool、args（敏感工具脱敏截断）｜
    end 行：tool、duration_ms ＋ **失败时** error_code / retryable / fallback_to
    """

    async def awrap_tool_call(self, request, handler):
        """执行前记 start 行 → 放行 → 执行后记 end 行（含结果与耗时）。

        `status` / `error_code` / `retryable` 取自工具输出的 **artifact 通道**
        （阶段 2.2 落地）——这正是 `ToolMessage.status`（只有 success/error）
        盖不住的三态信息（`ok` 与 `degraded` 都会被它压成 `success`）。

        审计任一行写失败都只降级 debug，绝不阻断工具（`_safe_call` 收口）。
        工具抛异常时**先记 end 行再原样抛出**——不吞异常，但把失败留痕。
        """
        self._safe_call(self._audit_start, request)
        started = time.monotonic()
        try:
            result = await handler(request)
        except BaseException as exc:
            # 含 CancelledError（进程被杀/取消）——正属 D2 要留痕的「未完成」情形
            # 异常路径没有信封 → 可重试性由错误码口径推出（单一真相源）
            code = classify_exception(exc)
            self._safe_call(
                self._audit_end,
                request,
                "error",
                code,
                is_retryable_tool_error(code),
                started,
            )
            raise
        status, error_code, retryable = self._outcome_of(result)
        self._safe_call(
            self._audit_end, request, status, error_code, retryable, started
        )
        return result

    @staticmethod
    def _safe_call(fn, *args) -> None:
        """审计旁路收口：任何异常都**不冒泡**（审计失败绝不影响工具执行）。

        **但两类异常分级留痕**（2026-10-16 批次 1 补充）：
        - `ValueError` = `emit()` 的**编程错误**（审计字段与核心字段重名）
          → 记 **error**：它不该被当"旁路失败"静默降级，否则永远没人发现
        - 其余（磁盘满等运行时故障）→ 记 **debug**（预期内的降级路径）
        """
        try:
            fn(*args)
        except ValueError:
            logger.error("工具审计编程错误（不影响执行）", exc_info=True)
        except Exception:  # noqa: BLE001 —— 审计是旁路能力，失败不影响工具执行
            logger.debug("工具审计失败（不影响执行）", exc_info=True)

    def _audit_start(self, request) -> None:
        """事前行：工具名 + 会话定位 + 敏感工具脱敏入参。"""
        tool_call = getattr(request, "tool_call", None) or {}
        name = tool_call.get("name", "")
        fields: dict = {"tool": name}
        if name in _SENSITIVE_TOOLS:
            fields["args"] = self._sanitize_args(name, tool_call.get("args", {}) or {})
        emit(
            "tool_call",
            "tool_call.start",
            session_id=self._session_id_from(request),
            **fields,
        )

    def _audit_end(
        self,
        request,
        status: str,
        error_code: str,
        retryable: bool,
        started: float,
    ) -> None:
        """事后行：三态 + 归一错误码 + 耗时（毫秒）＋ 失败时的可挽回信息。

        `retryable` / `fallback_to` **只在有错误码时写**（阶段 4 批次 3）：
        排查「这次失败能不能救、该换谁」才用得上它们，调用成功时写了只是噪声。
        两者此前都是死数据（`ToolResult.retryable` 写了无人读、注册表
        `fallback_to` 声明了无人读）——本批次接上审计这个真实读者。
        """
        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = tool_call.get("name", "")
        fields: dict = {
            "tool": tool_name,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if error_code:
            fields["error_code"] = error_code
            fields["retryable"] = retryable
            fallback = _fallback_for(tool_name)
            if fallback:
                fields["fallback_to"] = fallback
        emit(
            "tool_call",
            "tool_call.end",
            status=status,
            session_id=self._session_id_from(request),
            **fields,
        )

    @staticmethod
    def _outcome_of(result) -> tuple[str, str, bool]:
        """工具结果 → `(status, error_code, retryable)`，取自 artifact 结构化通道。

        Args:
            result: 工具执行返回值（通常是 `ToolMessage`）

        Returns:
            `(status, error_code, retryable)`；读不到信封时 `("unknown", "", False)`
            ——**如实记录"读不到"，不拿 `ToolMessage.status` 冒充三态**
            （HITL 中断等场景本就没有信封）
        """
        artifact = getattr(result, "artifact", None)
        if not isinstance(artifact, dict):
            return "unknown", "", False
        return (
            str(artifact.get("status") or "unknown"),
            str(artifact.get("error_code") or ""),
            bool(artifact.get("retryable")),
        )

    def _audit_blocked(self, tool: str, reason: str) -> None:
        """安全拦截事件（D5）：委托模块级 log_security_blocked。"""
        log_security_blocked(tool, reason)

    @staticmethod
    def _session_id_from(request) -> str:
        """会话定位：runtime.context.session_id（中间件是编译时单例，会话经请求级 context）。

        Note:
            原名 `_thread_id_from`——批次 1 随字段口径统一改名（`thread_id` 与
            `session_id` 本就是同一值，见设计稿 §3.1）。
        """
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
