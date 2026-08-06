"""轻量辅助任务（2026-08-04：统一走 LLMAdapter 单次调用，提示词集中在 prompts.py）。

与主 Agent 链路的区别：无工具、单次调用、失败可降级——不需要子 agent
（探讨结论见 docs/decisions/过程中优化记录）。当前任务：标题生成。
模型构造统一走 LLMAdapter（2026-08-04 修正：真实激活，非死代码）。
"""

from __future__ import annotations

import logging

from src.agent.prompts import TITLE_GENERATE_PROMPT
from src.llm.adapter import LLMAdapter

logger = logging.getLogger(__name__)

# 标题长度上限（与前端会话列表显示匹配）
TITLE_MAX_LEN = 20


async def generate_title(adapter: LLMAdapter | None, first_message: str) -> str | None:
    """LLM 生成会话标题（≤15 字目标，截断 ≤20 字，统一走 LLMAdapter.chat）。

    Args:
        adapter: LLMAdapter 实例（注入式，测试用 LLMAdapter(model=fake)）；
            None → 默认 LLMAdapter()（get_chat_model 工厂）
        first_message: 用户首条消息（截 200 字喂 prompt）

    Returns:
        标题文本；LLM 失败/空输出 → None（调用方回退规则截断）

    Raises:
        Exception: LLM 调用异常（由调用方 _generate_title_in_background 容错回退）
    """
    adapter = adapter or LLMAdapter()
    prompt = TITLE_GENERATE_PROMPT.format(message=first_message[:200])
    text = (await adapter.chat(prompt)).strip().strip('"\'')
    if not text:
        return None
    return text[:TITLE_MAX_LEN]
