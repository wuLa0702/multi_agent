"""ask_human 工具：需求澄清 / 中途确认（P0 HITL 设计 §4.2/§4.4/§5.1）。

- 模型目标/约束/交付形式模糊时调用；执行计划开始前请求确认时调用
- 真实执行永不发生：interrupt_on 只开 respond 决策（agent/hitl/hitl.py），
  人类回答经中间件合成 ToolMessage 顶替工具结果（官方 respond 语义）
- 工具体 stub 抛错：若未来误配决策集（如 approve）立即炸出声，不静默
"""

from __future__ import annotations


def ask_human(message: str) -> str:
    """向用户提问澄清。

    当用户目标、范围、约束或交付形式模糊时调用，向用户提问澄清；
    也用于执行计划开始前请求用户确认。返回用户的回答。

    Args:
        message: 要问用户的问题（明确、单一问题，不要多问混一条）

    Returns:
        用户的回答文本（真实执行不会发生——respond 决策合成结果）

    Raises:
        RuntimeError: 防御性抛错——本工具命中 interrupt_on(respond)，
            人类回答经中间件合成 ToolMessage 返回，正常链路不执行
    """
    raise RuntimeError(
        "ask_human 不应被真实执行：该工具命中 interrupt_on(respond)，"
        "人类回答经中间件合成 ToolMessage 返回——请检查 interrupt_on 配置"
    )
