"""MCP 治理元数据单测（D2 批次 1）：声明类型 + 缓存 + 仓储。

覆盖三层：
1. `McpToolPolicy`：挂载名推导 / JSON 列解析 / → `RetryPolicy` 转换
2. 缓存：预加载 / 按挂载名查 / 未登记返回 None / 读表失败沿用旧缓存 / reset
3. 仓储：真实 PG（按需 `pg_schema`）——建表 + upsert 幂等 + 删除

设计依据：`docs/决策/2026-10-15-设计-工具动态注册两方案对比-v1.md` §8.1/§8.2。
"""

from __future__ import annotations

import pytest

from src.tools.channels import mcp_meta
from src.tools.channels.mcp_meta import McpToolPolicy


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例前后清缓存（模块级全局状态，防用例间串味）。"""
    mcp_meta.reset()
    yield
    mcp_meta.reset()


def _row(**over) -> dict:
    """造一条 DB 行（字段与 mcp_tool_meta 表一致）。"""
    row = {
        "server_name": "exa",
        "tool_name": "web_search",
        "risk_level": "low",
        "requires_approval": 0,
        "allowed_decisions": "[]",
        "is_idempotent": 1,
        "retry": "",
        "note": "",
    }
    row.update(over)
    return row


class TestMcpToolPolicy:
    """声明类型本身：挂载名 / JSON 解析 / 重试转换。"""

    def test_qualified_name_matches_prefix_convention(self) -> None:
        """挂载名 = `{server}_{tool}`——必须与 tool_name_prefix=True 对齐。"""
        p = McpToolPolicy(server_name="exa", tool_name="web_search")
        assert p.qualified_name == "exa_web_search"

    def test_requires_approval_uses_int_column(self) -> None:
        """DB 的 0/1 整数列 → bool（避免 `bool(0)` 之外的隐式真值坑）。"""
        assert mcp_meta._row_to_policy(_row(requires_approval=1)).requires_approval is True
        assert mcp_meta._row_to_policy(_row(requires_approval=0)).requires_approval is False

    def test_json_columns_parsed(self) -> None:
        """`allowed_decisions`（JSON 数组）与 `retry`（JSON 对象）正确解析。"""
        p = mcp_meta._row_to_policy(
            _row(
                allowed_decisions='["approve", "reject"]',
                retry='{"retries": 2, "delays": [0.5, 1.0]}',
            )
        )
        assert p.allowed_decisions == ("approve", "reject")
        assert p.retry == {"retries": 2, "delays": [0.5, 1.0]}

    def test_malformed_json_falls_back(self) -> None:
        """坏 JSON → 回落到默认值（一行脏数据不该拖垮整次加载）。"""
        p = mcp_meta._row_to_policy(_row(allowed_decisions="{坏", retry="{也坏"))
        assert p.allowed_decisions == ()
        assert p.retry is None

    def test_to_retry_policy_none_when_unset(self) -> None:
        """未配 retry → None（不重试）。"""
        assert McpToolPolicy(server_name="s", tool_name="t").to_retry_policy() is None

    def test_to_retry_policy_maps_fields(self) -> None:
        """配了 retry → RetryPolicy；`extra_exceptions` 恒空（MCP 异常由 _SafeTool 兜底）。"""
        p = McpToolPolicy(
            server_name="s", tool_name="t", retry={"retries": 3, "delays": [1.0]}
        )
        rp = p.to_retry_policy()
        assert rp is not None
        assert (rp.retries, rp.delays, rp.extra_exceptions) == (3, (1.0,), ())

    def test_to_retry_policy_uses_defaults_for_partial_config(self) -> None:
        """只写 `{"retries": 1}` → delays/extra 走默认，不因缺字段炸。"""
        rp = McpToolPolicy(
            server_name="s", tool_name="t", retry={"retries": 1}
        ).to_retry_policy()
        assert rp is not None and rp.retries == 1 and len(rp.delays) > 0


class TestCache:
    """进程内缓存：预加载 / 查询 / 降级 / 隔离。"""

    async def test_load_then_lookup_by_qualified_name(self, mocker) -> None:
        """预加载后可按挂载名查到；`is_loaded()` 转 True。"""
        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=[_row()]),
        )
        assert mcp_meta.is_loaded() is False

        count = await mcp_meta.load_policies(object())

        assert count == 1
        assert mcp_meta.is_loaded() is True
        assert mcp_meta.policy_for("exa_web_search") is not None
        assert mcp_meta.registered_names() == {"exa_web_search"}

    async def test_unregistered_returns_none(self, mocker) -> None:
        """未登记 → None（调用方据此拒绝挂载，定案 X1 fail-closed）。"""
        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=[_row()]),
        )
        await mcp_meta.load_policies(object())

        assert mcp_meta.policy_for("exa_other_tool") is None

    async def test_reload_replaces_previous_state(self, mocker) -> None:
        """重复加载是覆盖而非累加（删掉的元数据不该留在缓存里）。"""
        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=[_row()]),
        )
        await mcp_meta.load_policies(object())

        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=[]),
        )
        await mcp_meta.load_policies(object())

        assert mcp_meta.policy_for("exa_web_search") is None
        assert mcp_meta.all_policies() == []

    async def test_load_failure_keeps_previous_cache(self, mocker) -> None:
        """读表失败 → 不清空既有缓存、不抛异常（沿用上次可用状态，降级留痕）。"""
        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=[_row()]),
        )
        await mcp_meta.load_policies(object())

        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(side_effect=RuntimeError("db boom")),
        )
        count = await mcp_meta.load_policies(object())  # 不应抛

        assert count == 1, "失败时返回既有条数"
        assert mcp_meta.policy_for("exa_web_search") is not None, "旧缓存必须保住"

    async def test_all_policies_sorted(self, mocker) -> None:
        """all_policies 排序稳定（供审批配置与待登记清单，顺序可预期）。"""
        rows = [
            _row(server_name="zeta", tool_name="a"),
            _row(server_name="alpha", tool_name="b"),
        ]
        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=rows),
        )
        await mcp_meta.load_policies(object())

        assert [p.qualified_name for p in mcp_meta.all_policies()] == [
            "alpha_b",
            "zeta_a",
        ]


class TestGovernedTools:
    """治理接线（批次 2）：过滤未登记 + 给幂等工具挂重试。

    最关键的一条是 `test_retry_actually_retries`——它证明重试**真的在
    `_SafeTool` 内层生效**，而不是被外层兜底吞掉后空转（P4 踩过的坑）。
    """

    @staticmethod
    def _flaky(name: str, fail_times: int, counter: dict):
        """造一个"前 N 次必失败"的 MCP 工具（失败用 httpx.ConnectError，
        属 retry_tool 内置的可重试网络异常）。"""
        import httpx
        from langchain_core.tools import tool

        async def _run(query: str = "") -> str:
            counter["n"] += 1
            if counter["n"] <= fail_times:
                raise httpx.ConnectError("boom")
            return "ok"

        return tool(name, description="flaky")(_run)

    def _register(self, mocker, *policies: dict) -> None:
        """把给定元数据塞进缓存（走真实解析路径，不直接改内部 dict）。"""
        rows = [_row(**p) for p in policies]
        mocker.patch(
            "src.db.mcp_meta_repository.list_meta_rows",
            new=mocker.AsyncMock(return_value=rows),
        )

    async def test_unregistered_is_filtered_out(self, mocker) -> None:
        """未登记 → 剔除（fail-closed，定案 X1）。"""
        from langchain_core.tools import tool

        from src.tools.channels.mcp_client import wrap_safe

        self._register(mocker, {"tool_name": "known"})  # 只登记 known
        await mcp_meta.load_policies(object())

        known = wrap_safe(tool("exa_known", description="d")(lambda: "ok"))
        unknown = wrap_safe(tool("exa_unknown", description="d")(lambda: "ok"))

        kept = mcp_meta.governed_tools([known, unknown])

        assert [t.name for t in kept] == ["exa_known"]

    async def test_pending_lists_unregistered(self, mocker) -> None:
        """待登记清单 = 已拉取 − 已登记（管理 API 暴露，把"缺失"变"待办"）。"""
        from langchain_core.tools import tool

        from src.tools.channels.mcp_client import wrap_safe

        self._register(mocker, {"tool_name": "known"})
        await mcp_meta.load_policies(object())

        tools = [
            wrap_safe(tool(n, description="d")(lambda: "ok"))
            for n in ("exa_known", "exa_unknown", "exa_another")
        ]
        assert mcp_meta.pending_tool_names(tools) == ["exa_another", "exa_unknown"]

    async def test_retry_actually_retries(self, mocker) -> None:
        """幂等工具的重试**真的生效**：前 2 次失败 → 第 3 次成功。

        若重试被包在 `_SafeTool` 外层（或没挂），本用例会看到 n==1（空转）。
        """
        from src.tools.channels.mcp_client import wrap_safe

        self._register(
            mocker,
            {"tool_name": "flaky", "is_idempotent": 1,
             "retry": '{"retries": 2, "delays": [0, 0]}'},
        )
        await mcp_meta.load_policies(object())

        counter = {"n": 0}
        raw = self._flaky("exa_flaky", fail_times=2, counter=counter)

        kept = mcp_meta.governed_tools([wrap_safe(raw)])

        result = await kept[0].ainvoke({"query": "x"})
        assert result == "ok"
        assert counter["n"] == 3, "1 首发 + 2 重试；只有 1 说明重试空转"

    async def test_non_idempotent_does_not_retry(self, mocker) -> None:
        """非幂等 → 不重试（写操作重试有幂等风险）；失败由兜底转字符串。"""
        from src.tools.channels.mcp_client import wrap_safe

        self._register(mocker, {"tool_name": "flaky", "is_idempotent": 0})
        await mcp_meta.load_policies(object())

        counter = {"n": 0}
        raw = self._flaky("exa_flaky", fail_times=99, counter=counter)

        kept = mcp_meta.governed_tools([wrap_safe(raw)])

        result = await kept[0].ainvoke({"query": "x"})
        assert counter["n"] == 1, "只调一次"
        assert "工具执行失败" in result, "失败降级为字符串（不中断 run）"

    async def test_idempotent_without_retry_config_still_no_retry(self, mocker) -> None:
        """声明幂等但没配 retry → 不重试（幂等只是"允许重试"，不是"必须重试"）。"""
        from src.tools.channels.mcp_client import wrap_safe

        self._register(mocker, {"tool_name": "flaky", "is_idempotent": 1, "retry": ""})
        await mcp_meta.load_policies(object())

        counter = {"n": 0}
        raw = self._flaky("exa_flaky", fail_times=99, counter=counter)

        kept = mcp_meta.governed_tools([wrap_safe(raw)])
        await kept[0].ainvoke({"query": "x"})

        assert counter["n"] == 1


class TestRepository:
    """仓储：真实 PG 读写（按需请求 `pg_schema`，非 autouse）。"""

    async def test_table_created_and_roundtrip(self, pg_schema) -> None:
        """建表随 init_schema 完成；upsert → 读回字段一致。"""
        from src.db import connection as db_conn
        from src.db import mcp_meta_repository as repo

        async with db_conn.connection() as conn:
            await repo.upsert_meta(
                conn,
                "exa",
                "web_search",
                risk_level="medium",
                requires_approval=True,
                allowed_decisions=["approve", "reject"],
                is_idempotent=True,
                retry={"retries": 2, "delays": [0.5, 1.0]},
                note="只读搜索",
            )
            rows = await repo.list_meta_rows(conn)

        assert len(rows) == 1
        row = rows[0]
        assert (row["server_name"], row["tool_name"]) == ("exa", "web_search")
        assert row["risk_level"] == "medium"
        assert bool(row["requires_approval"]) is True
        assert bool(row["is_idempotent"]) is True
        assert row["note"] == "只读搜索"

    async def test_upsert_is_idempotent_on_same_key(self, pg_schema) -> None:
        """同 (server, tool) 再 upsert 是更新而非插两行（复合唯一键生效）。"""
        from src.db import connection as db_conn
        from src.db import mcp_meta_repository as repo

        async with db_conn.connection() as conn:
            await repo.upsert_meta(conn, "exa", "web_search", risk_level="low")
            await repo.upsert_meta(conn, "exa", "web_search", risk_level="high")
            rows = await repo.list_meta_rows(conn)

        assert len(rows) == 1
        assert rows[0]["risk_level"] == "high", "第二次应更新覆盖"

    async def test_delete_by_server_clears_all(self, pg_schema) -> None:
        """按 server 删除清空该 server 全部元数据（防同名 server 复用旧声明）。"""
        from src.db import connection as db_conn
        from src.db import mcp_meta_repository as repo

        async with db_conn.connection() as conn:
            await repo.upsert_meta(conn, "exa", "a")
            await repo.upsert_meta(conn, "exa", "b")
            await repo.upsert_meta(conn, "other", "c")

            deleted = await repo.delete_by_server(conn, "exa")
            rows = await repo.list_meta_rows(conn)

        assert deleted == 2
        assert [r["server_name"] for r in rows] == ["other"]
