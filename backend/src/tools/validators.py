"""工具参数校验器（否定禁止收口）：统一契约 + 统一审计。

**契约**（全项目统一，`@security_audit` 靠真值判断）：
- 返回 `None` → 通过
- 返回 `str`  → 拦截原因（装饰器自动记 `security/blocked` 审计）

⚠️ **本模块只"判断 + 记审计"，不阻止执行**——真正"拦"的是**调用方**：

    blocked = validate_xxx(...)
    if blocked:
        return blocked          # ← 这一行才是拦截

**收口理由（2026-10-14）**：此前 `_validate_url` 挂装饰器，
`_validate_command` / `_validate_sandbox_path` 靠**调用点手写** `log_security_blocked`
（散落 3 处）——新增调用点极易漏记。统一挂装饰器后，审计不依赖调用方自觉。

双写（工具中心规范 §2.3，缺一不可）：
- **预防**：工具 `args_schema` 的 description 写"禁止…" + JSON Schema `pattern`/`not`
- **兜底**：本模块 + `@security_audit`

设计依据：`docs/决策/2026-10-14-设计-工具中心落地-v1.md` §3.2。
"""

from __future__ import annotations

import re

from src.tools.audit import security_audit

# ── URL（安全机制 D3）：纯 http/https + 无注入字符（空格/引号/分号/<>）──
_SAFE_URL_RE = re.compile(r"^https?://[^\s\"'<>;]+$")

# ── 沙箱危险命令黑名单（能力计划 §3.4）：防 agent 误操作/恶意指令 ──
_BLOCKED_COMMAND_PREFIXES = (
    "rm -rf /", "mkfs", "shutdown", "reboot", "halt",
    "dd if=/dev/zero", "chmod -R 777 /", ":(){ :|:& };:",
)


@security_audit(tool="fetch_url")
def validate_url(url: str) -> str | None:
    """URL 严格校验：http/https + 无注入字符。

    Args:
        url: 目标 URL

    Returns:
        None=合法；str=拦截原因（security_audit 自动记审计）
    """
    if not _SAFE_URL_RE.match(url):
        return "URL 注入/协议非法"
    return None


@security_audit(tool="run_command_in_sandbox")
def validate_command(command: str) -> str | None:
    """沙箱命令校验：危险前缀拒绝（`sudo `/`env ` 前缀穿透后仍校验）。

    Args:
        command: 待执行 shell 命令

    Returns:
        None=放行；str=拒绝原因（security_audit 自动记审计）
    """
    stripped = command.strip()
    for prefix in ("sudo ", "env "):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):].lstrip()
    for bad in _BLOCKED_COMMAND_PREFIXES:
        if stripped.startswith(bad):
            return f"命令被沙箱安全策略拒绝（危险操作：{bad}…），请换一种方式。"
    return None


@security_audit(tool="sandbox_path")
def validate_sandbox_path(filename: str) -> str | None:
    """沙箱内路径校验：禁 `../` 逃逸与绝对路径。

    ⚠️ 三个工具共用（`upload_workspace_file` / `download_sandbox_file` /
    `run_code_in_sandbox`），故审计 `tool` 取通用名 `sandbox_path`；
    **具体是哪个工具**由 `ToolAuditMiddleware` 的 tool_call 行给出。

    Args:
        filename: workspace 相对文件名（如 "main.py"、"sub/x.py"）

    Returns:
        None=放行；str=拒绝原因（security_audit 自动记审计）
    """
    parts = filename.replace("\\", "/").split("/")
    if filename.startswith("/") or any(p == ".." for p in parts):
        return "沙箱路径不合法：仅允许 workspace 相对路径，禁 ../ 与绝对路径。"
    return None
