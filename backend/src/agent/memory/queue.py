"""记忆后台任务队列（记忆抽取子代理方案 §3.4/§7.1）：监控 + 日志 + 并发限制。

替代裸 asyncio.create_task——后台抽取任务可观测、不堆积、失败可追踪。

⚠️ 并发实现（评审问题 2 定案）：**多 worker 协程**——lifespan 里
`asyncio.create_task(run_worker())` 调 _WORKER_COUNT 次，每个 worker 独立
消费，自然并发；单 worker 循环 + Semaphore 是伪并发（串行执行）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

# 并发 worker 数（后台任务不堆积；学习 demo 并发 2 足够）
_WORKER_COUNT = 2
# 队列上限（防无限堆积；超出拒绝并记日志）
_MAX_QUEUE = 100
# 指纹 LRU 上限（_seen 只增不减会内存泄漏——超限逐出最旧）
_SEEN_MAX = 1000


@dataclass
class MemoryTask:
    """记忆抽取任务：对话历史 + 会话定位 + 指纹（幂等去重）。"""

    session_id: str
    user_message: str
    assistant_text: str
    fingerprint: str   # session_id + 消息 hash（防重复入队）


class MemoryTaskQueue:
    """进程内单例后台队列（lifespan 启动/关闭）。

    Attributes:
        _queue: 待处理任务
        _seen: 指纹 LRU（幂等去重，上限 _SEEN_MAX 防泄漏）
        stats: 监控计数（pending/running/completed/failed）
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[MemoryTask] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._seen: dict[str, None] = {}   # 插入序 = 使用序（LRU 逐出）
        self.stats = {"pending": 0, "running": 0, "completed": 0, "failed": 0}

    def enqueue(self, task: MemoryTask) -> bool:
        """入队（幂等：相同指纹不重复入队；队列满拒绝）。

        Args:
            task: 记忆抽取任务

        Returns:
            True = 入队成功；False = 重复/队列满
        """
        if task.fingerprint in self._seen:
            logger.debug("记忆任务去重：fingerprint=%s", task.fingerprint)
            return False
        try:
            self._queue.put_nowait(task)
        except asyncio.QueueFull:
            logger.warning("记忆队列满（%d），任务拒绝：session=%s", _MAX_QUEUE, task.session_id)
            return False
        self._seen[task.fingerprint] = None
        while len(self._seen) > _SEEN_MAX:        # LRU 逐出最旧（防内存泄漏）
            self._seen.pop(next(iter(self._seen)))
        self.stats["pending"] += 1
        self._audit("enqueue", task, "")
        return True

    async def run_worker(self, consumer) -> None:
        """常驻 worker：取任务 → 消费（consumer 执行 memory_agent）→ 记录。

        多 worker 并发：lifespan 启动 _WORKER_COUNT 个本协程——每个独立
        while 循环消费，天然并发。

        Args:
            consumer: 异步消费函数（ainvoke memory_agent + 写入），
                由调用方注入（解耦队列与子代理）
        """
        while True:
            task = await self._queue.get()
            self.stats["pending"] -= 1
            self.stats["running"] += 1
            self._audit("start", task, "")
            try:
                result = await consumer(task)
                self.stats["completed"] += 1
                self._audit("completed", task, str(result)[:200])
            except Exception:  # noqa: BLE001 —— 后台任务失败不冒泡
                logger.exception("记忆任务失败：session=%s", task.session_id)
                self.stats["failed"] += 1
                self._audit("failed", task, "")
            finally:
                self.stats["running"] -= 1
            self._queue.task_done()

    def _audit(self, event: str, task: MemoryTask, detail: str) -> None:
        """任务审计行（layer=memory_agent，与 policy_backend 同构扁平 JSON）。"""
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "layer": "memory_agent",
            "event": event,
            "session_id": task.session_id,
            "fingerprint": task.fingerprint,
            "detail": detail,
        }
        audit_logger.info(json.dumps(record, ensure_ascii=False))


# 进程内单例（lifespan 启动 worker，关闭时 stop）
memory_task_queue = MemoryTaskQueue()
