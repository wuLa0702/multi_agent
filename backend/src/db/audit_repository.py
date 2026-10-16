"""数据访问层（DAO）：审计事件（`audit_events` 表）。

**这一层只搬数据，不做治理判定**——事件的构造在 `core/audit.py::build_record()`，
本层只负责把一行写进 PG。

## 幂等（重放的依据）

`UNIQUE (trace_id, seq)` + `ON CONFLICT DO NOTHING`：
同一条事件重复写**不报错也不重复**——这样 `rebuild_from_jsonl()` 可以安全地
反复执行（PG 丢消息 / 降级期补录 / 迁移重建，都靠它）。

规范（规则 06 §2）：与 `skill_repository` 同款——显式接收连接、参数化 SQL、
写操作 commit、行由连接层 dict_row 提供。

设计依据：`docs/决策/2026-10-16-设计-审计与可观测-v1.md` §5.3。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

#: 核心字段（进**列**；其余进 `payload` JSONB）
_CORE_KEYS = ("trace_id", "seq", "ts", "layer", "event", "status", "session_id")


def _parse_ts(raw: Any) -> datetime:
    """`ts`（ISO 字符串，来自 JSONL）→ datetime；异常值回落当前时间。

    ⚠️ **不让一行坏数据阻塞整批重放**：`rebuild_from_jsonl` 会遍历大量历史行，
    一条时间戳格式异样就整批失败是不可接受的（记 warn 后继续）。
    """
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return datetime.now().astimezone()


def core_and_payload(record: dict[str, Any]) -> dict[str, Any]:
    """一行审计记录 → `(核心列, payload)` 的扁平化。

    Args:
        record: `core.audit.build_record()` 产出的扁平 dict

    Returns:
        含 `trace_id/seq/ts/layer/event/status/session_id/orphan/payload` 的 dict
        （`payload` 已 JSON 序列化为字符串，供 `%s::jsonb` 参数化写入）
    """
    payload = {k: v for k, v in record.items() if k not in _CORE_KEYS and k != "orphan"}
    return {
        "trace_id": str(record.get("trace_id") or ""),
        "seq": int(record.get("seq") or 0),
        "ts": _parse_ts(record.get("ts")),
        "layer": str(record.get("layer") or ""),
        "event": str(record.get("event") or ""),
        "status": record.get("status"),
        "session_id": record.get("session_id") or None,
        "orphan": bool(record.get("orphan")),
        "payload": json.dumps(payload, ensure_ascii=False, default=str),
    }


async def insert_event(conn: AsyncConnection, record: dict[str, Any]) -> bool:
    """写入一条审计事件（**幂等**：重复 `(trace_id, seq)` 静默跳过）。

    Args:
        conn: PG 连接
        record: 扁平审计行（`build_record()` 的产出）

    Returns:
        True = 真的插入了；False = 冲突跳过（重放时的正常情形）

    Raises:
        psycopg.Error: 连接/语法错误（由调用方决定重试或进死信——本层不吞）
    """
    row = core_and_payload(record)
    cursor = await conn.execute(
        """INSERT INTO audit_events
           (trace_id, seq, ts, layer, event, status, session_id, orphan, payload)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
           ON CONFLICT (trace_id, seq) DO NOTHING
           RETURNING id""",
        (
            row["trace_id"],
            row["seq"],
            row["ts"],
            row["layer"],
            row["event"],
            row["status"],
            row["session_id"],
            row["orphan"],
            row["payload"],
        ),
    )
    inserted = await cursor.fetchone()
    await conn.commit()
    return inserted is not None


async def count_events(conn: AsyncConnection, *, layer: str | None = None) -> int:
    """统计事件条数（可选按 layer 过滤）。

    用途：`rebuild_from_jsonl` 的**一致性校验**——扫 JSONL 与 PG 条数对比，
    验证"PG 可重建"不是口号（设计稿 §6）。

    Args:
        conn: PG 连接
        layer: 限定层；None = 全量

    Returns:
        条数
    """
    if layer is None:
        cursor = await conn.execute("SELECT COUNT(*) AS n FROM audit_events")
    else:
        cursor = await conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE layer = %s", (layer,)
        )
    row = await cursor.fetchone()
    return int(row["n"]) if row else 0


async def delete_before(conn: AsyncConnection, cutoff: datetime, layers: tuple[str, ...]) -> int:
    """删除指定层的过期事件（保留策略，按 layer 分档）。

    Args:
        conn: PG 连接
        cutoff: 早于此时间的事件删除
        layers: 限定层（分档保留：安全类留更久）

    Returns:
        删除行数
    """
    if not layers:
        return 0
    cursor = await conn.execute(
        "DELETE FROM audit_events WHERE ts < %s AND layer = ANY(%s)",
        (cutoff, list(layers)),
    )
    await conn.commit()
    return cursor.rowcount
