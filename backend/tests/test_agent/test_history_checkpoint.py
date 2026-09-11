"""C01 项目实际链路核验（2026-09-11）：历史重建 + Checkpointer 是否导致消息重复。

背景：`docs/决策/2026-09-11-评估-会话与消息上下文核验-v1.md` §2——
框架级最小复现显示"每轮重传全量无 id 历史"会重复累积；本测试走**项目真实路径**核验：

    _prepare_new_messages（真实 DB 历史装配，重建消息无 id）
    → build_agent(thread_id=session_id)（真实图 + 真实 AsyncSqliteSaver）
    → stream_agent_events（v3 事件流，config 带 thread_id）
    → 读 checkpoint 中 messages 数量

若项目路径不存在重复，3 轮后 checkpoint 中 messages 应为 6 条（3×(user+assistant)）。
"""

from __future__ import annotations

import pytest

from src.agent.main_agent import ChatContext, build_agent, stream_agent_events
from src.api.chat import ChatStreamRequest, _prepare_new_messages
from src.core import db as core_db
from src.db import session_repo as repo
from src.schemas.message import Message


async def _append(conn, session_id: str, role: str, content: str) -> None:
    """落库一条消息（真实链路 assistant 在流结束后落库，此处手动补）。"""
    await repo.append_message(
        conn, Message(session_id=session_id, role=role, content=content)
    )


async def _run_turn(session_id: str, user_text: str, assistant_text: str) -> list:
    """走一轮项目真实路径，返回 checkpoint 中的 messages 列表。"""
    conn = await core_db.get_connection()
    try:
        req = ChatStreamRequest(session_id=session_id, message=user_text)
        lc_messages = await _prepare_new_messages(conn, repo, req, session_id)
        await _append(conn, session_id, "assistant", assistant_text)
    finally:
        await conn.close()

    agent = build_agent(thread_id=session_id)
    ctx = ChatContext(session_id=session_id)
    async for _evt in stream_agent_events(agent, lc_messages, context=ctx):
        pass

    # AsyncSqliteSaver 必须走异步接口（同步 get_state 会抛 InvalidStateError）
    snap = await agent.aget_state({"configurable": {"thread_id": session_id}})
    return list(snap.values.get("messages", []))


@pytest.mark.xfail(
    reason="C01 已知缺陷：重复累积（_history_to_langchain 无稳定 id + 每轮重传全量历史）；"
    "待拍板修复方案后转正为回归测试",
    strict=False,
)
async def test_project_pipeline_no_message_duplication(tmp_db_path, mock_chat_llm) -> None:
    """核验：项目真实路径 3 轮对话后，checkpoint 中消息不应重复累积。

    2026-09-11 实测：**当前失败**——3 轮后 messages 达 12 条且 `q1/q2/q3` 重复，
    证实 `docs/决策/2026-09-11-评估-会话与消息上下文核验-v1.md` §2 的 C01 风险
    在项目路径成立（非仅框架层）。修复后此测试应转绿。
    """
    session_id = "sess-c01-verify"

    # 建会话（标题非"新会话"→ 不触发后台标题 LLM 任务，保持测试确定性）
    conn = await core_db.get_connection()
    try:
        await repo.create_session(conn, session_id, title="C01 核验会话")
    finally:
        await conn.close()

    observed: list[list[str]] = []
    for i in (1, 2, 3):
        msgs = await _run_turn(session_id, f"q{i}", f"a{i}")
        observed.append([m.content for m in msgs])
        print(f"[C01 核验] turn{i} count={len(msgs)} contents={observed[-1]}")

    # 正确行为：3 轮后恰好 6 条（q1,a1,q2,a2,q3,a3），无重复
    assert observed[-1] == ["q1", "a1", "q2", "a2", "q3", "a3"], (
        f"项目路径出现消息重复累积：{observed[-1]}"
    )
