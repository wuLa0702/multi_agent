"""MCP 连接管理 API 测试（2026-10-16 补——B5 SQL 下沉时发现该接口**零覆盖**）。

补测背景：同批把 `GET /v1/mcp-servers` 的裸 SQL 下沉到 `skill_repository`，
改完全量 685 passed —— 但**这个接口本来就没有测试**，绿不能证明改动正确
（即"测试假绿"模式，见 `docs/临时/2026-10-16-汇总问题-v1.md` F3）。

覆盖：
1. 正常路径：列表返回**对外视图 7 列**，按 `id` 升序
2. 安全：`headers`（含 `Authorization` 明文）**绝不出现在响应中**
3. 边界：无连接配置 → 空列表（不是 404、不报错）
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.db import connection as db_conn
from src.db import skill_repository

#: 对外视图列（`api/mcp_servers.py::McpServerOut`）——多一列少一列都算契约跑偏
VIEW_COLUMNS = {"id", "name", "transport", "url", "is_active", "source", "version"}

#: 探针密钥：断言它**不出现在响应里**（鉴权明文外泄是最严重的一类回归）
SECRET_TOKEN = "Bearer SECRET-TOKEN-DO-NOT-LEAK"


async def _seed_server(name: str) -> int:
    """插一行 MCP 连接配置（带鉴权 headers），返回 id。"""
    async with db_conn.connection() as conn:
        return await skill_repository.insert_mcp_server(
            conn,
            name=name,
            transport="http",
            url=f"http://example.com/{name}/mcp",
            command="",
            args="",
            source="manual",
            source_url="",
            version="1.0.0",
            headers=f'{{"Authorization": "{SECRET_TOKEN}"}}',
        )


@pytest.mark.asyncio
async def test_list_returns_view_columns(app_env_dev) -> None:
    """正常路径：返回对外视图 7 列，按 id 升序。"""
    await _seed_server("demo-a")
    await _seed_server("demo-b")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/mcp-servers")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [i["name"] for i in body["items"]] == ["demo-a", "demo-b"], "应按 id 升序"
    for item in body["items"]:
        assert set(item) == VIEW_COLUMNS, f"对外列应为 {sorted(VIEW_COLUMNS)}"


@pytest.mark.asyncio
async def test_list_never_leaks_headers(app_env_dev) -> None:
    """安全：鉴权 headers（含 token）绝不出现在响应体里（端到端）。"""
    await _seed_server("auth-server")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/mcp-servers")

    assert resp.status_code == 200
    assert SECRET_TOKEN not in resp.text, "鉴权 token 外泄"


@pytest.mark.asyncio
async def test_repository_returns_only_view_columns(app_env_dev) -> None:
    """安全（**仓储层**——守卫的真正落点）：`list_mcp_servers` 不返回 `headers`。

    ⚠️ 为何单列此用例：上一用例（API 层）**抓不到**仓储写成 `SELECT *` 的回归——
    `_row_to_out` 按字段白名单构造 `McpServerOut`，多查的列到不了响应体。
    真正会泄漏的是"仓储把 `headers` 交出去"，故守卫必须落在这一层。
    """
    await _seed_server("repo-scope")

    async with db_conn.connection() as conn:
        rows = await skill_repository.list_mcp_servers(conn)

    assert rows, "应有 1 行"
    assert set(rows[0]) == VIEW_COLUMNS, f"仓储应为 {sorted(VIEW_COLUMNS)}，实际 {sorted(rows[0])}"
    assert "headers" not in rows[0]


@pytest.mark.asyncio
async def test_list_empty_is_ok(app_env_dev) -> None:
    """边界：无连接配置 → 空列表（不是 404、不报错）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/mcp-servers")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "items": [], "total": 0}


# ── 按需声明：本模块测试需要数据库（2026-10-15 起 pg_schema 不再 autouse）──
@pytest.fixture(autouse=True)
def _needs_db(pg_schema) -> None:
    """本模块需要独立 PG schema。"""
