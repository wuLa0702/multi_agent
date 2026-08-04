"""跨会话记忆读写（P1 Store，SqliteStore 持久化，2026-08-04）。

写入：对话结束后**先经 LLM 抽取**（extract_memory_fact）——判断这段对话是否有
长期记忆价值（用户事实/偏好/决策），有则把**抽取的一句话事实**写入全局记忆
（namespace=("memory","global")，跨会话共享），无则跳过。
检索：对话开始时取最近 N 条注入 SystemMessage（chat.py 调用）。

⚠️ 2026-08-04 修正（用户评审发现）：原实现把整段回复写入（仅长度过滤），
导致所有对话全文进记忆库、注入时污染上下文。改为 LLM 抽取式——
**存的是"值得记住的事实"，不是对话全文**。
"""

from __future__ import annotations

import logging
import time

from langgraph.store.base import BaseStore

from src.agent.prompts import MEMORY_EXTRACT_PROMPT
from src.llm.adapter import LLMAdapter

logger = logging.getLogger(__name__)

# 记忆 namespace（全局共享——跨会话回忆）
MEMORY_NAMESPACE = ("memory", "global")

# 噪音阈值：抽取出的记忆过短不写入（无意义碎片过滤）
MEMORY_MIN_LEN = 5
# 单条记忆最大长度（截断，防库膨胀）
MEMORY_MAX_LEN = 500
# 对话开始注入的记忆条数
MEMORY_INJECT_LIMIT = 5



async def extract_memory_fact(
    adapter: LLMAdapter | None,
    user_message: str,
    assistant_reply: str,
) -> str | None:
    """LLM 判断并抽取长期记忆事实；无记忆价值返回 None（统一走 LLMAdapter.chat）。

    Args:
        adapter: LLMAdapter 实例（注入式，测试用 LLMAdapter(model=fake)）；
            None → 默认 LLMAdapter()（get_chat_model 工厂）
        user_message: 本条用户消息
        assistant_reply: 本条助手回复全文

    Returns:
        抽取的一句话事实（中文 ≤50 字）；无价值/异常 → None（宁可不记不错记）

    Raises:
        无——LLM 调用异常统一降级返回 None（记忆是旁路能力，不阻断对话）
    """
    try:
        adapter = adapter or LLMAdapter()
        prompt = MEMORY_EXTRACT_PROMPT.format(user=user_message[:500], assistant=assistant_reply[:1500])
        text = (await adapter.chat(prompt)).strip()
    except Exception:  # noqa: BLE001 —— 抽取失败降级：不阻断对话
        logger.exception("记忆抽取失败（跳过本次记忆）")
        return None

    # 输出解析：含"无" → 无记忆价值；否则取首行作为事实
    if not text or "无" in text[:10]:
        return None
    fact = text.split("\n")[0].strip().strip('"\'')
    if not fact or len(fact) < MEMORY_MIN_LEN:
        return None
    return fact[:MEMORY_MAX_LEN]


async def save_conversation_memory(store: BaseStore, text: str) -> None:
    """把**已抽取的记忆事实**写入全局记忆（截断 + 时间戳 key）。

    注意：调用方应先用 extract_memory_fact 抽取——本函数只存"值得记住的事实"，
    不接收对话全文（2026-08-04 修正：防全量对话进记忆库）。

    Args:
        store: langgraph store（lifespan 初始化的 SqliteStore）
        text: 已抽取的记忆事实（一句话）
    """
    if store is None:
        return
    if len(text) < MEMORY_MIN_LEN:
        logger.debug("记忆跳过：事实过短（%d 字 < 阈值 %d）", len(text), MEMORY_MIN_LEN)
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
