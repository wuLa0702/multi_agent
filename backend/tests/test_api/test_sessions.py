"""会话与消息 REST 端点测试（契约 §4.2-4.6）：sessions CRUD + 消息 cursor 分页。

覆盖（20-testing.md：正常 / 边界 / 错误）：
- 正常：创建 / 列表 / PATCH 标题 / DELETE / 消息分页
- 边界：PATCH 空标题 400、limit 超上限 422、cursor 翻页 has_more 语义
- 错误：不存在会话 → 404 SESSION_NOT_FOUND（DELETE / PATCH / messages 三处）
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core import db as core_db
from src.db import session_repo as repo
from src.schemas.message import Message


@pytest.fixture
async def session_id(tmp_db_path, app_env_dev) -> str:
    """建一个会话，返回 id（隔离库）。"""
    conn = await core_db.get_connection()
    try:
        s = await repo.create_session(conn, "test-session-1", title="初始标题")
        return s.id
    finally:
        await conn.close()


@pytest.fixture
async def messages_fixture(session_id) -> None:
    """会话内塞 3 条消息（id 递增），供分页测试。"""
    conn = await core_db.get_connection()
    try:
        for i in range(3):
            await repo.append_message(
                conn,
                Message(
                    session_id=session_id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"消息{i + 1}",
                ),
            )
    finally:
        await conn.close()


# ── 正常路径 ──

@pytest.mark.asyncio
async def test_create_session_returns_session(app_env_dev, tmp_db_path) -> None:
    """正常：POST /v1/sessions 返回 Session（id 非空 + 默认标题）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]
    assert body["title"] == "新会话"
    assert body["created_at"] and body["updated_at"]


@pytest.mark.asyncio
async def test_list_sessions_returns_items_and_total(app_env_dev, tmp_db_path) -> None:
    """正常：会话列表返回 items + total（updated_at 倒序，新会话在前）。"""
    conn = await core_db.get_connection()
    try:
        await repo.create_session(conn, "s-old", title="旧")
        await repo.create_session(conn, "s-new", title="新")
    finally:
        await conn.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["total"] >= 2
    assert body["items"][0]["id"] in ("s-new", "s-old")


@pytest.mark.asyncio
async def test_update_title_returns_updated_session(app_env_dev, tmp_db_path, session_id) -> None:
    """正常：PATCH 标题返回更新后 Session，updated_at 刷新。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/v1/sessions/{session_id}", json={"title": "新标题"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == session_id
    assert body["title"] == "新标题"


@pytest.mark.asyncio
async def test_delete_session_returns_ok(app_env_dev, tmp_db_path, session_id) -> None:
    """正常：DELETE 返回 status=ok。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/v1/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_delete_evicts_cache_and_cleans_workspace(
    app_env_dev, tmp_db_path, session_id, monkeypatch
) -> None:
    """P0 联动：DELETE 后——Agent 缓存失效 + 工作区文件全量清理（深化方案 §2.4）。"""
    from src.agent import main_agent
    from src.core import backend as core_backend

    main_agent._agents[session_id] = object()  # 哨兵：模拟该会话已有编译图
    ws = tmp_db_path.parent / "ws" / session_id
    ws.mkdir(parents=True)
    (ws / "draft.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(core_backend, "get_workspace_dir", lambda: tmp_db_path.parent / "ws")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/v1/sessions/{session_id}")

    assert resp.status_code == 200
    assert session_id not in main_agent._agents, "缓存图应失效"
    assert not (ws / "draft.py").exists(), "工作区文件应全量清理"
    assert ws.exists(), "工作区目录保留（防误删路径本身）"


@pytest.mark.asyncio
async def test_delete_calls_rebuild_and_cleanup(
    app_env_dev, tmp_db_path, session_id, mocker, monkeypatch
) -> None:
    """P0 联动：rebuild_agent / cleanup_workspace / sandbox 销毁均以 session_id 调用（404 不触发）。

    2026-08-12 结构重构：联动逻辑移入 agent/services/session_service，patch 目标随之更新。
    """
    from src.agent.services import session_service

    mock_rebuild = mocker.patch("src.agent.services.session_service.main_agent.rebuild_agent")
    mock_cleanup = mocker.patch("src.agent.services.session_service.cleanup_workspace")
    mock_sandbox = mocker.patch("src.agent.services.session_service.sandbox_pool.destroy")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/v1/sessions/{session_id}")
    assert resp.status_code == 200
    mock_rebuild.assert_called_once_with(session_id)
    mock_cleanup.assert_called_once_with(session_id, older_than_days=0)
    mock_sandbox.assert_called_once_with(session_id)

    # 404 路径：不触发联动（会话不存在）
    mock_rebuild.reset_mock()
    mock_cleanup.reset_mock()
    mock_sandbox.reset_mock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp404 = await client.delete(f"/v1/sessions/not-exist")
    assert resp404.status_code == 404
    mock_rebuild.assert_not_called()
    mock_cleanup.assert_not_called()
    mock_sandbox.assert_not_called()


@pytest.mark.asyncio
async def test_list_messages_paginates_with_cursor(
    app_env_dev, tmp_db_path, messages_fixture, session_id
) -> None:
    """正常：第一页返回最新消息（升序）；has_more=true 时 next_before_id 可翻更早页。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page1 = await client.get(f"/v1/sessions/{session_id}/messages?limit=2")
    assert page1.status_code == 200
    p1 = page1.json()
    assert p1["has_more"] is True
    assert len(p1["items"]) == 2
    # 最新 2 条（id=2,3），升序返回
    assert [m["content"] for m in p1["items"]] == ["消息2", "消息3"]
    next_id = p1["next_before_id"]
    assert next_id == 2  # 本页最旧一条 id，下一页取 id < 2

    # 翻更早页：拿到剩余 1 条，has_more=false
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page2 = await client.get(
            f"/v1/sessions/{session_id}/messages?limit=2&before_id={next_id}"
        )
    p2 = page2.json()
    assert p2["has_more"] is False
    assert p2["next_before_id"] is None
    assert [m["content"] for m in p2["items"]] == ["消息1"]


# ── 错误路径 ──

@pytest.mark.asyncio
async def test_delete_missing_session_404(app_env_dev, tmp_db_path) -> None:
    """错误：DELETE 不存在会话 → 404 SESSION_NOT_FOUND。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/v1/sessions/no-such-id")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_patch_missing_session_404(app_env_dev, tmp_db_path) -> None:
    """错误：PATCH 不存在会话 → 404 SESSION_NOT_FOUND。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/v1/sessions/no-such-id", json={"title": "x"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_messages_missing_session_404(app_env_dev, tmp_db_path) -> None:
    """错误：消息分页查不存在会话 → 404 SESSION_NOT_FOUND。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/sessions/no-such-id/messages")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SESSION_NOT_FOUND"


# ── 边界 ──

@pytest.mark.asyncio
async def test_patch_empty_title_400(app_env_dev, tmp_db_path, session_id) -> None:
    """边界：空标题 → 400（Pydantic min_length=1 校验）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/v1/sessions/{session_id}", json={"title": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_messages_limit_over_cap_422(app_env_dev, tmp_db_path, session_id) -> None:
    """边界：limit 超过 200 上限 → 422（Query le 校验）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/v1/sessions/{session_id}/messages?limit=201")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_destroys_sandbox_pool(
    app_env_dev, tmp_db_path, session_id, mocker
) -> None:
    """P1 联动：DELETE 会话 → sandbox_pool.destroy(session_id)（沙箱资源释放）。"""
    from src.sandbox.pool import sandbox_pool

    mock_destroy = mocker.patch.object(sandbox_pool, "destroy")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/v1/sessions/{session_id}")

    assert resp.status_code == 200
    mock_destroy.assert_called_once_with(session_id)
