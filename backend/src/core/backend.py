"""Agent Backend 工厂：会话级组合存储 + 双层权限（2026-08-04 深化 v3）。

分层（写操作拦截顺序）：
  上层——FilesystemPermission 声明式规则（main_agent.py 配置，见 core/permissions.py）：
        /skills/** 写 deny；高危路径 interrupt 人工审批（开关门控）；子代理独立覆盖
  下层——PolicyBackend 拦截钩子（本文件）：
        兜底拦截所有经 backend 协议的路径访问（防上层漏配/未来新工具直写），
        统一审计日志（写全量 + 拒绝，audit logger → JSONL 扁平行）

修正（评审拍板，2026-08-04）：
  1. PolicyBackend 白名单委托——读/查询方法白名单放行；写关键字方法先过策略；
     未知可调用 raise AttributeError（防新增方法绕过 __getattr__）
  2. 审计输出统一扁平 JSON 行（ts/thread_id/layer/op/path/decision/policy 顶层）
  3. 内存模式（StateBackend）default 路由同样经策略包装，行为一致

开关（config.py）：
  MEMORY_WORKSPACE         True → default 切 StateBackend（dev 测试兼容）
  BACKEND_POLICY_ENABLED   False → PolicyBackend 透明直通（测试/排查）
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

from src.core.config import settings
from src.core.paths import (
    get_exports_dir,
    get_memory_dir,
    get_skill_md_dir,
    get_static_skills_dir,
    get_workspace_dir,
)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

# 工作区临时文件过期天数（cleanup_workspace 默认）
WORKSPACE_CLEANUP_DAYS = 30

# ── 白名单（修正 1：防 __getattr__ 绕过）──

# 确认安全的读/查询类方法：直接委托内层（含 async 变体；download 是 backend 读）
_READ_WHITELIST = frozenset(
    {
        "read", "aread", "ls", "als", "glob", "aglob", "grep", "agrep",
        "download_files", "adownload_files",
    }
)
# 写操作关键字：方法名命中任一即先过策略（deny 默认）再委托——
# 覆盖未来新增的写方法（rename/mkdir/copy 等），从根上杜绝绕过
_WRITE_KEYWORDS = (
    "write", "delete", "edit", "upload", "rename", "mkdir", "copy",
    "move", "remove", "unlink", "chmod", "truncate", "append",
    "patch", "set", "put", "create",
)


# ── 下层：Backend Policy Hooks（核心手写逻辑：策略决策 + 审计）──

@dataclass(frozen=True)
class BackendPolicyRule:
    """backend 层拦截规则：路径前缀 × 操作 × 决策。

    Attributes:
        path_prefix: 虚拟路径前缀（如 "/skills/"）；path.startswith 匹配
        operations: 适用操作集合（"write" 覆盖 write/edit/delete/upload 等）
        mode: "deny" 拒绝 + 审计；"allow" 放行（审计仍可记）
    """

    path_prefix: str
    operations: frozenset[str] = frozenset({"write"})
    mode: Literal["allow", "deny"] = "deny"


@dataclass(frozen=True)
class BackendPolicy:
    """有序规则集：先匹配先生效（第一条命中即返回）。

    Attributes:
        name: 策略名（审计日志用）
        rules: 规则元组（有序）
        audit_reads: 读操作是否审计（默认 False 防刷屏）
    """

    name: str
    rules: tuple[BackendPolicyRule, ...] = ()
    audit_reads: bool = False

    def decide(self, op: str, path: str) -> Literal["allow", "deny"]:
        """策略决策：返回 allow/deny。

        Args:
            op: 操作（write/read）
            path: 虚拟路径（如 "/skills/market/x.md"）

        Returns:
            "deny" 或 "allow"
        """
        for rule in self.rules:
            if op in rule.operations and path.startswith(rule.path_prefix):
                return rule.mode
        return "allow"


# ── 策略模板（backend 层兜底）──

SKILL_READONLY_POLICY = BackendPolicy(
    name="skills-readonly",
    rules=(BackendPolicyRule("/skills/", frozenset({"write"}), "deny"),),
)
READONLY_POLICY = BackendPolicy(
    name="readonly",
    rules=(BackendPolicyRule("/", frozenset({"write"}), "deny"),),
)
WORKSPACE_POLICY = BackendPolicy(name="workspace")   # 允许 + 写审计
MEMORY_POLICY = BackendPolicy(name="memories")       # 允许 + 写审计
EXPORT_POLICY = BackendPolicy(name="exports")        # 允许 + 写审计


class PolicyBackend:
    """策略拦截后端：包装内层 backend，写操作先过策略再执行（兜底防线）。

    与上层 Permissions 的区别：上层拦截 agent 的 7 个文件工具调用（工具层），
    本类拦截所有经 backend 协议的路径访问（协议层）——上层规则漏配、
    未来新增文件类工具直写 backend 时，仍在此被策略兜底并审计。

    委托策略（修正 1，防 __getattr__ 绕过）：
    - 协议写方法（write/edit/delete/upload_files 及 async 变体）显式守卫
    - 读/查询白名单方法直接委托；方法名含写关键字 → 先过策略再委托
    - 其余未知可调用 raise AttributeError（hasattr 返回 False，防静默绕过）
    - 属性（非 callable）正常委托

    Attributes:
        _inner: 被包装的 backend（FilesystemBackend / StateBackend 等）
        _policy: 策略规则集
        _thread_id: 审计字段（会话定位）
    """

    def __init__(self, inner: Any, policy: BackendPolicy, *, thread_id: str = "") -> None:
        self._inner = inner
        self._policy = policy
        self._thread_id = thread_id

    def __getattr__(self, name: str):
        """三路分派：白名单读委托 / 写关键字守卫 / 未知可调用拒绝；属性委托。"""
        inner_attr = getattr(self._inner, name)
        if callable(inner_attr):
            if name in _READ_WHITELIST:
                return inner_attr
            if any(keyword in name for keyword in _WRITE_KEYWORDS):
                return self._guarded_delegate(name, inner_attr)
            raise AttributeError(f"PolicyBackend 不支持的方法：{name}")
        return inner_attr

    # ── 写操作：先决策再执行（显式方法，路径已知）──

    def write(self, *args, **kwargs):
        self._guard("write", args[0] if args else None)
        return self._inner.write(*args, **kwargs)

    def awrite(self, *args, **kwargs):
        self._guard("write", args[0] if args else None)
        return self._inner.awrite(*args, **kwargs)

    def edit(self, *args, **kwargs):
        self._guard("write", args[0] if args else None)
        return self._inner.edit(*args, **kwargs)

    def aedit(self, *args, **kwargs):
        self._guard("write", args[0] if args else None)
        return self._inner.aedit(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard("write", args[0] if args else None)
        return self._inner.delete(*args, **kwargs)

    def adelete(self, *args, **kwargs):
        self._guard("write", args[0] if args else None)
        return self._inner.adelete(*args, **kwargs)

    def upload_files(self, *args, **kwargs):
        self._guard("write", self._first_upload_path(args))
        return self._inner.upload_files(*args, **kwargs)

    def aupload_files(self, *args, **kwargs):
        self._guard("write", self._first_upload_path(args))
        return self._inner.aupload_files(*args, **kwargs)

    # ── 读操作：read 可选审计，其余白名单透传 ──

    def read(self, *args, **kwargs):
        if self._policy.audit_reads:
            self._audit("read", args[0] if args else "", "allow")
        return self._inner.read(*args, **kwargs)

    def aread(self, *args, **kwargs):
        if self._policy.audit_reads:
            self._audit("read", args[0] if args else "", "allow")
        return self._inner.aread(*args, **kwargs)

    def grep(self, pattern: str, path: str | None = None, *, max_count: int | None = None):
        # 保留 max_count 关键字签名（deepagents _method_accepts_max_count inspect 兼容）
        return self._inner.grep(pattern, path=path, max_count=max_count)

    def agrep(self, pattern: str, path: str | None = None, *, max_count: int | None = None):
        return self._inner.agrep(pattern, path=path, max_count=max_count)

    # ── 内部：守卫 / 审计 / 委托 ──

    def _guarded_delegate(self, name: str, inner_attr):
        """写关键字未知方法守卫：路径不可解析默认 deny（fail-safe），可解析先过策略。"""

        def guarded(*args, **kwargs):
            path = args[0] if args and isinstance(args[0], str) else None
            self._guard("write", path)
            return inner_attr(*args, **kwargs)

        return guarded

    def _first_upload_path(self, args: tuple) -> str | None:
        """upload_files 首文件路径提取（files: list[tuple[str, bytes]]）；异常 → None（默认 deny）。"""
        try:
            return args[0][0][0]  # type: ignore[index]
        except (IndexError, TypeError, KeyError):
            return None

    def _guard(self, op: str, path: str | None) -> None:
        if path is None:
            self._audit(op, "<unknown>", "deny")
            raise PermissionError(f"策略拒绝：{self._policy.name} 禁止 {op}（路径不可解析）")
        decision = self._policy.decide(op, path)
        self._audit(op, path, decision)
        if decision == "deny":
            if not audit_logger.handlers:  # 审计未配置（未调 setup_logging）时回落模块日志
                logger.warning(
                    "backend 策略拦截：%s %s（thread=%s，policy=%s）——拒绝",
                    op, path, self._thread_id, self._policy.name,
                )
            raise PermissionError(f"策略拒绝：{self._policy.name} 禁止 {op} {path}")

    def _audit(self, op: str, path: str, decision: str) -> None:
        """扁平 JSON 审计行（修正 2）：字段全在顶层，每行一个完整 JSON 对象。"""
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "thread_id": self._thread_id,
            "layer": "policy_backend",
            "op": op,
            "path": path,
            "decision": decision,
            "policy": self._policy.name,
        }
        audit_logger.info(json.dumps(record, ensure_ascii=False))


class ReadOnlyBackend(PolicyBackend):
    """只读包装（v2.0 兼容类）：统一为 PolicyBackend + 全路径写拒绝策略。

    技能目录只读的强制实现（v2 硬缺陷 2）；v3 起 create_backend 改用
    SKILL_READONLY_POLICY 包装，本类保留兼容旧引用/测试（语义不变：
    全部写操作拒绝，读操作透传）。
    """

    def __init__(self, root_dir: Path) -> None:
        super().__init__(
            FilesystemBackend(root_dir=root_dir, virtual_mode=True),
            READONLY_POLICY,
        )


def _wrap(inner, policy: BackendPolicy, thread_id: str):
    """策略层包装：BACKEND_POLICY_ENABLED=False 时透明直通（零开销，测试/排查用）。"""
    if not settings.backend_policy_enabled:
        return inner
    return PolicyBackend(inner, policy, thread_id=thread_id)


def create_backend(thread_id: str, *, memory_workspace: bool | None = None) -> CompositeBackend:
    """按会话构建组合 backend（default 路由绑 thread_id 目录，会话文件隔离）。

    Args:
        thread_id: 会话 ID（== session_id，backend 文件根绑定它）
        memory_workspace: 覆盖内存模式（缺省读 settings.memory_workspace）

    Returns:
        CompositeBackend——default=workspace/{thread_id}（或 StateBackend），
        路由：/memories/、/skills/static/（只读策略）、/skills/market/（只读策略）、/exports/，
        全部经 PolicyBackend 策略包装（修正 3：内存模式 default 同样包装）
    """
    use_memory = settings.memory_workspace if memory_workspace is None else memory_workspace
    inner_default = (
        StateBackend()
        if use_memory
        else FilesystemBackend(root_dir=get_workspace_dir() / thread_id, virtual_mode=True)
    )
    default = _wrap(inner_default, WORKSPACE_POLICY, thread_id)
    return CompositeBackend(
        default=default,
        routes={
            "/memories/": _wrap(
                FilesystemBackend(root_dir=get_memory_dir(), virtual_mode=True),
                MEMORY_POLICY, thread_id,
            ),
            # ⚠️ 路由内层策略用全路径 deny（READONLY_POLICY）而非 /skills/ 前缀——
            # CompositeBackend 路由后传给内层 backend 的路径已剥掉虚拟前缀
            # （"/skills/market/x.md" → "/x.md"），前缀匹配会失效（实测踩坑）。
            # 每个 route 的 PolicyBackend 只管控自己路由，全路径 deny 语义即"该路由只读"。
            "/skills/static/": _wrap(
                FilesystemBackend(root_dir=get_static_skills_dir(), virtual_mode=True),
                READONLY_POLICY, thread_id,
            ),
            "/skills/market/": _wrap(
                FilesystemBackend(root_dir=get_skill_md_dir(), virtual_mode=True),
                READONLY_POLICY, thread_id,
            ),
            "/exports/": _wrap(
                FilesystemBackend(root_dir=get_exports_dir(), virtual_mode=True),
                EXPORT_POLICY, thread_id,
            ),
        },
    )


def cleanup_workspace(thread_id: str, older_than_days: int = WORKSPACE_CLEANUP_DAYS) -> int:
    """清理会话工作区过期临时文件（mtime 超期删除，返回删除数）。

    磁盘持久化后 Agent 草稿/临时代码会堆积——会话删除时调用（older_than_days=0
    全量清理）+ 定期巡检（可选）。内存模式（StateBackend）无文件可清理，返回 0。

    Args:
        thread_id: 会话 ID
        older_than_days: 超过该天数的文件删除

    Returns:
        删除的文件数
    """
    workspace = get_workspace_dir() / thread_id
    if not workspace.exists():
        return 0
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for f in workspace.rglob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                logger.warning("清理失败：%s", f)
    logger.info("workspace 清理：thread=%s 删除 %d 个过期文件", thread_id, removed)
    return removed
