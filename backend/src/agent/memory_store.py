"""跨会话记忆读写（P1 Store，SqliteStore 持久化，2026-08-04）。

写入：对话结束后把 assistant 回复写入全局记忆（namespace=("memory","global")，
跨会话共享——"新会话能回忆此前会话关键事实"）。
检索：对话开始时取最近 N 条注入 SystemMessage（chat.py 调用）。

噪音控制（计划文档 C.4-3）：assistant 回复过短（< MEMORY_MIN_LEN）不写入，
避免闲聊/简短应答污染记忆库。简化版整段摘要存储，后续可接 LLM 关键事实抽取。
"""

from __future__ import annotations

import logging
import time

from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

# 记忆 namespace（全局共享——跨会话回忆）
MEMORY_NAMESPACE = ("memory", "global")

# 噪音阈值：回复短于此长度不记忆（闲聊过滤）
MEMORY_MIN_LEN = 50
# 单条记忆最大长度（截断，防库膨胀）
MEMORY_MAX_LEN = 2000
# 对话开始注入的记忆条数
MEMORY_INJECT_LIMIT = 5


async def save_conversation_memory(store: BaseStore, text: str) -> None:
    """把一次对话产出写入全局记忆（噪音阈值 + 截断 + 时间戳 key）。

    Args:
        store: langgraph store（lifespan 初始化的 SqliteStore）
        text: assistant 回复全文
    """
    if store is None:
        return
    if len(text) < MEMORY_MIN_LEN:
        logger.debug("记忆跳过：回复过短（%d 字 < 阈值 %d）", len(text), MEMORY_MIN_LEN)
        return
    key = f"mem-{int(time.time() * 1000)}"
    await store.aput(
        MEMORY_NAMESPACE,
        key,
        {"content": text[:MEMORY_MAX_LEN], "ts": int(time.time())},
    )
    logger.info("记忆写入：%s（%d 字）", key, len(text))


async def load_recent_memories(store: BaseStore, limit: int = MEMORY_INJECT_LIMIT) -> list[str]:
    """取最近 N 条记忆内容（供 SystemMessage 注入）。

    Args:
        store: langgraph store
        limit: 注入条数上限

    Returns:
        记忆内容列表（新→旧）
    """
    if store is None:
        return []
    try:
        items = await store.asearch(MEMORY_NAMESPACE, limit=limit)
    except Exception:  # noqa: BLE001 —— 记忆检索是旁路能力，失败不阻断对话
        logger.exception("记忆检索失败（跳过注入）")
        return []
    return [str(item.value.get("content", "")) for item in items if item.value]
