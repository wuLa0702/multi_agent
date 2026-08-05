"""会话级沙箱池（方案 §3.1 / §7.2）：thread_id 维度复用 + TTL 续期 + 空闲回收。

- get_sandbox(thread_id)：命中续期复用；未命中懒创建（锁内双检 + 惰性 sweep）；
  池上限 sandbox_pool_max 超限抛 SandboxFullError（工具层转友好错误，不排队）
- destroy(thread_id)：主动销毁（会话删除联动；幂等）
- sweep()：空闲超阈值销毁（取用时惰性触发）
- 续期失败（评审问题 2 修复）：_renew 返回 bool，失败即销毁条目，
  get_sandbox 走重建而非 return 已销毁对象

设计文档：docs/decisions/方案-沙箱能力开发计划-v1.md §3.1 / §7.2
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from opensandbox.sync.sandbox import SandboxSync

from src.core.config import settings
from src.sandbox.adapter import OpenSandboxAdapter

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")


class SandboxFullError(RuntimeError):
    """沙箱池达到并发上限（sandbox_pool_max）——工具层捕获转友好错误提示。"""


@dataclass
class _Entry:
    """池条目：沙箱实例 + 最近取用时间（空闲回收判据）。"""

    sandbox: SandboxSync
    last_used: float


class SandboxPool:
    """进程内会话级沙箱池（thread_id 维度，线程安全）。

    与 backend 会话隔离同维度：每会话一个沙箱，连续工具调用共享
    （同实例连续 run() 保留文件与环境）；取用即 renew 续期（活跃会话
    永不过期）；空闲超阈值 sweep 销毁（防资源泄漏，服务端 TTL 仅兜底）。

    Attributes:
        _adapter: OpenSandboxAdapter（create/destroy 委托）
        _entries: thread_id → _Entry
        _lock: 懒创建/回收锁（同 main_agent._agents 双重检查模式）
    """

    def __init__(self, adapter: OpenSandboxAdapter | None = None) -> None:
        self._adapter = adapter or OpenSandboxAdapter()
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get_sandbox(self, thread_id: str) -> SandboxSync:
        """取会话沙箱：命中续期复用；未命中懒创建（锁内双检 + 惰性 sweep）。

        Args:
            thread_id: 会话 ID（== session_id）

        Returns:
            就绪的 SandboxSync 实例

        Raises:
            SandboxFullError: 池达到并发上限（sandbox_pool_max）
            SandboxException: 创建失败（由工具层降级为错误字符串，不中断 run）
        """
        if not settings.sandbox_pool_enabled:
            # 非池化兼容：只创建不托管（生命周期由调用方 try/finally 自管，
            # 见 sandbox_tool 非池化分支——评审问题 1）
            return self._adapter.create_sandbox()
        with self._lock:
            self._sweep_locked()
            entry = self._entries.get(thread_id)
            if entry is not None:
                if self._renew(entry, thread_id):
                    return entry.sandbox
                # 评审问题 2：续期失败时 _renew 内部已销毁条目——
                # 不 return 已销毁的沙箱，继续走下方创建新沙箱逻辑
            if len(self._entries) >= settings.sandbox_pool_max:
                # 池上限（本地 6 / 云端 4，配置化）：不排队不无限创建——
                # 直接拒绝，工具层转"沙箱资源已满"友好错误，agent 可换方案
                self._audit("full", thread_id, "")
                raise SandboxFullError(
                    f"沙箱资源已满（上限 {settings.sandbox_pool_max} 个并发会话），"
                    "请稍后重试，或换一种不需要沙箱的方式。"
                )
            sandbox = self._adapter.create_sandbox()
            self._entries[thread_id] = _Entry(sandbox, time.time())
            self._audit("create", thread_id, self._sandbox_id(sandbox))
            return sandbox

    def destroy(self, thread_id: str) -> None:
        """主动销毁会话沙箱（会话删除 / 显式清理；幂等，不存在静默通过）。"""
        with self._lock:
            entry = self._entries.pop(thread_id, None)
        if entry is not None:
            self._safe_destroy(entry, thread_id, "session-delete")

    def sweep(self) -> int:
        """空闲回收：超过 sandbox_idle_ttl 未取用的沙箱销毁，返回销毁数。"""
        with self._lock:
            return self._sweep_locked()

    # ── 内部：回收 / 续期 / 审计 ──

    def _sweep_locked(self) -> int:
        cutoff = time.time() - settings.sandbox_idle_ttl
        removed = 0
        for tid, entry in list(self._entries.items()):
            if entry.last_used < cutoff:
                self._entries.pop(tid, None)
                self._safe_destroy(entry, tid, "idle-sweep")
                removed += 1
        return removed

    def _renew(self, entry: _Entry, thread_id: str) -> bool:
        """续期 + 刷新最近使用；失败销毁条目并返回 False（调用方走重建）。

        Args:
            entry: 池条目
            thread_id: 会话 ID

        Returns:
            True = 续期成功（沙箱可用）；False = 续期失败（条目已销毁）
        """
        try:
            entry.sandbox.renew(timedelta(seconds=settings.sandbox_timeout))
            entry.last_used = time.time()
            self._audit("renew", thread_id, self._sandbox_id(entry.sandbox))
            return True
        except Exception:  # noqa: BLE001 —— 续期失败 = 沙箱可能已过期，销毁让下次重建
            logger.warning("沙箱续期失败（销毁重建）：thread=%s", thread_id)
            self._entries.pop(thread_id, None)
            self._safe_destroy(entry, thread_id, "renew-failed")
            return False

    def _safe_destroy(self, entry: _Entry, thread_id: str, reason: str) -> None:
        try:
            self._adapter.destroy(entry.sandbox)
        except Exception:  # noqa: BLE001 —— 销毁失败不阻塞调用方
            logger.warning("沙箱销毁失败：thread=%s reason=%s", thread_id, reason)
        self._audit("destroy", thread_id, self._sandbox_id(entry.sandbox))

    def _audit(self, event: str, thread_id: str, sandbox_id: str) -> None:
        """生命周期审计（与 policy_backend 同构的扁平 JSON 行，layer=sandbox）。"""
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "thread_id": thread_id,
            "layer": "sandbox",
            "event": event,
            "sandbox_id": sandbox_id,
        }
        audit_logger.info(json.dumps(record, ensure_ascii=False))

    @staticmethod
    def _sandbox_id(sandbox: SandboxSync) -> str:
        return str(getattr(sandbox, "id", ""))  # 防御：实例属性随 SDK 版本


# 进程内共享池单例（sandbox_tool 工具与 sessions 删除联动共用同一实例）
sandbox_pool = SandboxPool()
