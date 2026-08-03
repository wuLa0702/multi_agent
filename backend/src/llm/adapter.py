"""LLM 适配层：OpenAI 兼容协议多 provider（deepseek / ark / zhipu）。

- 主链路：deepagents 直接接收 langchain ChatOpenAI 实例（get_chat_model 工厂）
- 兜底通道：LLMAdapter.chat 提供最简同步对话（工具/Agent 之外的场景）
- provider 切换：settings.llm_provider 驱动（.env 配置，见 core/config.py provider_config）

规范（10-api.md / 00-security.md）：
- LLM 调用必须 timeout + retry（构造时固化，调用方无需重复配置）
- API Key 只来自 .env，不进代码不进日志
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.core.config import settings

# 统一超时/重试（LLM 调用硬性要求：timeout + max_retries）
_LLM_TIMEOUT_SECONDS = 60
_LLM_MAX_RETRIES = 2


def get_chat_model() -> ChatOpenAI:
    """构造当前默认 provider 的 ChatOpenAI 实例（deepagents 主链路用）。

    Returns:
        已配置 base_url / api_key / model 的 ChatOpenAI（OpenAI 兼容协议）

    Raises:
        ValueError: provider 配置非法（key/model 缺失）
    """
    cfg = settings.provider_config()
    if not cfg["api_key"]:
        raise ValueError(
            f"LLM provider={settings.llm_provider} 未配置 api_key，请检查 .env 配置"
        )
    return ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        temperature=0.7,
        timeout=_LLM_TIMEOUT_SECONDS,
        max_retries=_LLM_MAX_RETRIES,
    )


class LLMAdapter:
    """LLM 直连适配器（兜底通道；Agent 主链路走 deepagents）。

    Attributes:
        _model: 底层 chat 模型（可注入 mock，测试用）
    """

    def __init__(self, model: BaseChatModel | None = None) -> None:
        """初始化适配器；不传 model 时用 get_chat_model() 工厂。"""
        self._model: BaseChatModel = model if model is not None else get_chat_model()

    async def chat(self, prompt: str) -> str:
        """最简对话：单次 prompt → 文本回复。

        Args:
            prompt: 用户输入（纯文本，无历史）

        Returns:
            模型回复文本

        Raises:
            Exception: LLM 调用失败（超时/限流，由上层决定重试或降级）
        """
        response = await self._model.ainvoke(prompt)
        return str(response.content)
