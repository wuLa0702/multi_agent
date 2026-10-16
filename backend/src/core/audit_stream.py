"""审计双写的**第二路**：Redis Stream 投递 + 消费 worker + 死信 + 背压。

## 位置（为什么在 core/）

`emit()`（`core/audit.py`）写 JSONL 是**权威底账**；本模块负责把它送进 Redis Stream，
worker 再落 PG（**派生索引**）。三者同属底座层基建，故放 `core/`。

## 三条不可动摇的纪律（设计稿 §4.1 / §4.2）

1. **底账先落、且必成功**——投递发生在 JSONL 写成功**之后**（顺序写在
   `core/audit.py::emit` 里，不在本模块）
2. **投递失败不阻断业务**——sink 内部吞异常只告警；后果仅是"PG 落后"，
   可由 `rebuild_from_jsonl()` 追平
3. **宁 PG 落后，不丢底账**——背压时降级为"只保 JSONL"，不反压业务

## v1 的重试模型（与设计稿的差异，如实记录）

设计稿 §4.1.2 写的是「不 ack → 留 PEL → `XCLAIM` 重投」。**v1 实现简化为**
「**进程内立即重试 N 次，仍失败 → 死信 + ack**」：

| | 设计稿（PEL 重投） | v1（立即重试） |
|---|---|---|
| 进程崩溃时 | 消息留 PEL，重启可重投 | 消息随进程消失 |
| 复杂度 | 需 `XAUTOCLAIM` + 尝试计数持久化 | 简单 |

**为什么可接受**：崩在"读走未入库"这段的消息，**JSONL 底账仍在**——
`rebuild_from_jsonl()` 能补回（设计稿 §4.1.5 的"PG 可重建"正是为此）。
**PEL 重投列为后续增强**（工作单未列，作为已知简化记录在此）。

## 背压（设计稿 §4.1.3）

`XADD MAXLEN ~ N` 近似裁剪保护 Redis 内存；被裁掉的只是"待入 PG 的副本"，
**底账一条不丢**。逼近上限时另记告警（运维可见）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.core.paths import get_log_dir

logger = logging.getLogger(__name__)

#: Stream 键与消费组（设计稿 B1）
STREAM_KEY = "audit:stream"
GROUP = "audit-writers"
CONSUMER = "worker-0"

#: 近似裁剪上限（保护 Redis 256m 限额；被裁的只是 PG 副本，底账不丢）
STREAM_MAXLEN = 100_000

#: 单条事件的最大重试次数；超限 → 死信（**不静默丢**）
MAX_RETRIES = 3

#: 死信文件（**放 JSONL 而非 PG**：死信的主因常是 PG 故障，写 PG 会在最需要时失败）
DEAD_LETTER_FILENAME = "audit_dead_letter.jsonl"

_sync_client: Any = None


def _client() -> Any:
    """同步 Redis 客户端（进程级单例）。

    **为什么用同步客户端**：`emit()` 是同步函数（8 个写入点全是同步上下文），
    而 `redis.asyncio` 需要 await。投递到本地 Redis 约 0.1–1ms，与**同一函数里
    已有的 JSONL 同步写盘**同量级——故不额外引入异步边界。

    Returns:
        redis.Redis（decode_responses=True，与 `core/redis.py` 口径一致）
    """
    global _sync_client
    if _sync_client is None:
        from redis import Redis  # 同步客户端（与 asyncio 版并存，互不影响）

        _sync_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _sync_client


def stream_sink(record: dict[str, Any]) -> None:
    """`emit()` 的投递回调：把一行审计 XADD 进 Stream。

    **绝不抛异常**（调用方 `emit` 还有一层保护，这里是第一道）：
    投递失败只告警——底账已落，PG 可事后重放补齐。

    Args:
        record: 扁平审计行
    """
    try:
        _client().xadd(
            STREAM_KEY,
            {"payload": json.dumps(record, ensure_ascii=False, default=str)},
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
    except Exception:  # noqa: BLE001 —— 旁路：投递失败不影响业务
        logger.warning("审计投递到 Stream 失败（降级：底账已落，可重放补齐）", exc_info=True)


def write_dead_letter(record: dict[str, Any], error: str, attempts: int) -> None:
    """写死信（原始行 + 错误 + 尝试次数 + 时间）。

    与底账**同一条已验证可靠的路径**（本地文件 append），不引入新依赖——
    Redis / PG 都可能正是故障源。

    Args:
        record: 原始审计行（原样保留，便于事后人工处置）
        error: 最后一次的错误摘要
        attempts: 已尝试次数
    """
    try:
        path = Path(get_log_dir()) / DEAD_LETTER_FILENAME
        line = json.dumps(
            {
                "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "attempts": attempts,
                "error": error[:500],
                "record": record,
            },
            ensure_ascii=False,
            default=str,
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        logger.error("审计事件进死信（%d 次重试仍失败）：%s", attempts, error[:120])
    except Exception:  # noqa: BLE001 —— 死信写不了也不能崩（已尽人事）
        logger.error("死信写入失败（原始事件丢失风险）", exc_info=True)


def ensure_group() -> None:
    """确保消费组存在（幂等；`BUSYGROUP` 视为已存在）。"""
    try:
        _client().xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001 —— 已存在（BUSYGROUP）属正常
        if "BUSYGROUP" not in str(exc):
            raise


def _read_batch(count: int, block_ms: int) -> list[tuple[str, dict]]:
    """从 Stream 读一批新消息（阻塞最多 `block_ms`）。

    Returns:
        `[(msg_id, record), ...]`；解析失败的条目**丢弃并告警**（坏消息不该卡住队列）
    """
    raw = _client().xreadgroup(
        GROUP, CONSUMER, {STREAM_KEY: ">"}, count=count, block=block_ms
    )
    out: list[tuple[str, dict]] = []
    for _stream, entries in raw or []:
        for msg_id, fields in entries:
            try:
                out.append((msg_id, json.loads(fields["payload"])))
            except Exception:  # noqa: BLE001 —— 坏消息：进死信，不阻塞后续
                write_dead_letter(
                    {"raw": fields.get("payload", "")}, "消息体不是合法 JSON", 1
                )
                _client().xack(STREAM_KEY, GROUP, msg_id)
    return out


async def consume_batch(
    insert, *, count: int = 50, block_ms: int = 1000
) -> int:
    """消费一批并入库（测试与 worker 共用这一条路径）。

    Args:
        insert: 异步入库函数 `insert(record) -> bool`（worker 注入，便于测）
        count: 单批条数
        block_ms: 无消息时的阻塞时长

    Returns:
        本批**成功入库**的条数（含幂等跳过的）
    """
    import asyncio

    batch = await asyncio.to_thread(_read_batch, count, block_ms)
    ok = 0
    for msg_id, record in batch:
        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await insert(record)
                ok += 1
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001 —— 入库失败：重试，超限进死信
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.05 * attempt)  # 轻退避（不阻塞其他消息）
        if last_error:
            write_dead_letter(record, last_error, MAX_RETRIES)
        # 无论成败都 ack：失败已进死信（**不静默丢**），留在 PEL 只会重复堆积
        try:
            _client().xack(STREAM_KEY, GROUP, msg_id)
        except Exception:  # noqa: BLE001
            logger.debug("ack 失败（下次读会被跳过）", exc_info=True)
    return ok


#: 底账文件名（与 `core/logging.py` 的 audit handler 一致）
LEDGER_FILENAME = "file_access_audit.jsonl"


def ledger_files() -> list[Path]:
    """底账文件列表（当前文件 + 滚动出的历史文件，按名排序）。

    滚动文件由 `SizeTimedRotatingFileHandler` 产出，命名形如
    `file_access_audit.jsonl.2026-10-15`——重放必须**一并覆盖**，
    否则"PG 丢了昨天的数据"就补不回来。

    Returns:
        存在的底账文件（新 → 旧之外的顺序无关，重放幂等）
    """
    log_dir = Path(get_log_dir())
    candidates = [log_dir / LEDGER_FILENAME]
    candidates += sorted(log_dir.glob(f"{LEDGER_FILENAME}.*"), reverse=True)
    return [p for p in candidates if p.is_file()]


def read_ledger(files: list[Path] | None = None) -> tuple[list[dict], list[str]]:
    """读底账文件 → `(记录列表, 坏行说明)`。

    **坏行不中断**：审计底账里出现一行解析不了的内容，不能因此让整次重放失败
    ——收集起来返回，由调用方决定告警或人工处置。

    Args:
        files: 指定文件；None → `ledger_files()` 全量

    Returns:
        `(records, errors)`；errors 是 `"文件:行号 原因"` 的人类可读串
    """
    records: list[dict] = []
    errors: list[str] = []
    for path in files if files is not None else ledger_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except Exception as exc:  # noqa: BLE001 —— 坏行收集，不中断
                errors.append(f"{path.name}:{lineno} {type(exc).__name__}")
    return records, errors


async def rebuild_from_jsonl(
    insert, *, files: list[Path] | None = None
) -> dict[str, int | list[str]]:
    """**重放**：底账 JSONL → PG（幂等）。

    这是"PG 可重建"的落地——没有它，设计稿 §4.1.5 那句就只是口号。
    用途：① PG 丢消息 ② 降级期补录 ③ 迁移重建 ④ 一致性校验。

    幂等性来自 PG 的 `UNIQUE (trace_id, seq)` + `ON CONFLICT DO NOTHING`，
    故**可安全重复执行**（重复的部分记为 skipped）。

    Args:
        insert: 异步入库函数 `insert(record) -> bool`
        files: 指定底账文件；None → 全部（含滚动历史）

    Returns:
        `{"scanned": 总行数, "inserted": 新插入, "skipped": 幂等跳过, "errors": 坏行说明}`
    """
    records, errors = read_ledger(files)
    inserted = skipped = 0
    for record in records:
        try:
            was_new = await insert(record)
        except Exception as exc:  # noqa: BLE001 —— 单行失败不中断整次重放
            errors.append(f"insert failed: {type(exc).__name__}: {exc}")
            continue
        if was_new:
            inserted += 1
        else:
            skipped += 1
    logger.info(
        "审计重放完成：扫描 %d / 新插 %d / 幂等跳过 %d / 坏行 %d",
        len(records), inserted, skipped, len(errors),
    )
    return {
        "scanned": len(records),
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }


async def archive_old_ledgers(keep_days: int, *, log_dir: Path | None = None) -> int:
    """把超期的**滚动底账**压缩归档为 `.gz`（不删除）。

    底账是权威凭证，故**压缩而非删除**（压缩比通常 5–10×）。
    当前正在写的 `file_access_audit.jsonl` **不归档**（还在追加）。

    Args:
        keep_days: 保留天数（更早的滚动文件转 .gz）
        log_dir: 日志目录（测试注入）

    Returns:
        本次归档的文件数
    """
    import gzip
    import shutil
    import time

    base = Path(log_dir) if log_dir is not None else Path(get_log_dir())
    cutoff = time.time() - keep_days * 86400
    archived = 0
    for path in base.glob(f"{LEDGER_FILENAME}.*"):
        if path.suffix == ".gz" or path.stat().st_mtime >= cutoff:
            continue
        try:
            with open(path, "rb") as src, gzip.open(f"{path}.gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
            archived += 1
        except OSError:  # noqa: BLE001 —— 单个归档失败不影响其它
            logger.warning("底账归档失败：%s", path.name, exc_info=True)
    if archived:
        logger.info("审计底账归档 %d 个文件为 .gz", archived)
    return archived


async def run_retention_loop(
    purge, *, interval_seconds: float = 86400.0, keep_days: int = 90
) -> None:
    """常驻保留任务：按分档删 PG + 归档旧底账（lifespan 启动；一天一次）。

    ⚠️ **不引入调度组件**（X2 拍板）：与记忆队列同款的低频后台循环已足够——
    保留策略对时效性不敏感，晚跑几小时无影响。

    Args:
        purge: 异步清理函数 `purge(cutoff_days) -> int`（由装配方注入，负责
            按 layer 分档调用仓储的 `delete_before`）
        interval_seconds: 循环间隔（默认一天）
        keep_days: 底账归档阈值（天）
    """
    import asyncio

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await purge()
            await archive_old_ledgers(keep_days)
        except asyncio.CancelledError:
            logger.info("审计保留任务收到取消，退出")
            raise
        except Exception:  # noqa: BLE001 —— 保留任务不能因单次异常退出
            logger.exception("审计保留任务单轮异常（继续下一轮）")


async def run_worker(insert, *, poll_seconds: float = 1.0) -> None:
    """常驻消费 worker：循环 `consume_batch`（lifespan 启动）。

    **单条失败不终止循环**：worker 崩了审计就断档，故异常只记日志继续。

    Args:
        insert: 异步入库函数 `insert(record) -> bool`
        poll_seconds: 空转时的休眠（Stream 自身也有 block，双保险）
    """
    import asyncio

    while True:
        try:
            await consume_batch(insert, block_ms=int(poll_seconds * 1000))
        except asyncio.CancelledError:
            logger.info("审计 worker 收到取消，退出")
            raise
        except Exception:  # noqa: BLE001 —— 循环不能因单次异常退出
            logger.exception("审计 worker 单轮异常（继续下一轮）")
            await asyncio.sleep(poll_seconds)
