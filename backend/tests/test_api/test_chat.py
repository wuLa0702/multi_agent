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


@pytest.fixture(autouse=True)
def no_background_llm(mocker):
    """后台任务（自动标题/记忆抽取）不真调 LLM：返回 None → 走规则回退。

    chat.py 的 _generate_title_in_background / _save_memory_in_background
    在 adapter=None 时会构造默认 LLMAdapter() 真调 API（20-testing.md：
    LLM 全部 mock）。两个后台函数均在调用时才 import 模块属性，
    patch 模块属性即可拦截；返回 None → 标题走规则截断回退、
    记忆跳过写入，断言确定性通过。
    模块级（仅本文件）：test_memory_store.py 直接调 extract_memory_fact
    （adapter 显式注入），conftest 全局 autouse 会破坏它。
    """
    mocker.patch("src.agent.tasks.assistant.generate_title", return_value=None)
    mocker.patch("src.agent.memory.store.extract_memory_fact", return_value=None)


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
    from src.db import session_repo as repo

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
    from src.db import session_repo as repo

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
    # 2026-08-04 P0 自动标题：首条消息后标题 = 消息前 20 字（不再是「新会话」）
    assert session.title == "第一条"


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
async def test_chat_stream_with_model_id(
    mocker, fake_deep_agent_model, seeded_registry
) -> None:
    """运行时切换：model_id 透传 context，模型调用仍走 mock（不实际调 API）。"""
    # seed 后找豆包（ark）的模型 ID
    ark_models = [
        m
        for p in seeded_registry.list_providers()
        if p.slug == "ark"
        for m in p.models
    ]
    assert ark_models, "seed 应包含豆包模型"
    target_id = ark_models[0].id

    calls: list[int | None] = []

    def _fake_get_chat_model(model_id: int | None = None):
        calls.append(model_id)
        return fake_deep_agent_model

    mocker.patch("src.agent.main_agent.get_chat_model", side_effect=_fake_get_chat_model)
    mocker.patch("src.agent.main_agent.load_subagents", return_value=[])  # P1-1：本测试聚焦 model_id 路由

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {"message": "hi", "model_id": target_id})

    assert status == 200
    # 首次调用 = 单例构建兜底模型（model_id=None）；后续 = middleware 按 context 路由
    assert calls[0] is None
    assert target_id in calls, f"middleware 应按请求上下文路由 model_id，实际调用序列：{calls}"
    events = parse_sse(body)
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_chat_stream_invalid_model_id_400(tmp_db_path) -> None:
    """边界：model_id 不存在 → 400（运行时切换参数校验）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status, body = await _post_stream(client, {"message": "hi", "model_id": 99999})

    assert status == 400
    assert "model_id" in body


@pytest.mark.asyncio
async def test_chat_stream_llm_error_event(mocker, tmp_db_path) -> None:
    """LLM 异常：不发 done，发 error 事件收尾（流内错误不崩 HTTP 层）。"""
    def _boom() -> None:
        raise TimeoutError("llm timeout")

    mocker.patch("src.agent.main_agent.get_chat_model", side_effect=_boom)

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


# ── 事件流增强（引入方案 P0：EVENT_STREAM_V3=true 多事件分发）──

class _FakeStreamAgent:
    """假 agent：astream_events 产出合成事件（token 交错工具调用）。"""

    async def astream_events(self, input, **kwargs):  # noqa: ANN001
        from langchain_core.messages import AIMessageChunk

        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="你好")}}
        yield {"event": "on_tool_start", "name": "run_code_in_sandbox", "data": {"input": '{"code": "x"}'}}
        yield {"event": "on_tool_end", "name": "run_code_in_sandbox", "data": {"output": "ok"}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="，结果如上")}}


@pytest.mark.asyncio
async def test_chat_stream_v3_emits_tool_call_events(
    mock_chat_llm, tmp_db_path, mocker, monkeypatch
) -> None:
    """P0：EVENT_STREAM_V3=true → SSE 输出 tool_call 事件（契约 v3 落地）。

    事件序：start → token → tool_call(running) → tool_call(completed) → token → done
    ——工具调用事件**穿插在 token 流中**（评审问题 1 的集成回归）。
    """
    from src.api import chat as chat_api

    monkeypatch.setattr(settings, "event_stream_v3", True)
    mocker.patch.object(chat_api, "build_agent", return_value=_FakeStreamAgent())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream(
            "POST", "/v1/chat/stream",
            json={"message": "帮我算一下"},
        ) as resp:
            body = (await resp.aread()).decode("utf-8")

    events = parse_sse(body)
    types = [e["type"] for e in events]
    # start 首 / done 尾；tool_call 夹在 token 之间（交错，非串行）
    assert types[0] == "start" and types[-1] == "done"
    assert types == [
        "start", "token", "tool_call", "tool_call", "token", "done",
    ], "工具调用事件必须交错在 token 流中（评审问题 1）"
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_events[0]["status"] == "running"
    assert tool_events[1]["status"] == "completed"
    assert tool_events[0]["tool"] == "run_code_in_sandbox"
    assert tool_events[0]["id"] < tool_events[1]["id"], "事件序号自增（前端排序）"


@pytest.mark.asyncio
async def test_chat_stream_v3_default_off_token_only(
    mock_chat_llm, tmp_db_path, mocker, monkeypatch
) -> None:
    """P0：EVENT_STREAM_V3=false（默认）→ 仅 token 事件，现状零行为变化。"""
    from src.api import chat as chat_api

    monkeypatch.setattr(settings, "event_stream_v3", False)
    mocker.patch.object(chat_api, "build_agent", return_value=_FakeStreamAgent())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream(
            "POST", "/v1/chat/stream",
            json={"message": "hi"},
        ) as resp:
            body = (await resp.aread()).decode("utf-8")

    events = parse_sse(body)
    assert all(e["type"] in ("start", "token", "done") for e in events), "默认开关应只出 token"
