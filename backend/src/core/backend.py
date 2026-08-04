"""Agent Backend 工厂：会话级组合存储（2026-08-04 设计 v2.0）。

- `create_backend(thread_id)`：按会话构建——default 绑 `data/workspace/{thread_id}/`
  （会话文件隔离，v2 硬缺陷 1 修复）；技能路由 ReadOnlyBackend 只读强制（硬缺陷 2）
- `USE_MEMORY_WORKSPACE`（settings.memory_workspace）：default 切 StateBackend
  （dev 测试兼容"重启清空"内存语义，v2 隐患 3）
- `cleanup_workspace(thread_id)`：会话临时文件过期清理（v2 隐患 1）
- FilesystemBackend 无连接 → 无 lifespan 需求（区别于 checkpointer/store 的 async 连接）
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

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

# 工作区临时文件过期天数（cleanup_workspace 默认）
WORKSPACE_CLEANUP_DAYS = 30


class ReadOnlyBackend:
    """只读包装：拦截技能目录的写操作（代码强制，非文档约定，v2 硬缺陷 2）。

    - /skills/static/、/skills/market/ 用此包装——Agent 无法篡改/删除技能文件
    - 拦截操作抛 PermissionError + 日志（越权写入可追踪）
    - 读操作（read/ls/glob/grep 等）经 __getattr__ 委托底层 FilesystemBackend

    Attributes:
        _inner: 底层文件 backend（virtual_mode 防路径逃逸）
    """

    _WRITE_METHODS = ("write", "edit", "delete", "upload_files")

    def __init__(self, root_dir: Path) -> None:
        self._inner = FilesystemBackend(root_dir=root_dir, virtual_mode=True)

    def __getattr__(self, name: str):
        """读操作委托底层；写操作已在方法级拦截（防 __getattr__ 绕过）。"""
        return getattr(self._inner, name)

    def write(self, *args, **kwargs):
        self._deny("write", args)

    def edit(self, *args, **kwargs):
        self._deny("edit", args)

    def delete(self, *args, **kwargs):
        self._deny("delete", args)

    def upload_files(self, *args, **kwargs):
        self._deny("upload_files", args)

    def _deny(self, op: str, args: tuple) -> None:
        path = args[0] if args else "?"
        logger.warning("只读拦截：Agent 尝试 %s（path=%s）——技能目录只读，拒绝写入", op, path)
        raise PermissionError(f"技能目录只读：禁止 {op} {path}")


def create_backend(thread_id: str, *, memory_workspace: bool | None = None) -> CompositeBackend:
    """按会话构建组合 backend（default 路由绑 thread_id 目录，会话文件隔离）。

    Args:
        thread_id: 会话 ID（== session_id，backend 文件根绑定它）
        memory_workspace: 覆盖内存模式（缺省读 settings.memory_workspace）

    Returns:
        CompositeBackend——default=workspace/{thread_id}（或 StateBackend），
        路由：/memories/、/skills/static/（只读）、/skills/market/（只读）、/exports/
    """
    use_memory = settings.memory_workspace if memory_workspace is None else memory_workspace
    default = (
        StateBackend()
        if use_memory
        else FilesystemBackend(root_dir=get_workspace_dir() / thread_id, virtual_mode=True)
    )
    return CompositeBackend(
        default=default,
        routes={
            "/memories/": FilesystemBackend(root_dir=get_memory_dir(), virtual_mode=True),
            "/skills/static/": ReadOnlyBackend(get_static_skills_dir()),
            "/skills/market/": ReadOnlyBackend(get_skill_md_dir()),
            "/exports/": FilesystemBackend(root_dir=get_exports_dir(), virtual_mode=True),
        },
    )


def cleanup_workspace(thread_id: str, older_than_days: int = WORKSPACE_CLEANUP_DAYS) -> int:
    """清理会话工作区过期临时文件（mtime 超期删除，返回删除数）。

    磁盘持久化后 Agent 草稿/临时代码会堆积——会话删除时调用 +
    定期巡检（可选）。内存模式（StateBackend）无文件可清理，返回 0。

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
