"""chat SSE 流式接口测试（契约：方案-后端接口定义-v1 §5）。

覆盖（20-testing.md：正常 / 边界 / 错误 / LLM 异常）：
- 事件顺序保证：start 首、done 尾（§5.5）
- token 增量流 + 全文落库（user + assistant）
- 参数互斥：message/resume_run_id 冲突、全空 → 400
- resume_run_id（未实现）→ 400 显式拦截
- 会话不存在 → 404
- session_id=None 自动建会话
- LLM 异常 → error 事件（流内，不崩 HTTP）
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import settings


def parse_sse(text: str) -> list[dict]:
    """解析 SSE 文本 → 事件 dict 列表（data: 行提取）。"""
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


async def _post_stream(client: AsyncClient, payload: dict) -> tuple[int, str]:
    """POST /v1/chat/stream 并返回 (status_code, body)。"""
    resp = await client.post("/v1/chat/stream", json=payload)
    return resp.status_code, resp.text


@pytest.mark.asyncio
async def test_chat_stream_normal_flow(mock_chat_llm, tmp_db_path) -> None:
    """正常流：start 首 → token×N → done 尾；事件顺序与字段齐全。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {"message": "你好"})

    assert status == 200
    assert "text/event-stream" in body or body.startswith("data:")  # httpx 可能重写 Content-Type
    events = parse_sse(body)
    assert events, "应至少有一个 SSE 事件"

    # 首事件必为 start（§5.5）
    assert events[0]["type"] == "start"
    assert events[0]["run_id"]
    assert events[0]["session_id"]
    assert events[0]["resumed"] is False

    # 中间 token 事件（增量文本非空）
    token_events = [e for e in events if e["type"] == "token"]
    assert token_events, "应产出 token 事件"
    assert all(e["text"] for e in token_events)
    # 全文 = token 拼接（按字符流式：mock 回复 = 各字符 token）
    assert "".join(e["text"] for e in token_events) == "你好，这是 mock 回复"

    # 尾事件必为 done（§5.5）
    assert events[-1]["type"] == "done"
    assert events[-1]["session_id"] == events[0]["session_id"]
    assert events[-1]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_chat_stream_persists_messages(mock_chat_llm, tmp_db_path) -> None:
    """落库：user 消息 + assistant 全文各一条，会话更新。"""
    from src.core import db as core_db
    from src.db import repository as repo

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, body = await _post_stream(client, {"message": "你好"})
    events = parse_sse(body)
    session_id = events[0]["session_id"]

    conn = await core_db.get_connection()
    try:
        messages = await repo.list_messages(conn, session_id)
    finally:
        await conn.close()

    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "你好"
    assert messages[1].content == "你好，这是 mock 回复"


@pytest.mark.asyncio
async def test_chat_stream_auto_create_session(mock_chat_llm, tmp_db_path) -> None:
    """session_id=None → 自动建会话（start 事件带新 id）。"""
    from src.core import db as core_db
    from src.db import repository as repo

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, body = await _post_stream(client, {"message": "第一条"})
    events = parse_sse(body)
    session_id = events[0]["session_id"]
    assert session_id

    conn = await core_db.get_connection()
    try:
        session = await repo.get_session(conn, session_id)
    finally:
        await conn.close()
    assert session is not None
    assert session.title == "新会话"


@pytest.mark.asyncio
async def test_chat_stream_mutually_exclusive_400(mock_chat_llm, tmp_db_path) -> None:
    """边界：message 与 resume_run_id 同时给 → 400 BAD_REQUEST。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(
            client, {"message": "hi", "resume_run_id": "run-1"}
        )

    assert status == 400
    assert body


@pytest.mark.asyncio
async def test_chat_stream_empty_payload_400(mock_chat_llm, tmp_db_path) -> None:
    """边界：全空载荷 → 400 BAD_REQUEST。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {})

    assert status == 400
    assert body


@pytest.mark.asyncio
async def test_chat_stream_resume_not_implemented_400(mock_chat_llm, tmp_db_path) -> None:
    """resume_run_id 单独给 → 400（断点恢复当前阶段未实现，显式拦截）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {"resume_run_id": "run-1"})

    assert status == 400
    assert body


@pytest.mark.asyncio
async def test_chat_stream_session_not_found_404(mock_chat_llm, tmp_db_path) -> None:
    """错误路径：不存在的 session_id → 404 SESSION_NOT_FOUND。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {"session_id": "no-such", "message": "hi"})

    assert status == 404
    assert "SESSION_NOT_FOUND" in body or "会话不存在" in body


@pytest.mark.asyncio
async def test_chat_stream_llm_error_event(mocker, tmp_db_path) -> None:
    """LLM 异常：不发 done，发 error 事件收尾（流内错误不崩 HTTP 层）。"""
    def _boom() -> None:
        raise TimeoutError("llm timeout")

    mocker.patch("src.api.chat.get_chat_model", side_effect=_boom)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {"message": "hi"})

    assert status == 200  # SSE 已建立，错误走事件通道
    events = parse_sse(body)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] in ("LLM_UNAVAILABLE", "INTERNAL")
    assert "retryable" in events[-1]
    # done 不得出现（§5.5：done/error 二选一）
    assert not any(e["type"] == "done" for e in events)
