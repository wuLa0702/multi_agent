"""CompositeBackend 会话级组合存储测试（v2.0 设计文档 §2.5）。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 会话隔离：不同 thread_id 文件根互不污染
- 并发隔离：多协程写不同 thread_id → 各落各自目录
- 只读强制：/skills/ 路由 write/edit/delete → PermissionError
- 路由：/memories/、/exports/ 各落对应目录
- 内存模式：memory_workspace=True → default 为 StateBackend（无磁盘文件）
- 清理：cleanup_workspace 删除过期、保留新鲜
- 路径：get_static_skills_dir 自动初始化 README
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.core.backend import ReadOnlyBackend, cleanup_workspace, create_backend
from src.core.paths import get_static_skills_dir


# ── 会话隔离 / 路由 ──

def test_session_isolation(tmp_path, monkeypatch) -> None:
    """会话隔离：thread A/B 各自 workspace 目录，互不污染。"""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setattr("src.core.backend.get_workspace_dir", lambda: tmp_path / "ws")
    backend_a = create_backend("session-a", memory_workspace=False)
    backend_b = create_backend("session-b", memory_workspace=False)

    backend_a.write("/note.txt", "hello-a")
    backend_b.write("/note.txt", "hello-b")

    assert (tmp_path / "ws" / "session-a" / "note.txt").read_text(encoding="utf-8") == "hello-a"
    assert (tmp_path / "ws" / "session-b" / "note.txt").read_text(encoding="utf-8") == "hello-b"
    # 互不污染：A 的目录没有 B 的内容（同一文件名各自独立）
    assert (tmp_path / "ws" / "session-a").exists() and (tmp_path / "ws" / "session-b").exists()


def test_route_export_and_memory(tmp_path, monkeypatch) -> None:
    """路由：/exports/、/memories/ 各落对应目录。"""
    monkeypatch.setattr("src.core.backend.get_workspace_dir", lambda: tmp_path / "ws")
    monkeypatch.setattr("src.core.backend.get_exports_dir", lambda: tmp_path / "exports")
    monkeypatch.setattr("src.core.backend.get_memory_dir", lambda: tmp_path / "memory")
    monkeypatch.setattr("src.core.backend.get_static_skills_dir", lambda: tmp_path / "skills-static")
    monkeypatch.setattr("src.core.backend.get_skill_md_dir", lambda: tmp_path / "skills-market")

    backend = create_backend("s1", memory_workspace=False)
    backend.write("/exports/report.md", "report")
    backend.write("/memories/facts.md", "facts")

    assert (tmp_path / "exports" / "report.md").read_text(encoding="utf-8") == "report"
    assert (tmp_path / "memory" / "facts.md").read_text(encoding="utf-8") == "facts"


def test_readonly_backend_blocks_writes(tmp_path) -> None:
    """只读强制：/skills/ 路由写操作抛 PermissionError（v2 硬缺陷 2）。"""
    ro = ReadOnlyBackend(tmp_path / "skills")

    with pytest.raises(PermissionError):
        ro.write("/skills/x.md", "data")
    with pytest.raises(PermissionError):
        ro.edit("/skills/x.md", "data")
    with pytest.raises(PermissionError):
        ro.delete("/skills/x.md")
    # 读操作透传（委托底层）
    ro._inner.write("/skills/readable.md", "ok")
    assert ro.read("/skills/readable.md") is not None


def test_skills_routes_readonly_in_composite(tmp_path, monkeypatch) -> None:
    """组合 backend 中 /skills/ 路由只读强制。"""
    monkeypatch.setattr("src.core.backend.get_workspace_dir", lambda: tmp_path / "ws")
    monkeypatch.setattr("src.core.backend.get_skill_md_dir", lambda: tmp_path / "skills-market")
    monkeypatch.setattr("src.core.backend.get_static_skills_dir", lambda: tmp_path / "skills-static")
    monkeypatch.setattr("src.core.backend.get_memory_dir", lambda: tmp_path / "memory")
    monkeypatch.setattr("src.core.backend.get_exports_dir", lambda: tmp_path / "exports")

    backend = create_backend("s1", memory_workspace=False)
    with pytest.raises(PermissionError):
        backend.write("/skills/market/pdf.md", "hack")
    with pytest.raises(PermissionError):
        backend.write("/skills/static/skill.md", "hack")


# ── 内存模式 ──

def test_memory_workspace_mode(tmp_path, monkeypatch) -> None:
    """内存模式：memory_workspace=True → default 为 StateBackend。

    注：StateBackend 只能在 LangGraph 图执行上下文内读写（state.py 限制）——
    这里只断言类型与不落盘，不直接调 write。
    """
    from deepagents.backends import StateBackend

    monkeypatch.setattr("src.core.backend.get_workspace_dir", lambda: tmp_path / "ws")
    backend = create_backend("s1", memory_workspace=True)
    assert isinstance(backend.default, StateBackend), "内存模式 default 应为 StateBackend"
    assert not (tmp_path / "ws" / "s1").exists(), "内存模式不应创建磁盘工作区"


# ── 清理 ──

def test_cleanup_workspace(tmp_path, monkeypatch) -> None:
    """清理：过期文件删除、新鲜文件保留。"""
    monkeypatch.setattr("src.core.backend.get_workspace_dir", lambda: tmp_path / "ws")
    ws = tmp_path / "ws" / "s1"
    ws.mkdir(parents=True)
    old = ws / "old.txt"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (time.time() - 432000, time.time() - 432000))  # 5 天前（过期）
    fresh = ws / "fresh.txt"
    fresh.write_text("y", encoding="utf-8")  # 刚刚（新鲜）

    removed = cleanup_workspace("s1", older_than_days=1)  # 1 天前为界
    assert removed == 1, f"应只删过期文件，实际删 {removed}"
    assert not old.exists(), "过期文件应删除"
    assert fresh.exists(), "新鲜文件应保留"


# ── 静态技能目录自动初始化 ──

def test_static_skills_dir_auto_init(tmp_path, monkeypatch) -> None:
    """路径：get_static_skills_dir 不存在时自动创建 + README 模板。"""
    target = tmp_path / "skill-resources"
    monkeypatch.setenv("SKILL_RESOURCES_DIR", str(target))
    d = get_static_skills_dir()
    assert d == target
    assert (target / "README.md").exists()


# ── 并发隔离 ──

@pytest.mark.asyncio
async def test_concurrent_session_isolation(tmp_path, monkeypatch) -> None:
    """并发：多协程同时写不同 thread_id → 各落各自目录（无交叉）。"""
    import asyncio

    monkeypatch.setattr("src.core.backend.get_workspace_dir", lambda: tmp_path / "ws")

    async def write_session(tid: str, content: str) -> None:
        backend = create_backend(tid, memory_workspace=False)
        await asyncio.to_thread(backend.write, f"/{tid}.txt", content)

    await asyncio.gather(
        write_session("c1", "1"), write_session("c2", "2"), write_session("c3", "3")
    )
    for tid, content in [("c1", "1"), ("c2", "2"), ("c3", "3")]:
        f = tmp_path / "ws" / tid / f"{tid}.txt"
        assert f.read_text(encoding="utf-8") == content
