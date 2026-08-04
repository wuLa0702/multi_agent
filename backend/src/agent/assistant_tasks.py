"""轻量辅助任务（2026-08-04：统一走 LLMAdapter 单次调用，提示词集中在 prompts.py）。

与主 Agent 链路的区别：无工具、单次 ainvoke、失败可降级——不需要子 agent
（探讨结论见 docs/decisions/过程中优化记录）。当前任务：标题生成。
"""

from __future__ import annotations

import logging

from src.agent.prompts import TITLE_GENERATE_PROMPT

logger = logging.getLogger(__name__)

# 标题长度上限（与前端会话列表显示匹配）
TITLE_MAX_LEN = 20


async def generate_title(llm, first_message: str) -> str | None:
    """LLM 生成会话标题（≤15 字目标，截断 ≤20 字）。

    Args:
        llm: 聊天模型（注入式，mock 可测；生产用 LLMAdapter()._model）
        first_message: 用户首条消息（截 200 字喂 prompt）

    Returns:
        标题文本；LLM 失败/空输出 → None（调用方回退规则截断）

    Raises:
        无——调用方（chat.py 后台任务）负责容错，本函数不吞异常
    """
    prompt = TITLE_GENERATE_PROMPT.format(message=first_message[:200])
    response = await llm.ainvoke([("human", prompt)])
    text = str(getattr(response, "content", response) or "").strip().strip('"\'')
    if not text:
        return None
    return text[:TITLE_MAX_LEN]
