"""审计双写测试（工作单批次 3：T3.1–T3.6）。

分两层：
1. **纯逻辑**（不依赖 Redis/PG）：sink 安装语义 / 死信写入 / 消费重试与 ack
2. **真实 PG**（按需 `pg_schema`）：表结构 + 幂等插入 + 计数 + 分档删除

⚠️ 真实 Redis 的端到端（XADD → worker → PG）**不在此文件**
（会依赖运行中的 Redis，且污染共享 Stream）；Redis 交互用假客户端替身覆盖，
真实链路由 §「端到端」那条用 monkeypatch 打桩验证。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.core import audit, audit_stream
from src.db import audit_repository as repo


@pytest.fixture(autouse=True)
def _clean_audit_state():
    """每用例前后清 sink 与审计上下文（模块级全局状态）。"""
    audit.install_sink(None)
    audit.bind_context("", session_id="", orphan=False)
    yield
    audit.install_sink(None)
    audit.bind_context("", session_id="", orphan=False)


class _FakeRedis:
    """假 Redis：够用即可（xadd / xreadgroup / xack / xgroup_create）。

    ⚠️ 形状必须与真实调用一致：`xreadgroup` 返回的 entries 是
    `(msg_id, {"payload": "<json 字符串>"})`——**记录是包在 `payload` 字段里的**。
    （本测试首版把记录直接当 fields，导致被当成"坏 JSON"送死信。）
    """

    def __init__(self, records: list[dict] | None = None) -> None:
        #: 待读消息（真实形状：fields 里放 payload 字符串）
        self.entries: list[tuple[str, dict]] = [
            (f"1-{i}", {"payload": json.dumps(r)})
            for i, r in enumerate(records or [])
        ]
        self.added: list[dict] = []
        self.acked: list[str] = []
        self.group_created = False

    def xadd(self, key, fields, maxlen=None, approximate=False):
        self.added.append(
            {"key": key, "fields": fields, "maxlen": maxlen, "approximate": approximate}
        )
        return f"1-{len(self.added)}"

    def xgroup_create(self, key, group, id="0", mkstream=False):
        if self.group_created:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.group_created = True

    def xreadgroup(self, group, consumer, streams, count=10, block=0):
        if not self.entries:
            return []
        batch, self.entries = self.entries, []
        return [(audit_stream.STREAM_KEY, batch)]

    def xack(self, key, group, msg_id):
        self.acked.append(msg_id)
        return 1


# ── sink 语义（T3.2 的开关面） ──


class TestSinkWiring:
    """`emit` 与投递解耦：默认不投递；装了才投。"""

    def test_emit_without_sink_only_writes_ledger(self, audit_records) -> None:
        """未装 sink（单测/脚本态）→ 只写 JSONL，**不碰 Redis**。"""
        assert audit.has_sink() is False
        audit.emit("tool_call", "tool_call.start")

        assert len(audit_records) == 1, "底账照写"

    def test_emit_calls_sink_with_same_record(self, audit_records) -> None:
        """装了 sink → 投递**同一份**记录（双写=同一事件两路，不是两次采集）。"""
        seen: list[dict] = []
        audit.install_sink(seen.append)

        audit.emit("tool_call", "tool_call.end", status="ok")

        assert len(seen) == 1
        ledger = json.loads(audit_records[-1].getMessage())
        assert seen[0] == ledger, "投递的与落盘的是同一行"

    def test_sink_failure_does_not_break_business(self, audit_records) -> None:
        """投递失败（Redis 挂）→ 只告警；**底账仍落**、业务不崩。"""
        def _boom(_record):
            raise ConnectionError("redis down")

        audit.install_sink(_boom)
        audit.emit("tool_call", "tool_call.start")   # 不应抛

        assert len(audit_records) == 1, "底账必须照落（设计稿 §4.1.5：JSONL 权威）"

    def test_stream_sink_swallows_redis_errors(self, monkeypatch) -> None:
        """`stream_sink` 自身也吞异常（第一道防线，不依赖 emit 的兜底）。"""
        class _Dead:
            def xadd(self, *a, **k):
                raise ConnectionError("redis down")

        monkeypatch.setattr(audit_stream, "_client", lambda: _Dead())
        audit_stream.stream_sink({"layer": "x", "event": "y"})   # 不应抛

    def test_stream_sink_pushes_payload(self, monkeypatch) -> None:
        """投递形态：payload 为 JSON 字符串 + 近似裁剪上限（背压保护）。"""
        fake = _FakeRedis()
        monkeypatch.setattr(audit_stream, "_client", lambda: fake)

        audit_stream.stream_sink({"layer": "tool_call", "event": "tool_call.start"})

        assert len(fake.added) == 1
        entry = fake.added[0]
        assert entry["key"] == audit_stream.STREAM_KEY
        assert json.loads(entry["fields"]["payload"])["event"] == "tool_call.start"
        assert entry["maxlen"] == audit_stream.STREAM_MAXLEN
        assert entry["approximate"] is True


# ── 死信（T3.4） ──


class TestDeadLetter:
    """死信：写本地 JSONL（**不放 PG**——PG 常正是故障源）。"""

    def test_write_dead_letter_keeps_raw_record(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(audit_stream, "get_log_dir", lambda: tmp_path)

        audit_stream.write_dead_letter(
            {"layer": "tool_call", "event": "tool_call.start", "seq": 3},
            "psycopg.OperationalError: down",
            3,
        )

        path = tmp_path / audit_stream.DEAD_LETTER_FILENAME
        line = json.loads(path.read_text(encoding="utf-8").strip())
        assert line["attempts"] == 3
        assert "down" in line["error"]
        assert line["record"]["seq"] == 3, "原始行原样保留（便于人工处置）"

    def test_dead_letter_failure_does_not_raise(self, monkeypatch) -> None:
        """死信写不了也不能崩（已尽人事）——不能因为审计把业务带崩。"""
        monkeypatch.setattr(
            audit_stream, "get_log_dir",
            lambda: (_ for _ in ()).throw(OSError("no disk")),
        )
        audit_stream.write_dead_letter({"a": 1}, "err", 1)   # 不应抛


# ── 消费：重试 + ack（T3.4） ──


class TestConsumeBatch:
    """消费一批：成功入库 → ack；失败重试 → 超限死信但也 ack（不堆积 PEL）。"""

    async def test_success_acks_and_counts(self, monkeypatch) -> None:
        fake = _FakeRedis([{"seq": 1}, {"seq": 2}])
        monkeypatch.setattr(audit_stream, "_client", lambda: fake)
        inserted: list[dict] = []

        async def insert(record):
            inserted.append(record)
            return True

        ok = await audit_stream.consume_batch(insert)

        assert ok == 2 and len(inserted) == 2
        assert len(fake.acked) == 2, "两条都 ack（消费成功即确认）"

    async def test_retry_then_dead_letter(self, monkeypatch, tmp_path) -> None:
        """入库连续失败 → 重试 MAX_RETRIES 次 → 进死信 → **仍 ack**（不堆 PEL）。"""
        fake = _FakeRedis([{"seq": 9, "layer": "tool_call"}])
        monkeypatch.setattr(audit_stream, "_client", lambda: fake)
        monkeypatch.setattr(audit_stream, "get_log_dir", lambda: tmp_path)
        calls = {"n": 0}

        async def insert(record):
            calls["n"] += 1
            raise RuntimeError("PG down")

        ok = await audit_stream.consume_batch(insert)

        assert calls["n"] == audit_stream.MAX_RETRIES, "重试到上限"
        assert ok == 0
        assert len(fake.acked) == 1, "失败已进死信，不该留在 PEL 重复堆积"
        dead = (tmp_path / audit_stream.DEAD_LETTER_FILENAME).read_text(encoding="utf-8")
        assert "PG down" in dead and '"seq": 9' in dead

    async def test_bad_payload_goes_dead_letter_not_blocking(self, monkeypatch, tmp_path) -> None:
        """消息体不是合法 JSON → 进死信 + ack，**不阻塞后续消息**。"""
        fake = _FakeRedis([{"seq": 2}])
        # 手工塞一条坏消息到队首（形状与其他消息一致，内容是坏 JSON）
        fake.entries.insert(0, ("1-bad", {"payload": "{坏 JSON"}))
        monkeypatch.setattr(audit_stream, "_client", lambda: fake)
        monkeypatch.setattr(audit_stream, "get_log_dir", lambda: tmp_path)
        inserted: list[dict] = []

        async def insert(record):
            inserted.append(record)
            return True

        ok = await audit_stream.consume_batch(insert)

        assert ok == 1 and inserted == [{"seq": 2}], "坏消息不阻塞好消息"
        assert len(fake.acked) == 2, "坏消息与好消息都被 ack（不在 PEL 堆积）"


# ── 真实 PG（T3.1） ──


class TestRepositoryOnPG:
    """表结构 + 幂等插入 + 计数 + 分档删除（真实 PG，按需 `pg_schema`）。"""

    @staticmethod
    def _record(seq: int = 1, **over) -> dict:
        base = {
            "ts": "2026-10-16T12:00:00.000+08:00", "trace_id": "t-1", "seq": seq,
            "layer": "tool_call", "event": "tool_call.start", "status": None,
            "session_id": "s-1", "tool": "internet_search",
        }
        base.update(over)
        return base

    async def test_insert_and_roundtrip(self, pg_schema) -> None:
        from src.db import connection as db_conn

        async with db_conn.connection() as conn:
            inserted = await repo.insert_event(conn, self._record())
            count = await repo.count_events(conn)

        assert inserted is True
        assert count == 1

    async def test_duplicate_is_idempotent_not_error(self, pg_schema) -> None:
        """同 `(trace_id, seq)` 再插 → 静默跳过（**这是重放能安全重复的依据**）。"""
        from src.db import connection as db_conn

        async with db_conn.connection() as conn:
            first = await repo.insert_event(conn, self._record())
            second = await repo.insert_event(conn, self._record())
            count = await repo.count_events(conn)

        assert first is True and second is False, "第二次应幂等跳过而非报错"
        assert count == 1

    async def test_layer_fields_go_to_payload(self, pg_schema) -> None:
        """层自有字段进 payload JSONB；核心字段进列（可按列查）。"""
        from src.db import connection as db_conn

        async with db_conn.connection() as conn:
            await repo.insert_event(conn, self._record())
            cursor = await conn.execute(
                "SELECT layer, session_id, payload FROM audit_events"
            )
            row = await cursor.fetchone()

        assert row["layer"] == "tool_call"
        assert row["session_id"] == "s-1"
        assert row["payload"] == {"tool": "internet_search"}
        assert "seq" not in row["payload"], "核心字段不进 payload（避免两份）"

    async def test_delete_before_by_layer(self, pg_schema) -> None:
        """保留策略：按 layer 分档删除（安全类留更久 → 不在删除名单里）。"""
        from src.db import connection as db_conn

        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        async with db_conn.connection() as conn:
            await repo.insert_event(conn, {**self._record(1), "ts": old, "layer": "sandbox"})
            await repo.insert_event(conn, {**self._record(2), "ts": old, "layer": "security"})
            deleted = await repo.delete_before(
                conn, datetime.now(timezone.utc) - timedelta(days=90), ("sandbox",)
            )
            left = await repo.count_events(conn)

        assert deleted == 1, "只删 sandbox 档"
        assert left == 1, "security 档保留（长期）"
