"""C01 项目实际链路核验 + 回归（2026-09-11）。

背景：`docs/决策/2026-09-11-评估-会话与消息上下文核验-v1.md` §2——项目真实路径
（`_prepare_new_messages` + `build_agent` + Checkpointer + `stream_agent_events`）
曾出现消息重复累积（3 轮 12 条、`q1/q2/q3` 重复）。

2026-10-15 PG 迁移：Checkpointer 由 AsyncSqliteSaver 换为 AsyncPostgresSaver，
本回归链路不变（隔离靠 conftest 的 per-test schema）。

C01 修复（co-creator 拍板：**Checkpointer 管 Agent 路径执行历史**）后：
- 新消息模式只传**增量**（历史由图状态累积）
- 记忆/模式注入用**固定 id** → reducer 覆盖而非堆叠

预期：3 轮后 state 为 6 条、无重复；记忆注入仅 1 份。
"""

from __future__ import annotations

import pytest

from src.agent.main_agent import ChatContext, build_agent, stream_agent_events
from src.api.chat import ChatStreamRequest, _prepare_new_messages
from src.db import connection as db_conn
from src.db import session_repo as repo
from src.schemas.message import Message


async def _append(conn, session_id: str, role: str, content: str) -> None:
    """落库一条消息（真实链路 assistant 在流结束后落库，此处手动补）。"""
    await repo.append_message(
        conn, Message(session_id=session_id, role=role, content=content)
    )


async def _run_turn(session_id: str, user_text: str, assistant_text: str) -> list:
    """走一轮项目真实路径，返回 checkpoint 中的 messages 列表。"""
    async with db_conn.connection() as conn:
        req = ChatStreamRequest(session_id=session_id, message=user_text)
        lc_messages = await _prepare_new_messages(conn, repo, req, session_id)
        await _append(conn, session_id, "assistant", assistant_text)

    agent = build_agent(thread_id=session_id)
    ctx = ChatContext(session_id=session_id)
    async for _evt in stream_agent_events(agent, lc_messages, context=ctx):
        pass

    # Async* Saver 必须走异步接口（同步 get_state 会抛 InvalidStateError）
    snap = await agent.aget_state({"configurable": {"thread_id": session_id}})
    return list(snap.values.get("messages", []))


async def _new_session(session_id: str) -> None:
    """建会话（标题非"新会话"→ 不触发后台标题 LLM 任务，保持测试确定性）。"""
    async with db_conn.connection() as conn:
        await repo.create_session(conn, session_id, title="C01 回归会话")


async def test_project_pipeline_no_message_duplication(mock_chat_llm) -> None:
    """C01 回归：项目真实路径 3 轮后应为 6 条，且 `q1/q2/q3` 各只出现一次。"""
    session_id = "sess-c01-verify"
    await _new_session(session_id)

    msgs: list = []
    for i in (1, 2, 3):
        msgs = await _run_turn(session_id, f"q{i}", f"a{i}")
        print(f"[C01] turn{i} count={len(msgs)} contents={[m.content for m in msgs]}")

    contents = [m.content for m in msgs]
    assert len(contents) == 6, f"应 6 条（3 轮 × user+assistant），实际 {len(contents)}：{contents}"
    for q in ("q1", "q2", "q3"):
        assert contents.count(q) == 1, f"{q} 应只出现一次（无重复累积）：{contents}"


async def test_memory_injection_not_accumulated(mock_chat_llm) -> None:
    """C01 回归：记忆注入用固定 id → 多轮后 state 中只保留 1 份。"""
    from src.agent.main_agent import get_store
    from src.agent.memory.store import save_typed_memory

    await save_typed_memory(get_store(), "user_profile", "用户偏好简洁回答")

    session_id = "sess-c01-memory"
    await _new_session(session_id)

    msgs: list = []
    for i in (1, 2, 3):
        msgs = await _run_turn(session_id, f"q{i}", f"a{i}")

    memory_msgs = [m for m in msgs if "长期记忆" in str(m.content)]
    assert len(memory_msgs) == 1, f"记忆注入应只 1 份（固定 id 覆盖），实际 {len(memory_msgs)}"


async def test_degraded_without_checkpointer_uses_db_history(mock_chat_llm) -> None:
    """降级路径：未挂 Checkpointer → 仍由 DB 重建全量历史（不丢上下文）。

    C01 修复按 `has_checkpointer()` 分流：无 Checkpointer（测试/脚本未跑 lifespan）
    时图无状态，必须由 DB 提供历史，否则模型看不到上下文。
    """
    from src.agent import main_agent

    session_id = "sess-c01-degraded"
    await _new_session(session_id)

    # 预置一轮历史（旧问题/旧回答）
    async with db_conn.connection() as conn:
        await _append(conn, session_id, "user", "旧问题")
        await _append(conn, session_id, "assistant", "旧回答")

    # 临时关闭 checkpointer（模拟未跑 lifespan 的降级环境）
    saved = main_agent._checkpointer
    main_agent._checkpointer = None
    try:
        async with db_conn.connection() as conn:
            req = ChatStreamRequest(session_id=session_id, message="新问题")
            lc_messages = await _prepare_new_messages(conn, repo, req, session_id)
    finally:
        main_agent._checkpointer = saved

    contents = [m.content for m in lc_messages]
    assert "旧问题" in contents and "旧回答" in contents, f"降级模式应含 DB 全量历史：{contents}"
    assert "新问题" in contents, "应含本条新消息"


# ── 按需声明：本模块走真实链路（DB + Checkpointer/Store）──
@pytest.fixture(autouse=True)
def _needs_agent(reset_agent_singleton) -> None:
    """本模块每个用例都要独立 schema + 重建 checkpointer / store。"""
    return None

