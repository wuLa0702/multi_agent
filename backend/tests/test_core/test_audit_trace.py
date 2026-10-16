"""trace_id 贯穿测试（工作单批次 2：T2.1 / T2.3 / T2.4）。

**本文件的核心用例是 `test_long_lived_worker_recovers_trace`**——
它锁住设计稿 §4.2 修正过的那条：长驻 worker **不会**自动继承请求的 trace_id，
必须随消息显式携带。写错的话，"记忆抽取"这条链的审计全是孤儿，
而它恰恰是"会话触发了什么"最需要能追的部分。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from src.core import audit
from src.core.audit import bind_context, bind_orphan, current_trace_id


@pytest.fixture(autouse=True)
def _fresh_context():
    """每用例重置审计上下文（模块级 ContextVar 跨用例残留）。"""
    audit.bind_context("", session_id="", orphan=False)
    yield
    audit.bind_context("", session_id="", orphan=False)


def _records(audit_records) -> list[dict]:
    return [json.loads(r.getMessage()) for r in audit_records]


# ── T2.1 请求入口中间件 ──


class TestTraceIdMiddleware:
    """`TraceIdMiddleware`：透传 / 生成 / 非 HTTP 不绑。"""

    @staticmethod
    def _scope(headers: list[tuple[bytes, bytes]] | None = None, type_: str = "http"):
        return {"type": type_, "headers": headers or []}

    async def test_generates_when_absent(self) -> None:
        """无 `X-Trace-Id` → 生成 UUID4 并绑定。"""
        from src.api.main import TraceIdMiddleware

        seen: list[str] = []

        async def inner(scope, receive, send):
            seen.append(current_trace_id())

        await TraceIdMiddleware(inner)(self._scope(), None, None)

        assert seen and seen[0], "应已绑定一个非空 trace"
        uuid.UUID(seen[0])  # 合法 UUID（不是随便一个串）

    async def test_reuses_incoming_header(self) -> None:
        """带 `X-Trace-Id` → **复用**（跨系统串联：前端/网关传下来的那条链）。"""
        from src.api.main import TraceIdMiddleware

        seen: list[str] = []

        async def inner(scope, receive, send):
            seen.append(current_trace_id())

        scope = self._scope([(b"x-trace-id", b"upstream-abc")])
        await TraceIdMiddleware(inner)(scope, None, None)

        assert seen == ["upstream-abc"]

    async def test_empty_header_falls_back_to_generate(self) -> None:
        """空值头 → 当作没带（不能把空串当 trace，那等于"未绑定"混进来）。"""
        from src.api.main import TraceIdMiddleware

        seen: list[str] = []

        async def inner(scope, receive, send):
            seen.append(current_trace_id())

        scope = self._scope([(b"x-trace-id", b"   ")])
        await TraceIdMiddleware(inner)(scope, None, None)

        assert seen[0], "应生成新值而非沿用空串"

    async def test_non_http_not_bound(self) -> None:
        """lifespan / websocket 不绑（无"请求"语义）。"""
        from src.api.main import TraceIdMiddleware

        called: list[bool] = []

        async def inner(scope, receive, send):
            called.append(True)

        await TraceIdMiddleware(inner)(self._scope(type_="lifespan"), None, None)

        assert called == [True], "仍有转发（不能吞掉非 HTTP 消息）"
        assert current_trace_id() == "", "但不该绑 trace"


# ── T2.3 长驻消费者显式携带（🔴 本批最关键） ──


class TestLongLivedWorkerTrace:
    """记忆队列：入队盖章 → worker 取出恢复。"""

    @staticmethod
    def _task(session_id: str = "s1"):
        from src.agent.memory.queue import MemoryTask

        return MemoryTask(
            session_id=session_id, user_message="u", assistant_text="a",
            fingerprint=f"fp-{uuid.uuid4().hex[:8]}",
        )

    def test_enqueue_stamps_trace_from_context(self) -> None:
        """入队发生在请求内 → 任务自动盖上该请求的 trace_id（调用方不必填）。"""
        from src.agent.memory.queue import MemoryTaskQueue

        bind_context("trace-req-1", session_id="s1")
        q = MemoryTaskQueue()
        task = self._task()

        assert q.enqueue(task) is True
        assert task.trace_id == "trace-req-1"

    def test_enqueue_keeps_explicit_trace(self) -> None:
        """调用方已显式给了 trace_id → 不覆盖（尊重显式传参）。"""
        from src.agent.memory.queue import MemoryTaskQueue

        bind_context("trace-context", session_id="s1")
        q = MemoryTaskQueue()
        task = self._task()
        task.trace_id = "trace-explicit"

        q.enqueue(task)

        assert task.trace_id == "trace-explicit"

    async def test_long_lived_worker_recovers_trace(self, audit_records) -> None:
        """🔴 **核心用例**：worker 在**不同 context**里消费，仍能打出正确的 trace。

        模拟真实形态：worker 在 wrapper task 里创建（≈ lifespan），
        **在另一个 context** 入队，再让 worker 消费。
        若实现成"靠 contextvar 自动继承"，本用例会看到空 trace（孤儿）——
        记忆抽取链的审计就全断了。
        """
        from src.agent.memory.queue import MemoryTaskQueue

        q = MemoryTaskQueue()
        consumed: list[str] = []

        async def consumer(task):
            consumed.append(current_trace_id())
            return "ok"

        worker = asyncio.create_task(q.run_worker(consumer))
        await asyncio.sleep(0.05)

        # 在【另一个 context】里入队（模拟另一个请求）
        bind_context("trace-of-request-X", session_id="sX")
        q.enqueue(self._task(session_id="sX"))

        await asyncio.sleep(0.1)   # 给 worker 消费时间
        worker.cancel()

        assert consumed == ["trace-of-request-X"], (
            "worker 必须随消息恢复 trace（长驻任务不自动继承）"
        )
        events = _records(audit_records)
        start = [e for e in events if e["event"] == "memory.start"]
        assert start and start[-1]["trace_id"] == "trace-of-request-X"
        assert start[-1]["session_id"] == "sX", "弱关联字段同时带上"
        assert "orphan" not in start[-1]

    async def test_worker_marks_orphan_when_no_upstream(self, audit_records) -> None:
        """请求外入队（无上游 trace）→ 按 B6 生成**孤儿**（禁止留空）。"""
        from src.agent.memory.queue import MemoryTaskQueue

        q = MemoryTaskQueue()

        async def consumer(task):
            return "ok"

        worker = asyncio.create_task(q.run_worker(consumer))
        await asyncio.sleep(0.05)
        # 显式清空上下文 → 模拟"在请求外"入队
        bind_context("", session_id="")
        q.enqueue(self._task(session_id="sNoUpstream"))
        await asyncio.sleep(0.1)
        worker.cancel()

        start = [e for e in _records(audit_records) if e["event"] == "memory.start"][-1]
        assert start["trace_id"], "禁止留空（B6）"
        assert start["orphan"] is True, "应标记为孤儿"
        assert start["session_id"] == "sNoUpstream", "仍带弱关联"


# ── T2.4 孤儿规则 API ──


class TestOrphanRule:
    """`bind_orphan()`：无上游场景的入口。"""

    def test_generates_unique_trace_and_flags_orphan(self, audit_records) -> None:
        """生成新 id + 打 orphan 标；两次调用 id 不同。"""
        first = bind_orphan(session_id="cron-1")
        audit.emit("sandbox", "sandbox.gc")

        record = _records(audit_records)[-1]
        assert first, "必须生成（禁止留空）"
        assert record["trace_id"] == first
        assert record["orphan"] is True
        assert record["session_id"] == "cron-1", "弱关联带上"

        assert bind_orphan() != first, "每次孤儿都是新 id"

    def test_orphan_resets_seq(self) -> None:
        """孤儿是新 trace → seq 从头开始（同一 trace 内才单调）。"""
        bind_orphan()
        assert audit._next_seq() == 1
        assert audit._next_seq() == 2

    def test_orphan_flag_not_leaked_to_next_bind(self, audit_records) -> None:
        """孤儿标不粘：随后的正常 bind 不应继承 orphan。"""
        bind_orphan()
        bind_context("trace-normal")
        audit.emit("tool_call", "tool_call.start")

        assert "orphan" not in _records(audit_records)[-1]
