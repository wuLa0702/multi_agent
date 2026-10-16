"""审计唯一入口 `core/audit.py` 单测（工作单 T1.1）。

覆盖：
1. 核心字段齐备 + 毫秒精度 + 点分事件名
2. 层自有字段平铺
3. **保留名冲突 → ValueError**（编程错误必须暴露，不静默丢字段）
4. 写失败**不冒泡**（审计是旁路）
5. `seq` 在**并发子任务**下不重复（这是设计稿 §3.1 点名的静默丢事件陷阱）
6. ContextVar 绑定 / 孤儿标记 / 未绑定时的如实留空
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.core import audit


@pytest.fixture(autouse=True)
def _fresh_context():
    """每用例重置审计上下文（模块级 ContextVar 会跨用例残留）。"""
    audit.bind_context("", session_id="", orphan=False)
    yield
    audit.bind_context("", session_id="", orphan=False)


def _records(caplog) -> list[dict]:
    """从 caplog 取审计行（注入的 logger 会 propagate 到 root）。"""
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "audit"
    ]


class TestRecordShape:
    """行结构：核心字段齐备 + 精度 + 命名。"""

    def test_core_fields_present(self, caplog) -> None:
        """每行必含 7 个核心字段（缺一即破坏下游契约）。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start", status=None, tool="x")

        rec = _records(caplog)[-1]
        for field in ("ts", "trace_id", "seq", "layer", "event", "status", "session_id"):
            assert field in rec, f"核心字段缺失：{field}"
        assert rec["layer"] == "tool_call"
        assert rec["event"] == "tool_call.start"

    def test_ts_has_millisecond_precision(self, caplog) -> None:
        """ts 必须到毫秒——只到秒会导致同秒内多事件**无法排序**（现状缺陷）。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start")

        ts = _records(caplog)[-1]["ts"]
        assert "." in ts and len(ts.split(".")[-1][:3]) == 3, f"非毫秒精度：{ts}"

    def test_layer_fields_flattened(self, caplog) -> None:
        """层自有字段平铺在顶层（与既有扁平 JSON 风格一致）。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit(
                "tool_call", "tool_call.end", status="degraded",
                tool="fetch_url", duration_ms=812,
            )

        rec = _records(caplog)[-1]
        assert rec["tool"] == "fetch_url"
        assert rec["duration_ms"] == 812
        assert rec["status"] == "degraded"

    def test_no_orphan_key_by_default(self, caplog) -> None:
        """非孤儿不写 `orphan` 键（避免噪声字段）。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start")

        assert "orphan" not in _records(caplog)[-1]

    def test_orphan_flagged(self, caplog) -> None:
        """孤儿（无上游触发）→ `orphan=true`（设计稿 B6：禁止留空、如实标记）。"""
        audit.bind_context("cron-abc", orphan=True)
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("sandbox", "sandbox.gc")

        assert _records(caplog)[-1]["orphan"] is True


# 7 个核心字段分三类，**行为各不相同**（测试要把这层说准，不能一锅端）：
#   ① 位置形参  layer / event          → 重复传 → Python 报 TypeError（自身保护）
#   ② 关键字形参 status / session_id    → 重复传 → 合法（绑定形参，不进 fields）
#   ③ 非形参    ts / trace_id / seq     → 进 fields → **保留名守卫**必须拦下
_POSITIONAL = frozenset({"layer", "event"})
_KEYWORD_ONLY = frozenset({"status", "session_id"})
_GUARDED = audit.CORE_FIELDS - _POSITIONAL - _KEYWORD_ONLY


class TestReservedNameGuard:
    """保留名冲突必须**当场暴露**（静默丢字段 = 审计悄悄失真）。"""

    @pytest.mark.parametrize("reserved", sorted(_GUARDED))
    def test_reserved_name_raises(self, reserved: str) -> None:
        """③ 非形参的 3 个：经 `**fields` 撞上 → ValueError。"""
        with pytest.raises(ValueError, match="核心字段重名"):
            audit.emit("tool_call", "tool_call.start", **{reserved: "覆盖尝试"})

    def test_guard_domain_is_exactly_those_three(self) -> None:
        """自检：守卫域 = `{ts, trace_id, seq}`——**不是全部 7 个**
        （防有人误以为 7 个都受守卫，从而漏掉另外两类的保护机制）。"""
        assert _GUARDED == {"ts", "trace_id", "seq"}
        assert _POSITIONAL | _KEYWORD_ONLY | _GUARDED == set(audit.CORE_FIELDS)

    @pytest.mark.parametrize("param", sorted(_KEYWORD_ONLY))
    def test_keyword_only_names_are_legitimate(self, param: str, caplog) -> None:
        """② 关键字形参：**合法传参**（不是冲突）——传了就用传的。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start", **{param: "合法值"})

        assert _records(caplog)[-1][param] == "合法值"

    @pytest.mark.parametrize("param", sorted(_POSITIONAL))
    def test_positional_names_cannot_be_passed_twice(self, param: str) -> None:
        """① 位置形参：重复传由 **Python 自身**报 TypeError——
        即"不可能被静默覆盖"，无需我们额外守卫。"""
        with pytest.raises(TypeError, match="multiple values"):
            audit.emit("tool_call", "tool_call.start", **{param: "覆盖尝试"})

    def test_error_is_not_swallowed_on_emit(self) -> None:
        """`emit()` 也不吞这个 ValueError（吞了业务继续跑、字段悄悄没了）。"""
        with pytest.raises(ValueError):
            audit.emit("tool_call", "tool_call.start", ts="bad")


class TestFailureIsolation:
    """审计是旁路：写失败绝不让业务崩。"""

    def test_write_failure_does_not_raise(self, monkeypatch) -> None:
        """底账写失败（磁盘满等）→ 只告警，**不抛**。"""
        monkeypatch.setattr(
            audit.audit_logger, "info",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        audit.emit("tool_call", "tool_call.start")  # 不应抛


class TestSeqUniqueness:
    """🔴 `seq` 的并发陷阱（设计稿 §3.1）：写错会**静默丢事件**。"""

    def test_seq_monotonic(self, caplog) -> None:
        with caplog.at_level("INFO", logger="audit"):
            for _ in range(3):
                audit.emit("tool_call", "tool_call.start")

        assert [r["seq"] for r in _records(caplog)] == [1, 2, 3]

    async def test_seq_unique_across_concurrent_tasks(self, caplog) -> None:
        """请求内并发（并行子代理）→ 各子任务**共享同一个计数器**，seq 不重复。

        若把计数器实现成 `ContextVar[int]`（子任务各持副本），本用例会看到重复值
        ——而 PG 侧 `UNIQUE(trace_id, seq)` + `ON CONFLICT DO NOTHING` 会把重复的
        那条**静默丢弃**（审计最不能接受的失败方式）。
        """

        async def worker() -> None:
            for _ in range(5):
                audit.emit("tool_call", "tool_call.start")
                await asyncio.sleep(0)  # 让出控制权，制造真正的交错

        with caplog.at_level("INFO", logger="audit"):
            await asyncio.gather(*(worker() for _ in range(4)))

        seqs = [r["seq"] for r in _records(caplog)]
        assert len(seqs) == 20
        assert len(set(seqs)) == 20, f"seq 重复（会静默丢事件）：{sorted(seqs)}"

    def test_bind_context_resets_seq(self, caplog) -> None:
        """重新 bind（新请求 / worker 取新任务）→ seq 从 1 重新开始。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start")
            audit.bind_context("t2")
            audit.emit("tool_call", "tool_call.start")

        assert [r["seq"] for r in _records(caplog)] == [1, 1]


class TestContextBinding:
    """trace_id / session_id 的绑定与"如实留空"。"""

    def test_unbound_writes_empty_string(self, caplog) -> None:
        """未绑定 → 写**空串**，不编造（设计稿 B6：孤儿也可，但不许瞎填）。"""
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start")

        assert _records(caplog)[-1]["trace_id"] == ""

    def test_bound_trace_and_session_propagate(self, caplog) -> None:
        audit.bind_context("trace-1", session_id="s-42")
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("tool_call", "tool_call.start")

        rec = _records(caplog)[-1]
        assert rec["trace_id"] == "trace-1"
        assert rec["session_id"] == "s-42"

    def test_explicit_session_id_overrides_context(self, caplog) -> None:
        """显式传 session_id 优先于 context（如 PolicyBackend 自带 thread_id）。"""
        audit.bind_context("trace-1", session_id="from-context")
        with caplog.at_level("INFO", logger="audit"):
            audit.emit("file_access", "file_access", session_id="explicit")

        assert _records(caplog)[-1]["session_id"] == "explicit"

    def test_trace_id_propagates_into_child_task(self, caplog) -> None:
        """请求内派生的子任务**自动继承** trace_id（create_task 复制 context）。"""
        async def main() -> None:
            audit.bind_context("trace-parent", session_id="s1")
            await asyncio.create_task(child())

        async def child() -> None:
            audit.emit("tool_call", "tool_call.start")

        with caplog.at_level("INFO", logger="audit"):
            asyncio.run(main())

        assert _records(caplog)[-1]["trace_id"] == "trace-parent"
