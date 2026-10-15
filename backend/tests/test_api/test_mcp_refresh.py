"""MCP 热刷新回归锁（2026-10-15 修 G1）。

**为什么立这条锁**：改 MCP 配置有三条路径（市场安装/启停/卸载、连接启停、
连接删除），此前各写各的——两条漏了 `rebuild_agent()`（老会话仍用旧工具清单），
一条连 `reload()` 都没有（已删 server 的工具仍在图里）。三条路径**都没有测试**，
所以漂移一直没被发现。

本文件锁两件事：
1. `mcp_service.refresh_agent_tools()` 自身行为（两件事都做 / 失败不阻断但图仍失效）
2. **三条 API 路径都经过它**（结构锁——防某条路径又偷懒不调用）
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from src.agent.services import mcp_service


def _body_source(func) -> str:
    """取函数**代码体**源码（剔除 docstring 与注释）。

    ⚠️ 必须剔 docstring：本文件的断言是"源码里有没有出现某个调用"，而 docstring
    里可能**讲解**历史实现（如"原本自有一份 reload + rebuild_agent"）——不剔的话
    讲解文字会让断言假通过（本文件首版就踩了这个坑，自检抓出）。
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    first = node.body[0] if node.body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        node.body = node.body[1:]  # 去掉 docstring
    return ast.unparse(node)


class _FakeAsyncCtx:
    """假的 `async with connection() as conn`（热刷新只借连接、不做 SQL 断言）。"""

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc) -> bool:
        return False


@pytest.fixture
def spy(monkeypatch):
    """替换掉外部依赖（DB 连接 / MCP reload / rebuild_agent），记录调用。

    Returns:
        SimpleNamespace(events=[...], reload_raises=bool)
    """
    from types import SimpleNamespace

    recorded: list[str] = []
    state = SimpleNamespace(events=recorded, reload_raises=False)

    monkeypatch.setattr(mcp_service.db_conn, "connection", lambda: _FakeAsyncCtx())

    class _Manager:
        async def reload(self, conn):
            if state.reload_raises:
                raise RuntimeError("reload boom")
            recorded.append("reload")

    monkeypatch.setattr(mcp_service, "get_mcp_client_manager", lambda: _Manager())

    import src.agent.main_agent as main_agent

    monkeypatch.setattr(
        main_agent, "rebuild_agent", lambda *a, **k: recorded.append("rebuild")
    )
    return state


class TestRefreshAgentTools:
    """唯一入口的行为：先 reload 再 rebuild，失败也不能只剩半截。"""

    async def test_does_both_in_order(self, spy) -> None:
        """正常：reload 在前、rebuild 在后（顺序不可颠倒）。"""
        await mcp_service.refresh_agent_tools()
        assert spy.events == ["reload", "rebuild"], "必须两件事都做，且先 reload"

    async def test_reload_failure_still_invalidates_agent(self, spy) -> None:
        """reload 失败 → 不抛异常（不阻断管理操作），但 Agent 缓存仍要失效。"""
        spy.reload_raises = True

        await mcp_service.refresh_agent_tools()  # 不应抛

        assert spy.events == ["rebuild"], "reload 失败也要 rebuild，否则老会话留旧图"

    async def test_does_not_raise_to_caller(self, spy) -> None:
        """契约：调用方无需 try/except（热刷新是旁路动作，失败只记日志）。"""
        spy.reload_raises = True
        assert await mcp_service.refresh_agent_tools() is None


class TestAllPathsGoThroughRefresher:
    """结构锁：三条改 MCP 配置的路径都必须调 `refresh_agent_tools`。

    源码级断言（取 handler 源码查调用）——因为这三条路径**都要连 PG + 鉴权**才有
    完整集成测试，源码级锁能以零成本拦住"新写一条路径又忘了刷新"。
    """

    @staticmethod
    def _calls_refresher(func) -> bool:
        return "refresh_agent_tools" in _body_source(func)

    def test_patch_toggles_refresh(self) -> None:
        from src.api.mcp_servers import update_mcp_server

        assert self._calls_refresher(update_mcp_server), "启停路径漏了热刷新"

    def test_delete_refreshes(self) -> None:
        from src.api.mcp_servers import delete_mcp_server

        assert self._calls_refresher(delete_mcp_server), (
            "删除路径漏了热刷新——已删 server 的工具会留在图里"
        )

    def test_skills_path_refreshes(self) -> None:
        from src.api import skills

        assert self._calls_refresher(skills._refresh_agent_tools), (
            "市场安装/启停/卸载路径漏了热刷新"
        )

    def test_only_one_implementation(self) -> None:
        """唯一入口锁：`api/skills.py` **不得**再自己实现 reload/rebuild。

        否则又变两处真相源（本文件立的初衷）。
        """
        from src.api import skills

        src = _body_source(skills._refresh_agent_tools)
        assert "rebuild_agent" not in src and "reload(" not in src, (
            "skills.py 又长出了自己的热刷新实现——应只转发 mcp_service"
        )
