"""LLM 适配层：OpenAI 兼容协议多 provider（deepseek / ark / zhipu）。

- 主链路：deepagents 直接接收 langchain ChatOpenAI 实例（get_chat_model 工厂）
- 兜底通道：LLMAdapter.chat 提供最简同步对话（工具/Agent 之外的场景）
- 模型选择（2026-08-03 二级化）：
  - get_chat_model(model_id)：按 DB 模型 ID 构造（注册表真相源）
  - model_id=None → 默认模型；注册表未加载（脚本/异常路径）→ 回落 settings
- API key 只来自 .env（providers.api_key_env 指定变量名），不进代码不进日志
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.core.config import settings
from src.core.model_registry import get_registry

# 统一超时/重试（LLM 调用硬性要求：timeout + max_retries）
_LLM_TIMEOUT_SECONDS = 60
_LLM_MAX_RETRIES = 2


def get_chat_model(model_id: int | None = None) -> ChatOpenAI:
    """构造指定模型的 ChatOpenAI 实例（deepagents 主链路用）。

    Args:
        model_id: 数据库模型 ID（providers/models 表）；None → 默认模型
            （settings.llm_provider 厂商的默认模型）

    Returns:
        已配置 base_url / api_key / model 的 ChatOpenAI（OpenAI 兼容协议）

    Raises:
        ValueError: 模型 ID 不存在 / 密钥未配置
        ConfigError: 注册表已加载但默认模型解析失败
    """
    registry = get_registry()
    if model_id is not None:
        cfg = registry.get_model(model_id)
        if cfg is None:
            raise ValueError(f"未知模型 model_id={model_id}，请先 GET /v1/providers 查询")
    elif registry.is_loaded():
        cfg = registry.get_default_model()
    else:
        # 注册表未加载（脚本/异常路径）：回落 .env 默认配置
        env_cfg = settings.provider_config()
        return _build_chat_model(
            model_name=env_cfg["model"],
            base_url=env_cfg["base_url"],
            api_key=env_cfg["api_key"],
            provider=settings.llm_provider,
        )

    api_key = _api_key_for(cfg.api_key_env)
    if not api_key:
        raise ValueError(
            f"LLM provider={cfg.provider_slug} 未配置 api_key，"
            f"请检查 .env 的 {cfg.api_key_env}"
        )
    return _build_chat_model(
        model_name=cfg.model_name,
        base_url=cfg.base_url,
        api_key=api_key,
    )


def _api_key_for(env_name: str) -> str:
    """按 .env 变量名读密钥（settings 字段名 = 变量名小写）。"""
    return getattr(settings, env_name.lower(), "") or ""


def _build_chat_model(
    *, model_name: str, base_url: str, api_key: str
) -> ChatOpenAI:
    """统一构造 ChatOpenAI（timeout + retry 固化，见 00-security.md）。"""
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
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
