"""MCP 治理元数据单测（D2 批次 1）：声明类型 + 缓存 + 仓储。

覆盖三层：
1. `McpToolPolicy`：挂载名推导 / JSON 列解析 / → `RetryPolicy` 转换
2. 缓存：预加载 / 按挂载名查 / 未登记返回 None / 读表失败沿用旧缓存 / reset
3. 仓储：真实 PG（按需 `pg_schema`）——建表 + upsert 幂等 + 删除

设计依据：`docs/决策/2026-10-15-设计-工具动态注册两方案对比-v1.md` §8.1/§8.2。
"""

from __future__ import annotations

import pytest

from src.db import mcp_meta_repository as mcp_meta_repo
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


class TestDeriveDefaults:
    """MCP 注解 → 治理默认值（自动登记用；"下载即用"的核心推导）。"""

    def test_readonly_low_risk_no_approval_and_idempotent(self) -> None:
        """readOnlyHint → 低危 + 免审批 + 幂等（幂等才配重试）。"""
        d = mcp_meta.derive_defaults({"readOnlyHint": True})
        assert d["risk_level"] == "low"
        assert d["requires_approval"] is False
        assert d["is_idempotent"] is True
        assert d["retry"] is not None, "只读幂等 → 挂重试"

    def test_destructive_requires_approval(self) -> None:
        """destructiveHint → 高危 + **需审批**（approve/reject）。"""
        d = mcp_meta.derive_defaults({"destructiveHint": True})
        assert d["risk_level"] == "high"
        assert d["requires_approval"] is True
        assert d["allowed_decisions"] == ["approve", "reject"]
        assert d["is_idempotent"] is False
        assert d["retry"] is None, "非幂等 → 不配重试（写操作重试有幂等风险）"

    def test_idempotent_hint_maps(self) -> None:
        """idempotentHint 单独出现 → 幂等（挂重试），但仍不需审批。"""
        d = mcp_meta.derive_defaults({"idempotentHint": True})
        assert d["is_idempotent"] is True
        assert d["retry"] is not None
        assert d["requires_approval"] is False

    def test_no_annotation_uses_permissive_default(self) -> None:
        """无注解 → **宽松默认**（免审批 + 高危标记 + note 提示复核）。

        这是刻意的产品取舍：多数 server 不带注解，一律要审批等于第三方工具不可用。
        风险由"可见性"兜底（high 标记 + note + 告警日志）。
        """
        for metadata in (None, {}, {"title": "某工具"}):
            d = mcp_meta.derive_defaults(metadata)
            assert d["requires_approval"] is False, "免审批（保证下载即用）"
            assert d["risk_level"] == "high", "但标高危（可见性兜底）"
            assert d["note"] == mcp_meta.UNANNOTATED_NOTE

    def test_readonly_false_is_not_treated_as_readonly(self) -> None:
        """`readOnlyHint=false` 不等于只读——按无注解处理（不能反推成只读）。"""
        d = mcp_meta.derive_defaults({"readOnlyHint": False})
        assert d["note"] == mcp_meta.UNANNOTATED_NOTE

    def test_strip_prefix(self) -> None:
        """挂载名 → 远端原名（元数据存原名，定案 X2）。"""
        assert mcp_meta._strip_prefix("exa", "exa_web_search") == "web_search"
        assert mcp_meta._strip_prefix("exa", "other_tool") == "other_tool"


def _mcp_tool(name: str, metadata: dict | None = None):
    """造一个带注解 metadata 的假 MCP 工具。

    ⚠️ `@tool` 装饰器**不接受** `metadata=`（它是 `BaseTool` 的字段，不是装饰器
    参数）——适配器是在 `StructuredTool(...)` 构造时塞进去的（tools.py:534），
    测试照同款路径构造，别用装饰器。
    """
    from langchain_core.tools import StructuredTool

    return StructuredTool(
        name=name,
        description="d",
        args_schema={"type": "object", "properties": {}},
        func=lambda **_: "ok",
        metadata=metadata,
    )


class TestThreeStateEnvelope:
    """三态信封（批次 3）：MCP 工具的输出接入项目的 artifact 通道。

    此前 `_SafeTool` 返回**裸字符串** → `artifact=None` → 审计只见 `status="unknown"`、
    SSE 只见 `result_status=None`——MCP 工具在可观测链路上是"盲区"（G2 缺口 ②）。
    """

    @staticmethod
    async def _call(tool, name: str):
        """走**真实链路**入口调用工具 → ToolMessage（带 artifact）。

        ⚠️ 必须传 ToolCall dict：传裸参数 dict 时 langchain 只回 content、
        丢掉 artifact（实测：`ainvoke({})` → `'ok'`）。真实 agent 由 ToolNode
        传 ToolCall，故测试照同款入口，否则测的不是生产路径。
        """
        return await tool.ainvoke(
            {"name": name, "args": {}, "id": "c1", "type": "tool_call"}
        )


    async def test_success_returns_content_and_artifact(self) -> None:
        """成功 → `(文本, 信封)`：信封带 status=ok（审计/SSE 读得到）。"""
        from src.tools.channels.mcp_client import wrap_safe

        msg = await self._call(wrap_safe(_mcp_tool("exa_search")), "exa_search")

        assert msg.artifact["status"] == "ok"
        assert msg.content == "ok", "content 通道给模型的是纯文本"

    async def test_tool_declares_content_and_artifact(self) -> None:
        """不变量：包装后必须声明 content_and_artifact（否则二元组被 repr 成文本）。"""
        from src.tools.channels.mcp_client import wrap_safe

        assert (
            wrap_safe(_mcp_tool("exa_search")).response_format
            == "content_and_artifact"
        )

    async def test_failure_returns_error_envelope_with_code(self) -> None:
        """失败 → **错误信封**（不是裸字符串）：带归一错误码 + retryable。

        失败用 httpx.ConnectError（可重试网络异常）→ error_code=upstream_error、
        retryable=True —— 这两个字段正是审计/SSE 需要的。
        """
        import httpx

        from src.tools.channels.mcp_client import wrap_safe

        async def _boom(**_: object) -> str:
            raise httpx.ConnectError("connection refused")

        from langchain_core.tools import StructuredTool

        broken = StructuredTool(
            name="exa_do", description="d",
            args_schema={"type": "object", "properties": {}}, coroutine=_boom,
        )
        msg = await self._call(wrap_safe(broken), "exa_do")

        assert msg.artifact["status"] == "error"
        assert msg.artifact["error_code"] == "upstream_error"
        assert msg.artifact["retryable"] is True, "连接失败属可重试性质"

    async def test_error_text_still_reaches_the_model(self) -> None:
        """错误文本**照样进 content**（模型能自我纠正，不因改了信封而变哑）。"""
        import httpx

        from langchain_core.tools import StructuredTool

        from src.tools.channels.mcp_client import wrap_safe

        async def _boom(**_: object) -> str:
            raise httpx.ConnectError("connection refused")

        broken = StructuredTool(
            name="exa_do", description="d",
            args_schema={"type": "object", "properties": {}}, coroutine=_boom,
        )
        msg = await self._call(wrap_safe(broken), "exa_do")

        assert "失败原因" in msg.content, "走 render(error) 口径"
        assert "connection refused" in msg.content, "原始错误信息保留给模型"

    async def test_no_degraded_state_for_mcp(self) -> None:
        """MCP 不产生 degraded——它没有"拿到一半/被截断"的语义。

        锁这条是防止有人照搬本地工具的三态、给 MCP 造一个假的 degraded。
        """
        from src.tools.channels.mcp_client import wrap_safe

        msg = await self._call(wrap_safe(_mcp_tool("exa_search")), "exa_search")

        assert msg.artifact["status"] == "ok"


class TestOutputToText:
    """MCP content blocks → 给 LLM 的文本（适配器返回的 content 可能是块列表）。"""

    def test_plain_string(self) -> None:
        from src.tools.channels.mcp_client import mcp_output_to_text

        assert mcp_output_to_text(("纯文本", None)) == "纯文本"

    def test_text_blocks_joined(self) -> None:
        from src.tools.channels.mcp_client import mcp_output_to_text

        raw = ([{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}], None)
        assert mcp_output_to_text(raw) == "第一段\n第二段"

    def test_non_text_block_not_silently_dropped(self) -> None:
        """图片/文件块 → 给可读占位，**不静默丢内容**（丢了模型不知道有东西）。"""
        from src.tools.channels.mcp_client import mcp_output_to_text

        raw = ([{"type": "text", "text": "见图"}, {"type": "image"}], None)
        out = mcp_output_to_text(raw)

        assert "见图" in out
        assert "[image]" in out

    def test_artifact_extracts_structured_content(self) -> None:
        from src.tools.channels.mcp_client import _mcp_artifact_of

        assert _mcp_artifact_of(("t", {"structured_content": {"k": 1}})) == {"k": 1}
        assert _mcp_artifact_of(("t", None)) is None
        assert _mcp_artifact_of("裸值") is None


class TestRepository:
    """仓储：真实 PG 读写（按需请求 `pg_schema`，非 autouse）。"""

    async def test_register_tools_creates_rows(self, pg_schema) -> None:
        """自动登记：按注解推导写入，幂等工具带上重试参数。"""
        from src.db import connection as db_conn
        from src.tools.channels.mcp_client import wrap_safe

        readonly = wrap_safe(_mcp_tool("exa_search", {"readOnlyHint": True}))

        async with db_conn.connection() as conn:
            result = await mcp_meta.register_tools(conn, "exa", [readonly])
            rows = await mcp_meta_repo.list_meta_rows(conn)

        assert result == {"added": 1, "skipped": 0, "unannotated": []}
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "search", "存远端原名（不含前缀）"
        assert rows[0]["risk_level"] == "low"
        assert rows[0]["retry"], "只读幂等 → 写出重试参数"

    async def test_register_tools_reports_unannotated(self, pg_schema) -> None:
        """无注解工具 → 进 `unannotated` 清单（供告警/复核），但仍登记（下载即用）。"""
        from src.db import connection as db_conn
        from src.tools.channels.mcp_client import wrap_safe

        bare = wrap_safe(_mcp_tool("exa_do"))

        async with db_conn.connection() as conn:
            result = await mcp_meta.register_tools(conn, "exa", [bare])

        assert result == {"added": 1, "skipped": 0, "unannotated": ["exa_do"]}

    async def test_register_tools_skips_already_registered(self, pg_schema) -> None:
        """已登记的不覆盖——**人工调过的声明优先于自动推导**（重装/升级不踩掉）。"""
        from src.db import connection as db_conn
        from src.tools.channels.mcp_client import wrap_safe

        async with db_conn.connection() as conn:
            # 人工登记：要求审批
            await mcp_meta_repo.upsert_meta(
                conn, "exa", "do",
                risk_level="high", requires_approval=True,
                allowed_decisions=["approve", "reject"],
            )
            bare = wrap_safe(_mcp_tool("exa_do"))
            result = await mcp_meta.register_tools(conn, "exa", [bare])
            rows = await mcp_meta_repo.list_meta_rows(conn)

        assert result == {"added": 0, "skipped": 1, "unannotated": []}
        assert bool(rows[0]["requires_approval"]) is True, "人工声明未被覆盖"

    async def test_full_install_flow_goes_live(self, pg_schema, mocker) -> None:
        """**端到端**：登记 → 刷新缓存 → 工具真的能挂载（"下载即用"闭环）。

        缺任一环都不行：登记了不刷缓存 = 缓存里没有 = 仍被判"未登记"。
        """
        from src.db import connection as db_conn
        from src.tools.channels.mcp_client import wrap_safe

        t = wrap_safe(_mcp_tool("exa_search", {"readOnlyHint": True}))
        async with db_conn.connection() as conn:
            await mcp_meta.register_tools(conn, "exa", [t])
            await mcp_meta.load_policies(conn)  # ← 安装流程里由 mcp_service 做

        assert mcp_meta.policy_for("exa_search") is not None
        assert mcp_meta.pending_tool_names([t]) == [], "登记后不再进待登记清单"
        assert [x.name for x in mcp_meta.governed_tools([t])] == ["exa_search"]

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
